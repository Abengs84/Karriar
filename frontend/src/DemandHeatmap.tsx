import { useMemo } from "react";
import type { PreviewInspiratorStatus, Room, SessionSlot, Student } from "./api";
import {
  getSuppressedInspirations,
  isPlacedWithInspirator,
  studentRequiredChoices,
} from "./placementUtils";

export type HeatmapRow = {
  inspiration: string;
  choice1: number;
  choice2: number;
  choice3: number;
  reserve: number;
  required: number;
  placed: number;
  unplaced: number;
  capacity: number;
  passSlots: number;
};

type PassKey = "pass1" | "pass2" | "pass3";

export type RoomPresence = {
  passes: Partial<Record<PassKey, { placed: number; capacity: number }>>;
  totalPlaced: number;
  passCount: number;
};

const PASS_LABELS: Record<PassKey, string> = {
  pass1: "1",
  pass2: "2",
  pass3: "3",
};

function collectInspirations(students: Student[]): string[] {
  const set = new Set<string>();
  for (const s of students) {
    for (const c of [s.choice1, s.choice2, s.choice3, s.reserve]) {
      if (c) set.add(c);
    }
  }
  return [...set].sort((a, b) => a.localeCompare(b, "sv"));
}

function slotPassKey(passType: string): PassKey | null {
  if (passType === "pass1") return "pass1";
  if (passType === "pass2a" || passType === "pass2b") return "pass2";
  if (passType === "pass3") return "pass3";
  return null;
}

export function getRoomPresence(
  inspiration: string,
  roomId: number,
  slots: SessionSlot[]
): RoomPresence | null {
  const relevant = slots.filter(
    (s) => s.inspiration === inspiration && s.room_id === roomId
  );
  if (relevant.length === 0) return null;

  const passes: RoomPresence["passes"] = {};
  let totalPlaced = 0;

  for (const sl of relevant) {
    const pk = slotPassKey(sl.pass_type);
    if (!pk) continue;
    const prev = passes[pk];
    if (!prev) {
      passes[pk] = { placed: sl.placed_count, capacity: sl.room_capacity };
    } else {
      prev.placed += sl.placed_count;
      prev.capacity = Math.max(prev.capacity, sl.room_capacity);
    }
    totalPlaced += sl.placed_count;
  }

  const passCount = Object.keys(passes).length;
  if (passCount === 0) return null;

  return { passes, totalPlaced, passCount };
}

export function buildHeatmapRows(students: Student[], slots: SessionSlot[]): HeatmapRow[] {
  const inspirations = collectInspirations(students);
  const capacityByInsp = new Map<string, number>();
  const passSlotsByInsp = new Map<string, number>();

  for (const sl of slots) {
    const insp = sl.inspiration;
    capacityByInsp.set(insp, (capacityByInsp.get(insp) ?? 0) + sl.room_capacity);
    passSlotsByInsp.set(insp, (passSlotsByInsp.get(insp) ?? 0) + 1);
  }

  const rows: HeatmapRow[] = [];

  for (const inspiration of inspirations) {
    let choice1 = 0;
    let choice2 = 0;
    let choice3 = 0;
    let reserve = 0;
    let required = 0;
    let placed = 0;
    let unplaced = 0;

    for (const s of students) {
      if (s.choice1 === inspiration) choice1++;
      if (s.choice2 === inspiration) choice2++;
      if (s.choice3 === inspiration) choice3++;
      if (s.reserve === inspiration) reserve++;
      if (!studentRequiredChoices(s).includes(inspiration)) continue;
      required++;
      if (isPlacedWithInspirator(s, inspiration)) placed++;
      else unplaced++;
    }

    rows.push({
      inspiration,
      choice1,
      choice2,
      choice3,
      reserve,
      required,
      placed,
      unplaced,
      capacity: capacityByInsp.get(inspiration) ?? 0,
      passSlots: passSlotsByInsp.get(inspiration) ?? 0,
    });
  }

  return rows.sort(
    (a, b) => b.required - a.required || a.inspiration.localeCompare(b.inspiration, "sv")
  );
}

function splitInspiration(name: string): { field: string; person: string } {
  const m = name.match(/^(.+?)\s*[-–]\s*(.+)$/);
  if (!m) return { field: name, person: "" };
  return { field: m[1].trim(), person: m[2].trim() };
}

function heatStyle(value: number, max: number, hue = 214): React.CSSProperties {
  if (max <= 0 || value <= 0) return {};
  const t = Math.min(1, value / max);
  const alpha = 0.1 + t * 0.72;
  return { backgroundColor: `hsla(${hue}, 58%, 46%, ${alpha})` };
}

function stressStyle(required: number, capacity: number): React.CSSProperties {
  if (required <= 0) return {};
  const ratio = capacity > 0 ? required / capacity : required > 0 ? 2 : 0;
  const t = Math.min(1, ratio);
  const hue = ratio > 1 ? 8 : 152;
  const alpha = 0.12 + t * 0.7;
  return { backgroundColor: `hsla(${hue}, 52%, 42%, ${alpha})` };
}

function chipFillStyle(placed: number, roomCapacity: number, passCount: number): React.CSSProperties {
  if (placed <= 0 || roomCapacity <= 0) return {};
  const t = Math.min(1, placed / (roomCapacity * Math.max(1, passCount)));
  return {
    borderColor: `hsla(168, 42%, 38%, ${0.35 + t * 0.55})`,
    backgroundColor: `hsla(168, 40%, 94%, ${0.4 + t * 0.5})`,
  };
}

function presenceSignature(p: RoomPresence | null): string {
  if (!p) return "";
  const parts = (["pass1", "pass2", "pass3"] as PassKey[])
    .map((pk) => {
      const x = p.passes[pk];
      return x ? `${pk}:${x.placed}` : "";
    })
    .filter(Boolean);
  return parts.join("|");
}

type RoomEntry = { room: Room; presence: RoomPresence };

function inspiratorRooms(
  inspiration: string,
  rooms: Room[],
  slots: SessionSlot[]
): RoomEntry[] {
  const entries: RoomEntry[] = [];
  for (const room of rooms) {
    const presence = getRoomPresence(inspiration, room.id, slots);
    if (presence) entries.push({ room, presence });
  }
  return entries.sort((a, b) => a.room.name.localeCompare(b.room.name, "sv"));
}

function chipDiff(
  current: RoomPresence | null,
  preview: RoomPresence | null
): "new" | "changed" | "same" | null {
  if (!preview) return null;
  if (!current) return "new";
  if (presenceSignature(current) !== presenceSignature(preview)) return "changed";
  return "same";
}

function InspiratorCell({ name }: { name: string }) {
  const { field, person } = splitInspiration(name);
  return (
    <th className="heatmap-insp-col" title={name}>
      <span className="heatmap-insp-field">{field}</span>
      {person ? <span className="heatmap-insp-person">{person}</span> : null}
    </th>
  );
}

function RoomsCell({
  previewEntries,
  currentEntries,
  showDiff,
}: {
  previewEntries: RoomEntry[];
  currentEntries: RoomEntry[];
  showDiff: boolean;
}) {
  if (previewEntries.length === 0) {
    return <td className="heatmap-rooms-col heatmap-rooms-empty">—</td>;
  }

  const currentByRoom = new Map(currentEntries.map((e) => [e.room.id, e.presence]));
  const passOrder: PassKey[] = ["pass1", "pass2", "pass3"];

  return (
    <td className="heatmap-rooms-col">
      <div className="heatmap-rooms-list">
        {previewEntries.map(({ room, presence }) => {
          const diff = showDiff
            ? chipDiff(currentByRoom.get(room.id) ?? null, presence)
            : null;
          return (
            <span
              key={room.id}
              className={[
                "heatmap-room-chip",
                diff === "new" ? "heatmap-room-chip-new" : "",
                diff === "changed" ? "heatmap-room-chip-changed" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              style={chipFillStyle(presence.totalPlaced, room.capacity, presence.passCount)}
              title={`${room.name} (${room.capacity} platser) · ${presence.totalPlaced} elever${diff === "new" ? " · ny i förhandsgranskning" : diff === "changed" ? " · ändrad" : ""}`}
            >
              <span className="heatmap-room-chip-name">{room.name}</span>
              <span className="heatmap-room-chip-passes">
                {passOrder.map((pk) => {
                  const p = presence.passes[pk];
                  if (!p) return null;
                  return (
                    <span key={pk} className="heatmap-room-pass">
                      {PASS_LABELS[pk]}·{p.placed}
                    </span>
                  );
                })}
              </span>
            </span>
          );
        })}
      </div>
    </td>
  );
}

type Props = {
  students: Student[];
  slots: SessionSlot[];
  rooms: Room[];
  minStudentsThreshold: number;
  previewSlots?: SessionSlot[] | null;
  previewInspiratorStatus?: PreviewInspiratorStatus[] | null;
};

export function DemandHeatmap({
  students,
  slots,
  rooms,
  minStudentsThreshold,
  previewSlots = null,
  previewInspiratorStatus = null,
}: Props) {
  const isPreview = previewSlots != null && previewInspiratorStatus != null;
  const displaySlots = isPreview && previewSlots ? previewSlots : slots;

  const rows = useMemo(() => buildHeatmapRows(students, slots), [students, slots]);
  const statusByInsp = useMemo(() => {
    const m = new Map<string, PreviewInspiratorStatus>();
    if (previewInspiratorStatus) {
      for (const s of previewInspiratorStatus) m.set(s.inspiration, s);
    }
    return m;
  }, [previewInspiratorStatus]);

  const roomList = useMemo(
    () => [...rooms].sort((a, b) => a.name.localeCompare(b.name, "sv")),
    [rooms]
  );
  const suppressed = useMemo(
    () => getSuppressedInspirations(students, minStudentsThreshold),
    [students, minStudentsThreshold]
  );

  const max = useMemo(() => {
    let c1 = 0;
    let c2 = 0;
    let c3 = 0;
    let res = 0;
    let req = 0;
    for (const r of rows) {
      c1 = Math.max(c1, r.choice1);
      c2 = Math.max(c2, r.choice2);
      c3 = Math.max(c3, r.choice3);
      res = Math.max(res, r.reserve);
      req = Math.max(req, r.required);
    }
    return { c1, c2, c3, res, req };
  }, [rows]);

  if (rows.length === 0) {
    return (
      <p className="heatmap-empty" style={{ color: "var(--muted)" }}>
        Ingen elevdata – importera elever först.
      </p>
    );
  }

  return (
    <div className={`demand-heatmap ${isPreview ? "demand-heatmap-preview" : ""}`}>
      <div className="heatmap-header">
        <h3>Efterfrågan</h3>
        {isPreview && (
          <span className="heatmap-preview-badge">Förhandsgranskning</span>
        )}
        <ul className="heatmap-legend" aria-label="Förklaring">
          <li>
            <span className="heatmap-swatch heatmap-swatch-c1" /> Val 1
          </li>
          <li>
            <span className="heatmap-swatch heatmap-swatch-c2" /> Val 2
          </li>
          <li>
            <span className="heatmap-swatch heatmap-swatch-c3" /> Val 3
          </li>
          <li>
            <span className="heatmap-swatch heatmap-swatch-res" /> Reserv
          </li>
          <li>
            <span className="heatmap-swatch heatmap-swatch-room" /> Rum · pass
          </li>
          {isPreview && (
            <>
              <li>
                <span className="heatmap-swatch heatmap-swatch-new" /> Nytt rum
              </li>
              <li>
                <span className="heatmap-swatch heatmap-swatch-changed" /> Ändrat
              </li>
            </>
          )}
        </ul>
      </div>
      <p className="heatmap-intro">
        {isPreview ? (
          <>
            Visar <strong>simulerat utfall</strong> efter förhandsgranskning (ej sparat). Rum-chips
            jämförs med nuvarande schema.
          </>
        ) : (
          <>
            Mörkare fält = fler val. <strong>Rum</strong> visar sessioner i nuvarande schema. Kör
            förhandsgranskning för att se föreslagna rum.
          </>
        )}{" "}
        Under tröskel{minStudentsThreshold > 0 ? ` ${minStudentsThreshold}` : ""} nedtonade.
      </p>
      <div className="heatmap-table-wrap">
        <table className="heatmap-table">
          <thead>
            <tr>
              <th className="heatmap-insp-col">Inspiratör</th>
              <th>Val 1</th>
              <th>Val 2</th>
              <th>Val 3</th>
              <th>Res.</th>
              <th>Elever</th>
              <th title="Elever / kapacitet i sessioner">Belastn.</th>
              <th>Oplac.</th>
              <th className="heatmap-rooms-col-head">Rum</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const hidden = suppressed.has(r.inspiration);
              const previewStatus = statusByInsp.get(r.inspiration);
              const capacity = isPreview && previewStatus ? previewStatus.capacity : r.capacity;
              const unplaced = isPreview && previewStatus ? previewStatus.unplaced : r.unplaced;
              const currentRoomEntries = inspiratorRooms(r.inspiration, roomList, slots);
              const previewRoomEntries = inspiratorRooms(
                r.inspiration,
                roomList,
                displaySlots
              );

              return (
                <tr key={r.inspiration} className={hidden ? "heatmap-row-suppressed" : undefined}>
                  <InspiratorCell name={r.inspiration} />
                  <td style={heatStyle(r.choice1, max.c1)}>{r.choice1 || "—"}</td>
                  <td style={heatStyle(r.choice2, max.c2, 248)}>{r.choice2 || "—"}</td>
                  <td style={heatStyle(r.choice3, max.c3, 278)}>{r.choice3 || "—"}</td>
                  <td style={heatStyle(r.reserve, max.res, 38)}>{r.reserve || "—"}</td>
                  <td style={heatStyle(r.required, max.req)}>{r.required}</td>
                  <td
                    className={isPreview ? "heatmap-cell-preview" : undefined}
                    style={stressStyle(r.required, capacity)}
                    title={
                      capacity > 0
                        ? `${r.required} / ${capacity}${isPreview ? " (förhandsgranskning)" : ""}`
                        : `${r.required} elever, ingen session`
                    }
                  >
                    {capacity > 0 ? `${r.required}/${capacity}` : r.required > 0 ? "?" : "—"}
                  </td>
                  <td
                    className={[
                      unplaced > 0 ? "heatmap-warn" : undefined,
                      isPreview ? "heatmap-cell-preview" : undefined,
                    ]
                      .filter(Boolean)
                      .join(" ") || undefined}
                  >
                    {unplaced || "—"}
                  </td>
                  <RoomsCell
                    previewEntries={isPreview ? previewRoomEntries : currentRoomEntries}
                    currentEntries={currentRoomEntries}
                    showDiff={isPreview}
                  />
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {roomList.length === 0 && (
        <p className="heatmap-no-rooms">Skapa rum under fliken Rum för att se rumsinformation.</p>
      )}
    </div>
  );
}
