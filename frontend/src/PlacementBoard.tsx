import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import {
  DndContext,
  DragEndEvent,
  DragMoveEvent,
  DragOverEvent,
  DragOverlay,
  DragStartEvent,
  PointerSensor,
  pointerWithin,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { api, AutoSolveResult, Room, SessionSlot, Student } from "./api";
import { createDropToCellAnimation } from "./dropAnimation";
import { dndDebug, dndDebugGroup, dndDebugWarn, logDndDebugHelpOnce } from "./placementDndDebug";
import {
  formatCapacityReturnWarning,
  formatInspiratorDoubleBookedError,
  formatPartialIneligibleWarning,
  formatPlacementError,
  type PlacementResult,
} from "./placementMessages";
import {
  inspiratorBookedElsewhereAtPass,
  resolvePlacementPassType,
  splitStudentsForPlacement,
  countReserveForInspirator,
  countUniqueUnplacedStudents,
  unplacedByInspirator,
} from "./placementUtils";
import type { ToastType } from "./Toast";

const PASS_COLUMNS = [
  { value: "pass1", label: "Pass 1", time: "11:00–11:30" },
  {
    value: "pass2",
    label: "Pass 2",
    time: "11:45–12:15 / 12:30–13:00",
    sub: "2a eller 2b (lunch)",
  },
  { value: "pass3", label: "Pass 3", time: "13:15–13:45" },
] as const;

const DROP_ANIM_MS = 320;
const POOL_DROP_ID = "pool-return";

type PlacementViewMode = "group" | "individual";

type DragPayload = {
  inspiration: string;
  studentIds: number[];
  overlayLabel?: string;
};

function parseCellFromOverId(overId: string): { roomId: number; passType: string } | null {
  const m = overId.match(/^cell-(\d+)-(pass1|pass2|pass3)$/);
  if (!m) return null;
  return { roomId: Number(m[1]), passType: m[2] };
}

function cellDomId(roomId: number, passType: string) {
  return `cell-${roomId}-${passType}`;
}

function pointerFromDrag(e: { activatorEvent: Event | null; delta: { x: number; y: number } }) {
  const a = e.activatorEvent;
  if (
    a &&
    "clientX" in a &&
    "clientY" in a &&
    typeof a.clientX === "number" &&
    typeof a.clientY === "number"
  ) {
    return { x: a.clientX + e.delta.x, y: a.clientY + e.delta.y };
  }
  return null;
}

/** Placera menyn vid släpp (mus/pekare), inom målcellen om möjligt. */
function dropMenuPosition(
  cell: { roomId: number; passType: string },
  pointer: { x: number; y: number }
) {
  const margin = 8;
  const menuW = 280;
  const menuH = 130;
  let x = pointer.x + 8;
  let y = pointer.y + 8;

  const el = document.getElementById(cellDomId(cell.roomId, cell.passType));
  if (el) {
    const r = el.getBoundingClientRect();
    x = Math.min(Math.max(r.left + margin, x), r.right - menuW - margin);
    y = Math.min(Math.max(r.top + margin, y), r.bottom - menuH - margin);
  }

  return {
    x: Math.min(Math.max(margin, x), window.innerWidth - menuW - margin),
    y: Math.min(Math.max(margin, y), window.innerHeight - menuH - margin),
  };
}

function resolveDropTarget(
  e: DragEndEvent,
  overId: string | null
): { type: "pool" } | { type: "cell"; cell: { roomId: number; passType: string } } | null {
  if (overId === POOL_DROP_ID) return { type: "pool" };

  const cellCollision = e.collisions?.find((c) => String(c.id).startsWith("cell-"));
  if (cellCollision) {
    const parsed = parseCellFromOverId(String(cellCollision.id));
    if (parsed) return { type: "cell", cell: parsed };
  }

  const fromOver = e.over?.data.current as { roomId: number; passType: string } | undefined;
  if (fromOver?.roomId) return { type: "cell", cell: fromOver };

  if (overId?.startsWith("cell-")) {
    const parsed = parseCellFromOverId(overId);
    if (parsed) return { type: "cell", cell: parsed };
  }

  return null;
}

type Props = {
  rooms: Room[];
  students: Student[];
  slots: SessionSlot[];
  minStudentsThreshold: number;
  autoPlacePreview?: AutoSolveResult | null;
  onRefresh: () => Promise<{ students: Student[]; slots: SessionSlot[] }>;
  showMsg: (type: ToastType, text: string) => void;
};

export function PlacementBoard({
  rooms,
  students,
  slots,
  minStudentsThreshold,
  autoPlacePreview = null,
  onRefresh,
  showMsg,
}: Props) {
  const [placementViewMode, setPlacementViewMode] = useState<PlacementViewMode>("group");
  const [dragGroup, setDragGroup] = useState<{
    inspiration: string;
    ids: number[];
    overlayLabel?: string;
  } | null>(null);
  /** Håller källkortet dolt tills drop-animation + API är klara (undviker "hopp tillbaka"). */
  const [concealedInspiration, setConcealedInspiration] = useState<string | null>(null);
  const [concealedStudentId, setConcealedStudentId] = useState<number | null>(null);
  const [cellMenu, setCellMenu] = useState<{ x: number; y: number; slot: SessionSlot } | null>(
    null
  );
  const [dropMenu, setDropMenu] = useState<{
    x: number;
    y: number;
    cell: { roomId: number; passType: string };
    inspiration: string;
    eligibleIds: number[];
    fitsInRoom: number;
    conflictCount: number;
  } | null>(null);
  const dropTargetRef = useRef<string | null>(null);
  const lastOverLogRef = useRef<string | null>(null);
  const dropPointerRef = useRef({ x: 0, y: 0 });
  const placingLockRef = useRef(false);
  const dropAnimation = useRef(
    createDropToCellAnimation(() => dropTargetRef.current, DROP_ANIM_MS)
  ).current;

  useEffect(() => {
    logDndDebugHelpOnce();
  }, []);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));

  const slotMap = new Map<string, SessionSlot>();
  for (const s of slots) {
    slotMap.set(`${s.room_id}-${s.pass_type}`, s);
  }

  const groups = useMemo(() => {
    const raw = unplacedByInspirator(students, minStudentsThreshold);
    return [...raw].sort(
      (a, b) => a[1].length - b[1].length || a[0].localeCompare(b[0], "sv")
    );
  }, [students, minStudentsThreshold]);
  const uniqueUnplacedStudents = countUniqueUnplacedStudents(
    students,
    minStudentsThreshold
  );
  const sumInGroupRows = groups.reduce((n, [, g]) => n + g.length, 0);
  const reserveCountByInspiration = useMemo(() => {
    const map = new Map<string, number>();
    for (const s of students) {
      const r = s.reserve?.trim();
      if (!r) continue;
      map.set(r, (map.get(r) ?? 0) + 1);
    }
    return map;
  }, [students]);
  const previewUnplaced =
    autoPlacePreview?.unplaced_student_count ??
    autoPlacePreview?.missing_pass_count ??
    null;
  const dbPreviewUnplaced = autoPlacePreview?.db_unplaced_student_count ?? null;
  const showPreviewMismatch =
    autoPlacePreview?.dry_run === true &&
    dbPreviewUnplaced != null &&
    previewUnplaced != null &&
    dbPreviewUnplaced !== previewUnplaced;

  const dropMenuRef = useRef(dropMenu);
  dropMenuRef.current = dropMenu;

  const cancelDropPlacement = useCallback(() => {
    setDropMenu(null);
    setDragGroup(null);
    setConcealedInspiration(null);
    setConcealedStudentId(null);
    dropTargetRef.current = null;
    lastOverLogRef.current = null;
    dndDebug("släpp avbrutet via meny");
  }, []);

  const executePlacement = useCallback(
    async (
      studentIds: number[],
      cell: { roomId: number; passType: string },
      inspiration: string,
      maxToPlace?: number
    ) => {
      setDropMenu(null);
      const ids =
        maxToPlace != null ? studentIds.slice(0, Math.max(0, maxToPlace)) : studentIds;
      if (placingLockRef.current || ids.length === 0) return;

      placingLockRef.current = true;
      const apiPassType = resolvePlacementPassType(
        cell.passType,
        slots,
        inspiration,
        cell.roomId
      );
      try {
        dndDebug("API POST /placements/at-cell …", {
          count: ids.length,
          passType: apiPassType,
        });
        const result = await api.placements.atCell(
          ids,
          cell.roomId,
          apiPassType,
          inspiration,
          minStudentsThreshold
        );
        dndDebug("API svar", { ...result });

        const { slots: freshSlots } = await onRefresh();
        const resolvedPass =
          cell.passType === "pass2"
            ? resolvePlacementPassType("pass2", freshSlots, inspiration, cell.roomId)
            : cell.passType;
        const freshSlot = freshSlots.find(
          (s) => s.room_id === cell.roomId && s.pass_type === resolvedPass
        );

        if (result.placed === 0) {
          showMsg("error", formatPlacementError(result, cell.passType));
        } else if (!freshSlot || freshSlot.placed_count === 0) {
          showMsg("error", "Placeringen sparades inte korrekt – ladda om sidan.");
        } else {
          showMsg("success", `Placerade ${result.placed} elev${result.placed === 1 ? "" : "er"}.`);
          const capacityReturned = result.skipped_capacity ?? 0;
          if (capacityReturned > 0) {
            showMsg("warn", formatCapacityReturnWarning(capacityReturned));
          }
          const ineligibleMsg = formatPartialIneligibleWarning(result, cell.passType);
          if (ineligibleMsg) {
            showMsg("warn", ineligibleMsg);
          }
        }
      } catch (err) {
        showMsg("error", err instanceof Error ? err.message : "Placering misslyckades");
        try {
          await onRefresh();
        } catch {
          /* ignore */
        }
      } finally {
        placingLockRef.current = false;
        dropTargetRef.current = null;
        lastOverLogRef.current = null;
        setDragGroup(null);
        setConcealedInspiration(null);
        setConcealedStudentId(null);
      }
    },
    [onRefresh, showMsg, slots]
  );

  useEffect(() => {
    if (!cellMenu && !dropMenu) return;
    const delay = dropMenu ? 150 : 0;
    let removeListeners: (() => void) | undefined;
    const timer = window.setTimeout(() => {
      const close = () => {
        setCellMenu(null);
        if (dropMenuRef.current) {
          cancelDropPlacement();
        }
      };
      window.addEventListener("click", close);
      window.addEventListener("scroll", close, true);
      window.addEventListener("contextmenu", close);
      removeListeners = () => {
        window.removeEventListener("click", close);
        window.removeEventListener("scroll", close, true);
        window.removeEventListener("contextmenu", close);
      };
    }, delay);
    return () => {
      window.clearTimeout(timer);
      removeListeners?.();
    };
  }, [cellMenu, dropMenu, cancelDropPlacement]);

  const pass2SwapInRoom = useMemo(() => {
    if (!cellMenu) return null;
    const slot = cellMenu.slot;
    if (slot.pass_type !== "pass2a" && slot.pass_type !== "pass2b") return null;
    const otherType = slot.pass_type === "pass2a" ? "pass2b" : "pass2a";
    const other = slots.find((s) => s.room_id === slot.room_id && s.pass_type === otherType);
    if (!other || other.inspiration === slot.inspiration) return null;
    return { roomId: slot.room_id, roomName: slot.room_name };
  }, [cellMenu, slots]);

  const resetCell = async (slot: SessionSlot) => {
    setCellMenu(null);
    try {
      const res = await api.sessionSlots.delete(slot.id);
      const n = res.removed_placements;
      showMsg(
        "success",
        n > 0
          ? `${n} elever återställda till oplacerade grupper.`
          : "Passet rensades."
      );
      await onRefresh();
    } catch (err) {
      showMsg("error", err instanceof Error ? err.message : "Kunde inte återställa");
    }
  };

  const swapPass2InRoom = async () => {
    if (!pass2SwapInRoom) return;
    setCellMenu(null);
    try {
      const res = await api.sessionSlots.swapPass2(pass2SwapInRoom.roomId);
      showMsg(
        "success",
        `Bytte plats på 2a och 2b i ${res.room_name}: «${res.inspiration_was_2a}» och «${res.inspiration_was_2b}».`
      );
      await onRefresh();
    } catch (err) {
      showMsg("error", err instanceof Error ? err.message : "Kunde inte byta plats");
    }
  };

  const onDragStart = (e: DragStartEvent) => {
    const data = e.active.data.current as DragPayload | undefined;
    lastOverLogRef.current = null;
    dndDebugGroup("dragStart", () => {
      dndDebug("active.id", { activeId: String(e.active.id) });
      dndDebug("grupp", data ?? { error: "saknar data på draggable" });
    });
    if (data) {
      setDragGroup({
        inspiration: data.inspiration,
        ids: data.studentIds,
        overlayLabel: data.overlayLabel,
      });
      if (data.studentIds.length === 1) {
        setConcealedStudentId(data.studentIds[0]);
        setConcealedInspiration(null);
      } else {
        setConcealedInspiration(data.inspiration);
        setConcealedStudentId(null);
      }
    }
  };

  const onDragMove = (e: DragMoveEvent) => {
    const p = pointerFromDrag(e);
    if (p) dropPointerRef.current = p;
  };

  const onDragOver = (e: DragOverEvent) => {
    const p = pointerFromDrag(e);
    if (p) dropPointerRef.current = p;
    const next = e.over?.id != null ? String(e.over.id) : null;
    dropTargetRef.current = next;
    if (next !== lastOverLogRef.current) {
      lastOverLogRef.current = next;
      dndDebug("dragOver → ny målcell", {
        overId: next,
        overData: e.over?.data.current ?? null,
        collisions: e.collisions?.map((c) => String(c.id)),
      });
    }
  };

  const onDragCancel = () => {
    dndDebugWarn("dragCancel", { dropTargetRef: dropTargetRef.current });
    dropTargetRef.current = null;
    lastOverLogRef.current = null;
    setDragGroup(null);
    setConcealedInspiration(null);
    setConcealedStudentId(null);
  };

  const onDragEnd = async (e: DragEndEvent) => {
    if (placingLockRef.current) {
      dndDebugWarn("dragEnd ignoreras – placering pågår redan (dubbel händelse)");
      return;
    }

    const group = e.active.data.current as DragPayload | undefined;
    const overFromEvent = e.over?.id != null ? String(e.over.id) : null;
    const overId = overFromEvent ?? dropTargetRef.current;
    if (e.over?.id != null) {
      dropTargetRef.current = String(e.over.id);
    }

    const release =
      pointerFromDrag(e) ?? dropPointerRef.current ?? null;
    const target = resolveDropTarget(e, overId);

    dndDebugGroup("dragEnd", () => {
      dndDebug("släpp", {
        activeId: String(e.active.id),
        overFromEvent,
        overIdResolved: overId,
        pointer: release,
        target,
        group: group ?? null,
        collisions: e.collisions?.map((c) => String(c.id)),
      });
    });

    if (!group) {
      dropTargetRef.current = null;
      lastOverLogRef.current = null;
      setDragGroup(null);
      setConcealedInspiration(null);
      setConcealedStudentId(null);
      return;
    }

    if (target?.type === "pool") {
      cancelDropPlacement();
      return;
    }

    const cell = target?.type === "cell" ? target.cell : null;
    if (!cell) {
      cancelDropPlacement();
      return;
    }

    const split = splitStudentsForPlacement(
      students,
      group.studentIds,
      group.inspiration,
      cell.passType,
      cell.roomId,
      slots,
      minStudentsThreshold
    );

    if (split.inspirator_double_booked) {
      const other = inspiratorBookedElsewhereAtPass(
        slots,
        group.inspiration,
        cell.passType,
        cell.roomId
      );
      const otherRoom = rooms.find((r) => r.id === other?.room_id);
      showMsg(
        "error",
        formatInspiratorDoubleBookedError(
          group.inspiration,
          otherRoom?.name ?? "annat rum"
        )
      );
      dropTargetRef.current = null;
      lastOverLogRef.current = null;
      setDragGroup(null);
      setConcealedInspiration(null);
      setConcealedStudentId(null);
      return;
    }

    const conflictCount =
      split.skip_already_at_pass +
      split.skip_already_with_inspirator +
      split.skip_not_chose;

    const room = rooms.find((r) => r.id === cell.roomId);
    const resolvedPass = resolvePlacementPassType(
      cell.passType,
      slots,
      group.inspiration,
      cell.roomId
    );
    const existingSlot = slotMap.get(`${cell.roomId}-${resolvedPass}`);
    const roomRemaining = room
      ? room.capacity - (existingSlot?.placed_count ?? 0)
      : split.eligibleIds.length;
    const fitsInRoom = Math.min(split.eligibleIds.length, Math.max(0, roomRemaining));

    dndDebug("placering analys", {
      total: group.studentIds.length,
      eligible: split.eligibleIds.length,
      fitsInRoom,
      roomRemaining,
      conflictCount,
      skips: split,
    });

    if (fitsInRoom === 0 && split.eligibleIds.length === 0) {
      const pseudoResult: PlacementResult = {
        placed: 0,
        skipped_capacity: 0,
        skipped_ineligible: conflictCount,
        skip_already_at_pass: split.skip_already_at_pass,
        skip_already_with_inspirator: split.skip_already_with_inspirator,
        skip_not_chose: split.skip_not_chose,
      };
      showMsg("error", formatPlacementError(pseudoResult, cell.passType));
      dropTargetRef.current = null;
      lastOverLogRef.current = null;
      setDragGroup(null);
      setConcealedInspiration(null);
      setConcealedStudentId(null);
      return;
    }

    if (fitsInRoom === 0) {
      const pseudoResult: PlacementResult = {
        placed: 0,
        skipped_capacity: Math.max(0, split.eligibleIds.length - roomRemaining),
        skipped_ineligible: conflictCount,
        skip_already_at_pass: split.skip_already_at_pass,
        skip_already_with_inspirator: split.skip_already_with_inspirator,
        skip_not_chose: split.skip_not_chose,
      };
      showMsg("error", formatPlacementError(pseudoResult, cell.passType));
      dropTargetRef.current = null;
      lastOverLogRef.current = null;
      setDragGroup(null);
      setConcealedInspiration(null);
      setConcealedStudentId(null);
      return;
    }

    if (conflictCount === 0) {
      await executePlacement(split.eligibleIds, cell, group.inspiration, fitsInRoom);
      return;
    }

    const menuPointer =
      release ?? { x: window.innerWidth / 2, y: window.innerHeight / 2 };
    const pos = dropMenuPosition(cell, menuPointer);
    setDropMenu({
      x: pos.x,
      y: pos.y,
      cell,
      inspiration: group.inspiration,
      eligibleIds: split.eligibleIds,
      fitsInRoom,
      conflictCount,
    });
    dndDebug("visar släpp-meny", {
      eligible: split.eligibleIds.length,
      fitsInRoom,
      conflictCount,
      pos: menuPointer,
    });
  };

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={pointerWithin}
      onDragStart={onDragStart}
      onDragMove={onDragMove}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
      onDragCancel={onDragCancel}
    >
      <div className="placement-board">
        <div className="placement-view-toolbar" role="tablist" aria-label="Placeringsläge">
          <button
            type="button"
            role="tab"
            aria-selected={placementViewMode === "group"}
            className={placementViewMode === "group" ? "active" : ""}
            onClick={() => setPlacementViewMode("group")}
          >
            Gruppdrag
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={placementViewMode === "individual"}
            className={placementViewMode === "individual" ? "active" : ""}
            onClick={() => setPlacementViewMode("individual")}
          >
            Individuellt
          </button>
        </div>
        {showPreviewMismatch && (
          <p className="placement-preview-mismatch" role="status">
            Du har <strong>förhandsgranskat</strong> auto-placering utan att verkställa. Här visas{" "}
            <strong>{dbPreviewUnplaced}</strong> elever (nuvarande databas). Efter Verkställ blir det
            cirka <strong>{previewUnplaced}</strong>. Gå till Auto-placering → Verkställ placering.
          </p>
        )}
        <PoolDropColumn dragging={dragGroup != null}>
          <h3>
            Oplacerade grupper ({groups.length}
            {uniqueUnplacedStudents > 0
              ? ` · ${uniqueUnplacedStudents} elever`
              : ""}
            )
          </h3>
          <p className="pool-hint">
            {placementViewMode === "group" ? (
              <>
                Dra en hel grupp till en ruta i schemat. Släpp tillbaka här för att ångra.
              </>
            ) : (
              <>
                Expandera grupperna och dra <strong>en elev i taget</strong> till schemat. Släpp
                tillbaka här för att ångra.
              </>
            )}{" "}
            Varje elev kan bara ha ett pass per tid. Varje inspiratör kan ligga på högst tre
            tidspass (pass 1, 2 och 3) och väljer antingen lunch 2a eller 2b – inte båda. Elever
            som redan har tre pass (t.ex. via reserv eller annat val) visas inte här. Antal
            reservval är alla elever med inspiratören som reserv (kolumn H), även om de redan är
            placerade.
            {sumInGroupRows > uniqueUnplacedStudents && uniqueUnplacedStudents > 0 && (
              <>
                {" "}
                Summan i listan ({sumInGroupRows}) är högre än antalet elever (
                {uniqueUnplacedStudents}) eftersom samma elev kan räknas i flera grupper.
              </>
            )}
          </p>
          {minStudentsThreshold > 0 && (
            <p className="pool-hint pool-hint-threshold">
              Tröskel {minStudentsThreshold}: inspiratörer med färre elever visas inte här – deras
              elever listas under reserv om de har reservval.
            </p>
          )}
          <div
            className={`pool-list ${placementViewMode === "individual" ? "pool-list--icons" : ""}`}
          >
            {groups.map(([inspiration, group]) => (
              <DraggableGroup
                key={inspiration}
                inspiration={inspiration}
                students={group}
                reserveCount={reserveCountByInspiration.get(inspiration) ?? 0}
                viewMode={placementViewMode}
                concealed={concealedInspiration === inspiration}
                concealedStudentId={concealedStudentId}
              />
            ))}
            {groups.length === 0 && (
              <p style={{ color: "var(--muted)" }}>Alla inspiratörer är placerade.</p>
            )}
          </div>
        </PoolDropColumn>

        <div className="slots-column card">
          <h3>Schema – rum och pass</h3>
          <p className="pool-hint" style={{ marginTop: 0 }}>
            Högerklicka en placerad ruta för att återställa till oplacerade grupper, eller byta
            plats på 2a och 2b när två inspiratörer delar pass 2 i samma rum.
          </p>
          {rooms.length === 0 ? (
            <p style={{ color: "var(--muted)" }}>Skapa rum under fliken Rum först.</p>
          ) : (
            <div className="schedule-grid-wrapper">
              <table className="schedule-grid">
                <thead>
                  <tr>
                    <th className="room-header">Rum</th>
                    {PASS_COLUMNS.map((p) => (
                      <th key={p.value} className="pass-header">
                        <span className="pass-label">{p.label}</span>
                        <span className="pass-time">{p.time}</span>
                        {"sub" in p && p.sub ? (
                          <span className="pass-sub">{p.sub}</span>
                        ) : null}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rooms.map((room) => (
                    <tr key={room.id}>
                      <th className="room-name">
                        {room.name}
                        <span className="room-cap">{room.capacity} platser</span>
                      </th>
                      {PASS_COLUMNS.map((p) => (
                        <td key={p.value}>
                          {p.value === "pass2" ? (
                            <Pass2GridCell
                              room={room}
                              slot2a={slotMap.get(`${room.id}-pass2a`)}
                              slot2b={slotMap.get(`${room.id}-pass2b`)}
                              students={students}
                              slots={slots}
                              dragGroup={dragGroup}
                              minStudentsThreshold={minStudentsThreshold}
                              onContextMenuSlot={(e, slot) => {
                                e.preventDefault();
                                e.stopPropagation();
                                setCellMenu({ x: e.clientX, y: e.clientY, slot });
                              }}
                            />
                          ) : (
                            <GridCell
                              room={room}
                              passType={p.value}
                              slot={slotMap.get(`${room.id}-${p.value}`)}
                              students={students}
                              slots={slots}
                              dragGroup={dragGroup}
                              minStudentsThreshold={minStudentsThreshold}
                              onContextMenuSlot={(e, slot) => {
                                e.preventDefault();
                                e.stopPropagation();
                                setCellMenu({ x: e.clientX, y: e.clientY, slot });
                              }}
                            />
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {dropMenu && (
        <div
          className="cell-context-menu drop-context-menu"
          style={{ left: dropMenu.x, top: dropMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <p className="drop-menu-hint">
            {dropMenu.conflictCount} elev{dropMenu.conflictCount === 1 ? "" : "er"} har redan detta
            pass (eller annan krock) och stannar i oplacerade grupper.
          </p>
          {dropMenu.fitsInRoom < dropMenu.eligibleIds.length && (
            <p className="drop-menu-hint">
              Rummet har plats för högst {dropMenu.fitsInRoom} till – övriga stannar i oplacerade
              grupper.
            </p>
          )}
          <button
            type="button"
            onClick={() =>
              executePlacement(
                dropMenu.eligibleIds,
                dropMenu.cell,
                dropMenu.inspiration,
                dropMenu.fitsInRoom
              )
            }
          >
            Placera {dropMenu.fitsInRoom} elev{dropMenu.fitsInRoom === 1 ? "" : "er"} utan krock
          </button>
          <button type="button" className="menu-muted" onClick={cancelDropPlacement}>
            Avbryt
          </button>
        </div>
      )}

      {cellMenu && (
        <div
          className="cell-context-menu"
          style={{ left: cellMenu.x, top: cellMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          {pass2SwapInRoom && (
            <button type="button" onClick={() => void swapPass2InRoom()}>
              Byt plats på 2a och 2b
            </button>
          )}
          <button type="button" onClick={() => resetCell(cellMenu.slot)}>
            Återställ till oplacerade grupper
          </button>
        </div>
      )}

      <DragOverlay dropAnimation={dropAnimation}>
        {dragGroup && (
          <div
            className={`inspirator-group dragging-overlay ${dragGroup.overlayLabel ? "group-student-icon-wrap dragging-overlay" : ""}`}
          >
            {dragGroup.overlayLabel ? (
              <StudentDragIcon label={dragGroup.overlayLabel} inspiration={dragGroup.inspiration} />
            ) : (
              <>
                <h4>{dragGroup.inspiration}</h4>
                <div className="meta">
                  <GroupStudentMeta
                    count={dragGroup.ids.length}
                    reserveCount={countReserveForInspirator(students, dragGroup.inspiration)}
                  />
                </div>
              </>
            )}
          </div>
        )}
      </DragOverlay>
    </DndContext>
  );
}

function PoolDropColumn({
  children,
  dragging,
}: {
  children: React.ReactNode;
  dragging: boolean;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: POOL_DROP_ID });

  return (
    <div
      ref={setNodeRef}
      className={`pool-column card ${dragging && isOver ? "pool-drop-active" : ""}`}
    >
      {dragging && isOver && <p className="pool-return-banner">Släpp här för att ångra</p>}
      {children}
    </div>
  );
}

function GroupStudentMeta({
  count,
  reserveCount,
}: {
  count: number;
  reserveCount: number;
}) {
  const elevLabel = count === 1 ? "1 elev" : `${count} elever`;
  if (reserveCount <= 0) return <>{elevLabel}</>;
  const reservLabel =
    reserveCount === 1 ? "1 reservval" : `${reserveCount} reservval`;
  return (
    <>
      {elevLabel} · {reservLabel}
    </>
  );
}

function DraggableGroup({
  inspiration,
  students,
  reserveCount,
  viewMode,
  concealed,
  concealedStudentId,
}: {
  inspiration: string;
  students: Student[];
  reserveCount: number;
  viewMode: PlacementViewMode;
  concealed: boolean;
  concealedStudentId: number | null;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `group-${inspiration}`,
    data: { inspiration, studentIds: students.map((s) => s.id) },
    disabled: viewMode === "individual",
  });

  const hidden = viewMode === "group" && (isDragging || concealed);

  return (
    <div
      ref={viewMode === "group" ? setNodeRef : undefined}
      className={[
        "inspirator-group",
        viewMode === "individual" ? "inspirator-group--pool" : "",
        hidden ? "dragging" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      {...(viewMode === "group" ? { ...listeners, ...attributes } : {})}
    >
      <h4>{inspiration}</h4>
      <div className="meta">
        <GroupStudentMeta count={students.length} reserveCount={reserveCount} />
        {viewMode === "individual" ? " · dra ikon nedan" : ""}
      </div>
      {viewMode === "individual" && (
        <ul className="group-student-list">
          {students.map((s) => (
            <DraggableStudent
              key={s.id}
              student={s}
              inspiration={inspiration}
              concealed={concealedStudentId === s.id}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function StudentPersonIcon() {
  return (
    <svg
      className="group-student-icon-svg"
      viewBox="0 0 24 24"
      width={16}
      height={16}
      aria-hidden
    >
      <circle cx="12" cy="8" r="3.5" fill="currentColor" />
      <path
        fill="currentColor"
        d="M5 20c0-3.5 3.1-6 7-6s7 2.5 7 6v1H5v-1z"
      />
    </svg>
  );
}

function StudentDragIcon({
  label,
  inspiration,
}: {
  label: string;
  inspiration: string;
}) {
  return (
    <div className="group-student-icon-wrap group-student-icon-wrap--overlay">
      <span className="group-student-icon" aria-hidden>
        <StudentPersonIcon />
      </span>
      <span className="group-student-overlay-meta">
        <strong>{label}</strong>
        <span>{inspiration}</span>
      </span>
    </div>
  );
}

type StudentTooltipAlign = "center" | "start" | "end";

type StudentTooltipPos = {
  x: number;
  y: number;
  align: StudentTooltipAlign;
};

const TOOLTIP_EST_WIDTH = 288;
const TOOLTIP_VIEWPORT_MARGIN = 10;

function StudentTooltipContent({ student, label }: { student: Student; label: string }) {
  return (
    <>
      <span className="group-student-tooltip-name">{label}</span>
      <span>Val 1: {student.choice1?.trim() || "—"}</span>
      <span>Val 2: {student.choice2?.trim() || "—"}</span>
      <span>Val 3: {student.choice3?.trim() || "—"}</span>
      <span>Reserv: {student.reserve?.trim() || "—"}</span>
    </>
  );
}

function DraggableStudent({
  student,
  inspiration,
  concealed,
}: {
  student: Student;
  inspiration: string;
  concealed: boolean;
}) {
  const label = `${student.first_name} ${student.last_name}`;
  const choiceLine = (rank: string, value: string | null) =>
    `${rank}: ${value?.trim() || "—"}`;
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [tooltip, setTooltip] = useState<StudentTooltipPos | null>(null);
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `student-${student.id}-${inspiration}`,
    data: {
      inspiration,
      studentIds: [student.id],
      overlayLabel: label,
    },
  });

  const mergeRef = useCallback(
    (node: HTMLDivElement | null) => {
      setNodeRef(node);
      wrapRef.current = node;
    },
    [setNodeRef]
  );

  const showTooltip = useCallback(() => {
    const el = wrapRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const centerX = r.left + r.width / 2;
    let align: StudentTooltipAlign = "center";
    let x = centerX;
    if (centerX - TOOLTIP_EST_WIDTH / 2 < TOOLTIP_VIEWPORT_MARGIN) {
      align = "start";
      x = r.left;
    } else if (centerX + TOOLTIP_EST_WIDTH / 2 > window.innerWidth - TOOLTIP_VIEWPORT_MARGIN) {
      align = "end";
      x = r.right;
    }
    setTooltip({ x, y: r.top - 6, align });
  }, []);

  const hideTooltip = useCallback(() => setTooltip(null), []);

  const hidden = isDragging || concealed;

  const tooltipStyle: CSSProperties =
    tooltip?.align === "center"
      ? { left: tooltip.x, top: tooltip.y, transform: "translate(-50%, -100%)" }
      : tooltip?.align === "start"
        ? { left: tooltip.x, top: tooltip.y, transform: "translateY(-100%)" }
        : tooltip
          ? { right: window.innerWidth - tooltip.x, top: tooltip.y, transform: "translateY(-100%)" }
          : {};

  return (
    <li>
      <div
        ref={mergeRef}
        className={`group-student-icon-wrap ${hidden ? "dragging" : ""}`}
        {...listeners}
        {...attributes}
        onMouseEnter={showTooltip}
        onMouseLeave={hideTooltip}
        onFocus={showTooltip}
        onBlur={hideTooltip}
        aria-label={[
          label,
          choiceLine("Val 1", student.choice1),
          choiceLine("Val 2", student.choice2),
          choiceLine("Val 3", student.choice3),
          choiceLine("Reserv", student.reserve),
        ].join(", ")}
      >
        <span className="group-student-icon">
          <StudentPersonIcon />
        </span>
      </div>
      {tooltip &&
        !hidden &&
        createPortal(
          <div
            className={`group-student-tooltip group-student-tooltip--fixed group-student-tooltip--${tooltip.align}`}
            style={tooltipStyle}
            role="tooltip"
          >
            <StudentTooltipContent student={student} label={label} />
          </div>,
          document.body
        )}
    </li>
  );
}

function Pass2GridCell({
  room,
  slot2a,
  slot2b,
  students,
  slots,
  dragGroup,
  minStudentsThreshold,
  onContextMenuSlot,
}: {
  room: Room;
  slot2a?: SessionSlot;
  slot2b?: SessionSlot;
  students: Student[];
  slots: SessionSlot[];
  dragGroup: { inspiration: string; ids: number[] } | null;
  minStudentsThreshold: number;
  onContextMenuSlot: (e: React.MouseEvent, slot: SessionSlot) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({
    id: `cell-${room.id}-pass2`,
    data: { roomId: room.id, passType: "pass2" },
  });

  let dropTone: "ok" | "conflict" | null = null;
  if (isOver && dragGroup) {
    const split = splitStudentsForPlacement(
      students,
      dragGroup.ids,
      dragGroup.inspiration,
      "pass2",
      room.id,
      slots,
      minStudentsThreshold
    );
    dropTone =
      split.inspirator_double_booked || split.eligibleIds.length !== dragGroup.ids.length
        ? "conflict"
        : "ok";
  }

  const blocks: { variant: "2a" | "2b"; slot?: SessionSlot; time: string }[] = [
    { variant: "2a", slot: slot2a, time: "11:45–12:15" },
    { variant: "2b", slot: slot2b, time: "12:30–13:00" },
  ];

  const hasContent = blocks.some((b) => b.slot != null);
  const anyOccupied = blocks.some((b) => b.slot && b.slot.placed_count > 0);
  const anyReserved = blocks.some(
    (b) => b.slot && b.slot.placed_count === 0
  );
  const full =
    anyOccupied &&
    blocks.every(
      (b) => !b.slot || !b.slot.placed_count || b.slot.placed_count >= room.capacity
    );

  const dragInspiration = dragGroup?.inspiration;
  const lockedVariant =
    dragInspiration != null
      ? resolvePlacementPassType("pass2", slots, dragInspiration, room.id)
      : null;

  return (
    <div
      id={cellDomId(room.id, "pass2")}
      data-room-id={room.id}
      data-pass-type="pass2"
      ref={setNodeRef}
      className={`grid-cell pass2-merged ${dropTone === "ok" ? "drop-target-ok" : ""} ${dropTone === "conflict" ? "drop-target-conflict" : ""} ${full ? "full" : ""} ${anyReserved && !anyOccupied ? "reserved" : ""} ${!hasContent ? "empty" : ""}`}
    >
      {blocks.map(({ variant, slot, time }) => {
        const occupied = slot != null && slot.placed_count > 0;
        const reserved = slot != null && slot.placed_count === 0;
        const isLockedTarget =
          lockedVariant === (variant === "2a" ? "pass2a" : "pass2b");
        if (!occupied && !reserved) return null;
        return (
          <div
            key={variant}
            className={`pass2-block ${isLockedTarget && isOver ? "pass2-block-target" : ""}`}
            onContextMenu={(e) => {
              if (slot && (occupied || reserved)) onContextMenuSlot(e, slot);
            }}
          >
            <span className="pass2-block-time">{variant} · {time}</span>
            <div className="cell-inspiration">{slot!.inspiration}</div>
            {occupied ? (
              <div className="cell-count">
                {slot!.placed_count} elever ·{" "}
                {Math.max(0, room.capacity - slot!.placed_count)} ledig(a) plats(er) kvar
              </div>
            ) : (
              <div className="cell-count">Tom cell – dra ny grupp hit</div>
            )}
          </div>
        );
      })}
      {!hasContent && <span className="cell-placeholder">Dra hit</span>}
    </div>
  );
}

function GridCell({
  room,
  passType,
  slot,
  students,
  slots,
  dragGroup,
  minStudentsThreshold,
  onContextMenuSlot,
}: {
  room: Room;
  passType: string;
  slot?: SessionSlot;
  students: Student[];
  slots: SessionSlot[];
  dragGroup: { inspiration: string; ids: number[] } | null;
  minStudentsThreshold: number;
  onContextMenuSlot: (e: React.MouseEvent, slot: SessionSlot) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({
    id: `cell-${room.id}-${passType}`,
    data: { roomId: room.id, passType },
  });

  const reserved = slot != null && slot.placed_count === 0;
  const occupied = slot != null && slot.placed_count > 0;
  const full = occupied && slot.placed_count >= room.capacity;

  let dropTone: "ok" | "conflict" | null = null;
  if (isOver && dragGroup) {
    const split = splitStudentsForPlacement(
      students,
      dragGroup.ids,
      dragGroup.inspiration,
      passType,
      room.id,
      slots,
      minStudentsThreshold
    );
    dropTone =
      split.inspirator_double_booked || split.eligibleIds.length !== dragGroup.ids.length
        ? "conflict"
        : "ok";
  }

  return (
    <div
      id={cellDomId(room.id, passType)}
      data-room-id={room.id}
      data-pass-type={passType}
      ref={setNodeRef}
      className={`grid-cell ${dropTone === "ok" ? "drop-target-ok" : ""} ${dropTone === "conflict" ? "drop-target-conflict" : ""} ${full ? "full" : ""} ${reserved ? "reserved" : ""} ${!occupied && !reserved ? "empty" : ""}`}
      onContextMenu={(e) => {
        if (slot && (occupied || reserved)) onContextMenuSlot(e, slot);
      }}
    >
      {occupied && slot ? (
        <>
          <div className="cell-inspiration">{slot.inspiration}</div>
          <div className="cell-count">
            {slot.placed_count} elever · {Math.max(0, room.capacity - slot.placed_count)} ledig(a) plats(er) kvar
          </div>
        </>
      ) : reserved && slot ? (
        <>
          <div className="cell-inspiration cell-inspiration-reserved">{slot.inspiration}</div>
          <div className="cell-count">Tom cell – dra ny grupp hit för att ersätta</div>
        </>
      ) : (
        <span className="cell-placeholder">Dra hit</span>
      )}
    </div>
  );
}
