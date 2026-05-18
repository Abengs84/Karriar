import { useCallback, useEffect, useRef, useState } from "react";
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
import { api, Room, SessionSlot, Student } from "./api";
import { createDropToCellAnimation } from "./dropAnimation";
import { dndDebug, dndDebugGroup, dndDebugWarn, logDndDebugHelpOnce } from "./placementDndDebug";
import {
  formatCapacityReturnWarning,
  formatPartialIneligibleWarning,
  formatPlacementError,
  type PlacementResult,
} from "./placementMessages";
import type { ToastType } from "./Toast";
import { splitStudentsForPlacement, unplacedByInspirator } from "./placementUtils";

const PASS_COLUMNS = [
  { value: "pass1", label: "Pass 1", time: "11:00–11:30" },
  { value: "pass2a", label: "Pass 2a", time: "11:45–12:15" },
  { value: "pass2b", label: "Pass 2b", time: "12:30–13:00" },
  { value: "pass3", label: "Pass 3", time: "13:15–13:45" },
] as const;

const DROP_ANIM_MS = 320;
const POOL_DROP_ID = "pool-return";

function parseCellFromOverId(overId: string): { roomId: number; passType: string } | null {
  const m = overId.match(/^cell-(\d+)-(pass1|pass2a|pass2b|pass3)$/);
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
  onRefresh: () => Promise<{ students: Student[]; slots: SessionSlot[] }>;
  showMsg: (type: ToastType, text: string) => void;
};

export function PlacementBoard({
  rooms,
  students,
  slots,
  minStudentsThreshold,
  onRefresh,
  showMsg,
}: Props) {
  const [dragGroup, setDragGroup] = useState<{ inspiration: string; ids: number[] } | null>(null);
  /** Håller källkortet dolt tills drop-animation + API är klara (undviker "hopp tillbaka"). */
  const [concealedInspiration, setConcealedInspiration] = useState<string | null>(null);
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

  const groups = unplacedByInspirator(students, minStudentsThreshold);

  const dropMenuRef = useRef(dropMenu);
  dropMenuRef.current = dropMenu;

  const cancelDropPlacement = useCallback(() => {
    setDropMenu(null);
    setDragGroup(null);
    setConcealedInspiration(null);
    dropTargetRef.current = null;
    lastOverLogRef.current = null;
    dndDebug("släpp avbrutet via meny");
  }, []);

  const executePlacement = useCallback(
    async (
      studentIds: number[],
      cell: { roomId: number; passType: string },
      inspiration: string
    ) => {
      setDropMenu(null);
      if (placingLockRef.current || studentIds.length === 0) return;

      placingLockRef.current = true;
      try {
        dndDebug("API POST /placements/at-cell …", { count: studentIds.length });
        const result = await api.placements.atCell(
          studentIds,
          cell.roomId,
          cell.passType,
          inspiration
        );
        dndDebug("API svar", { ...result });

        const { slots: freshSlots } = await onRefresh();
        const freshSlot = freshSlots.find(
          (s) => s.room_id === cell.roomId && s.pass_type === cell.passType
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
      }
    },
    [onRefresh, showMsg]
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

  const onDragStart = (e: DragStartEvent) => {
    const data = e.active.data.current as { inspiration: string; studentIds: number[] };
    lastOverLogRef.current = null;
    dndDebugGroup("dragStart", () => {
      dndDebug("active.id", { activeId: String(e.active.id) });
      dndDebug("grupp", data ?? { error: "saknar data på draggable" });
    });
    if (data) {
      setDragGroup({ inspiration: data.inspiration, ids: data.studentIds });
      setConcealedInspiration(data.inspiration);
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
  };

  const onDragEnd = async (e: DragEndEvent) => {
    if (placingLockRef.current) {
      dndDebugWarn("dragEnd ignoreras – placering pågår redan (dubbel händelse)");
      return;
    }

    const group = e.active.data.current as { inspiration: string; studentIds: number[] } | undefined;
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
      cell.passType
    );
    const conflictCount =
      split.skip_already_at_pass +
      split.skip_already_with_inspirator +
      split.skip_not_chose;

    const room = rooms.find((r) => r.id === cell.roomId);
    const existingSlot = slotMap.get(`${cell.roomId}-${cell.passType}`);
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
      return;
    }

    if (conflictCount === 0) {
      await executePlacement(split.eligibleIds, cell, group.inspiration);
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
        <PoolDropColumn dragging={dragGroup != null}>
          <h3>Oplacerade grupper ({groups.length})</h3>
          <p className="pool-hint">
            Dra en grupp till en ruta i schemat. Släpp tillbaka här för att ångra. Varje elev kan
            bara ha ett pass per tid.
          </p>
          {minStudentsThreshold > 0 && (
            <p className="pool-hint pool-hint-threshold">
              Tröskel {minStudentsThreshold}: inspiratörer med färre elever visas inte här – deras
              elever listas under reserv om de har reservval.
            </p>
          )}
          <div className="pool-list">
            {groups.map(([inspiration, group]) => (
              <DraggableGroup
                key={inspiration}
                inspiration={inspiration}
                students={group}
                concealed={concealedInspiration === inspiration}
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
            Högerklicka en placerad ruta för att återställa till oplacerade grupper.
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
                          <GridCell
                            room={room}
                            passType={p.value}
                            slot={slotMap.get(`${room.id}-${p.value}`)}
                            students={students}
                            dragGroup={dragGroup}
                            onContextMenuSlot={(e, slot) => {
                              e.preventDefault();
                              e.stopPropagation();
                              setCellMenu({ x: e.clientX, y: e.clientY, slot });
                            }}
                          />
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
              executePlacement(dropMenu.eligibleIds, dropMenu.cell, dropMenu.inspiration)
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
          <button type="button" onClick={() => resetCell(cellMenu.slot)}>
            Återställ till oplacerade grupper
          </button>
        </div>
      )}

      <DragOverlay dropAnimation={dropAnimation}>
        {dragGroup && (
          <div className="inspirator-group dragging-overlay">
            <h4>{dragGroup.inspiration}</h4>
            <div className="meta">{dragGroup.ids.length} elever</div>
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

function DraggableGroup({
  inspiration,
  students,
  concealed,
}: {
  inspiration: string;
  students: Student[];
  concealed: boolean;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `group-${inspiration}`,
    data: { inspiration, studentIds: students.map((s) => s.id) },
  });

  const hidden = isDragging || concealed;

  return (
    <div
      ref={setNodeRef}
      className={`inspirator-group ${hidden ? "dragging" : ""}`}
      {...listeners}
      {...attributes}
    >
      <h4>{inspiration}</h4>
      <div className="meta">
        {students.length === 1 ? "1 elev" : `${students.length} elever`}
      </div>
    </div>
  );
}

function GridCell({
  room,
  passType,
  slot,
  students,
  dragGroup,
  onContextMenuSlot,
}: {
  room: Room;
  passType: string;
  slot?: SessionSlot;
  students: Student[];
  dragGroup: { inspiration: string; ids: number[] } | null;
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
      passType
    );
    dropTone = split.eligibleIds.length === dragGroup.ids.length ? "ok" : "conflict";
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
