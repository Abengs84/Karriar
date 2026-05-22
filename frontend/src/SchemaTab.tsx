import { useEffect, useMemo, useState } from "react";
import { api, Room, SessionSlot, Student } from "./api";
import { StudentSchedulePreview } from "./StudentSchedulePreview";

type Props = {
  rooms: Room[];
  slots: SessionSlot[];
  students: Student[];
};

type View = "overview" | "rooms" | "inspirators" | "student";

const PASS_COLUMNS = [
  { key: "pass1" as const, label: "Pass 1", time: "11:00–11:30" },
  { key: "pass2" as const, label: "Pass 2", time: "11:45–12:15 / 12:30–13:00" },
  { key: "pass3" as const, label: "Pass 3", time: "13:15–13:45" },
];

const PASS2_BLOCKS = [
  { variant: "2a" as const, passType: "pass2a", time: "11:45–12:15" },
  { variant: "2b" as const, passType: "pass2b", time: "12:30–13:00" },
];

function isBooked(slot: SessionSlot | undefined): slot is SessionSlot {
  return slot != null && slot.placed_count > 0;
}

function pass2Label(variant: "2a" | "2b", time: string): string {
  return `Pass ${variant.toUpperCase()} · ${time}`;
}

function slotLabel(slot: SessionSlot, capacity: number): string {
  const free = Math.max(0, capacity - slot.placed_count);
  return `${slot.placed_count} elever · ${free} ledig(a) plats(er) kvar`;
}

function BookedCell({
  inspiration,
  countLabel,
}: {
  inspiration: string;
  countLabel: string;
}) {
  return (
    <div className="schema-cell">
      <div className="schema-cell-inspiration">{inspiration}</div>
      <div className="schema-cell-count">{countLabel}</div>
    </div>
  );
}

function Pass2BookedCell({
  slot,
  time,
  variant,
}: {
  slot: SessionSlot;
  time: string;
  variant: "2a" | "2b";
}) {
  return (
    <div className={`schema-pass2-block schema-pass2-block-${variant}`}>
      <div className="schema-cell">
        <div className="schema-cell-inspiration">{slot.inspiration}</div>
        <div className="schema-cell-count">{slotLabel(slot, slot.room_capacity)}</div>
        <span className="schema-pass2-time">{pass2Label(variant, time)}</span>
      </div>
    </div>
  );
}

function OverviewTable({
  rooms,
  slotMap,
}: {
  rooms: Room[];
  slotMap: Map<string, SessionSlot>;
}) {
  const rows = useMemo(() => {
    return rooms
      .map((room) => {
        const pass1 = slotMap.get(`${room.id}-pass1`);
        const pass3 = slotMap.get(`${room.id}-pass3`);
        const roomSlots = (["pass1", "pass2a", "pass2b", "pass3"] as const)
          .map((pt) => slotMap.get(`${room.id}-${pt}`))
          .filter((s): s is SessionSlot => s != null);
        const pass2Booked = pass2BlocksForDisplay(roomSlots).filter((b) =>
          isBooked(slotMap.get(`${room.id}-${b.passType}`))
        );
        const hasPass1 = isBooked(pass1);
        const hasPass3 = isBooked(pass3);
        const hasAny = hasPass1 || hasPass3 || pass2Booked.length > 0;
        if (!hasAny) return null;
        return { room, pass1, pass3, pass2Booked, hasPass1, hasPass3 };
      })
      .filter((r): r is NonNullable<typeof r> => r != null);
  }, [rooms, slotMap]);

  if (rows.length === 0) {
    return <p className="schema-empty">Inga bokade pass ännu.</p>;
  }

  return (
    <div className="schema-table-wrap">
      <table className="schedule-grid schema-grid">
        <thead>
          <tr>
            <th className="room-header">Rum</th>
            {PASS_COLUMNS.map((p) => (
              <th key={p.key} className="pass-header">
                <span className="pass-label">{p.label}</span>
                <span className="pass-time">{p.time}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ room, pass1, pass3, pass2Booked, hasPass1, hasPass3 }) => (
            <tr key={room.id}>
              <th className="room-name">
                {room.name}
                <span className="room-cap">{room.capacity} platser</span>
              </th>
              <td>
                {hasPass1 && pass1 ? (
                  <BookedCell inspiration={pass1.inspiration} countLabel={slotLabel(pass1, room.capacity)} />
                ) : null}
              </td>
              <td>
                {pass2Booked.length > 0 ? (
                  <div className="schema-pass2-cell">
                    {pass2Booked.map((b) => {
                      const slot = slotMap.get(`${room.id}-${b.passType}`)!;
                      return (
                        <Pass2BookedCell
                          key={b.passType}
                          slot={slot}
                          time={b.time}
                          variant={b.variant}
                        />
                      );
                    })}
                  </div>
                ) : null}
              </td>
              <td>
                {hasPass3 && pass3 ? (
                  <BookedCell inspiration={pass3.inspiration} countLabel={slotLabel(pass3, room.capacity)} />
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RoomCard({ room, slots }: { room: Room; slots: SessionSlot[] }) {
  const byPass = new Map(slots.map((s) => [s.pass_type, s]));

  return (
    <section className="schema-room-card">
      <header className="schema-room-card-header">
        <h3>{room.name}</h3>
        <span className="schema-room-cap">{room.capacity} platser</span>
      </header>
      <ul className="schema-room-list">
        {PASS_COLUMNS.flatMap((col) => {
          if (col.key === "pass2") {
            return pass2BlocksForDisplay(slots).map((b) => {
              const slot = byPass.get(b.passType);
              return (
                <li key={b.passType}>
                  <span className="schema-room-pass">{pass2Label(b.variant, b.time)}</span>
                  {isBooked(slot) ? (
                    <>
                      <span className="schema-room-insp">{slot.inspiration}</span>
                      <span className="schema-room-meta">{slotLabel(slot, room.capacity)}</span>
                    </>
                  ) : (
                    <span className="schema-room-unbooked">Ingen bokning</span>
                  )}
                </li>
              );
            });
          }
          const slot = byPass.get(col.key);
          return (
            <li key={col.key}>
              <span className="schema-room-pass">
                {col.label} · {col.time}
              </span>
              {isBooked(slot) ? (
                <>
                  <span className="schema-room-insp">{slot.inspiration}</span>
                  <span className="schema-room-meta">{slotLabel(slot, room.capacity)}</span>
                </>
              ) : (
                <span className="schema-room-unbooked">Ingen bokning</span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

const LUNCH_TIMES = {
  "2a": "12:15–13:00",
  "2b": "11:30–12:15",
} as const;

function inspiratorLunchTrackFromPass2(slots: SessionSlot[]): "2a" | "2b" | null {
  const pass2a = slots.find((s) => s.pass_type === "pass2a");
  const pass2b = slots.find((s) => s.pass_type === "pass2b");
  if (isBooked(pass2a)) return "2a";
  if (isBooked(pass2b)) return "2b";
  if (pass2a) return "2a";
  if (pass2b) return "2b";
  return null;
}

/** Minuter från midnatt – avstånd till lunchblock (0 om tiden ligger inom lunchen). */
function distanceToLunch(anchorMin: number, track: "2a" | "2b"): number {
  const lunch =
    track === "2a"
      ? { start: 12 * 60 + 15, end: 13 * 60 }
      : { start: 11 * 60 + 30, end: 12 * 60 + 15 };
  if (anchorMin < lunch.start) return lunch.start - anchorMin;
  if (anchorMin > lunch.end) return anchorMin - lunch.end;
  return 0;
}

/** Lunchspår från pass 2, eller närmaste lunch utifrån övriga bokade pass. */
function suggestedLunchTrack(slots: SessionSlot[]): "2a" | "2b" | null {
  const fromPass2 = inspiratorLunchTrackFromPass2(slots);
  if (fromPass2) return fromPass2;

  const booked = slots.filter((s) => s.placed_count > 0);
  if (booked.length === 0) return null;

  const anchors: number[] = [];
  for (const s of booked) {
    if (s.pass_type === "pass1") anchors.push(11 * 60 + 30);
    else if (s.pass_type === "pass3") anchors.push(13 * 60 + 15);
  }
  if (anchors.length === 0) return null;

  let best: "2a" | "2b" = "2b";
  let bestDist = Infinity;
  for (const track of ["2a", "2b"] as const) {
    const total = anchors.reduce((sum, a) => sum + distanceToLunch(a, track), 0);
    if (total < bestDist) {
      bestDist = total;
      best = track;
    }
  }
  return best;
}

/** Visa båda pass 2 endast om 2a och 2b är bokade; annars ett pass (bokat eller lunchspår). */
function pass2BlocksForDisplay(slots: SessionSlot[]): typeof PASS2_BLOCKS {
  const pass2a = slots.find((s) => s.pass_type === "pass2a");
  const pass2b = slots.find((s) => s.pass_type === "pass2b");
  const aBooked = isBooked(pass2a);
  const bBooked = isBooked(pass2b);

  if (aBooked && bBooked) {
    return PASS2_BLOCKS;
  }
  if (aBooked) {
    return PASS2_BLOCKS.filter((b) => b.variant === "2a");
  }
  if (bBooked) {
    return PASS2_BLOCKS.filter((b) => b.variant === "2b");
  }

  const track = suggestedLunchTrack(slots);
  if (track === "2a") {
    return PASS2_BLOCKS.filter((b) => b.variant === "2a");
  }
  if (track === "2b") {
    return PASS2_BLOCKS.filter((b) => b.variant === "2b");
  }
  return [PASS2_BLOCKS[0]];
}

function bookedPassLabel(count: number): string {
  return count === 1 ? "1 bokat pass" : `${count} bokade pass`;
}

type InspiratorScheduleRow =
  | { kind: "pass"; key: string; passType: string; label: string }
  | { kind: "lunch"; key: string; label: string; track: "2a" | "2b" };

function pass2ScheduleRows(blocks: typeof PASS2_BLOCKS): InspiratorScheduleRow[] {
  return blocks.map((b) => ({
    kind: "pass" as const,
    key: b.passType,
    passType: b.passType,
    label: pass2Label(b.variant, b.time),
  }));
}

function inspiratorScheduleRows(slots: SessionSlot[]): InspiratorScheduleRow[] {
  const track = suggestedLunchTrack(slots);
  const pass2Blocks = pass2BlocksForDisplay(slots);
  const pass2Rows = pass2ScheduleRows(pass2Blocks);
  const lunchRow: InspiratorScheduleRow | null = track
    ? {
        kind: "lunch",
        key: "lunch",
        label: `Lunch · ${LUNCH_TIMES[track]}`,
        track,
      }
    : null;

  const rows: InspiratorScheduleRow[] = [
    { kind: "pass", key: "pass1", passType: "pass1", label: "Pass 1 · 11:00–11:30" },
  ];

  if (track === "2b") {
    if (lunchRow) rows.push(lunchRow);
    const order2b: InspiratorScheduleRow[] = [];
    for (const passType of ["pass2b", "pass2a"] as const) {
      const row = pass2Rows.find((r) => r.passType === passType);
      if (row) order2b.push(row);
    }
    rows.push(...order2b);
  } else if (track === "2a") {
    const order2a: InspiratorScheduleRow[] = [];
    for (const passType of ["pass2a", "pass2b"] as const) {
      const row = pass2Rows.find((r) => r.passType === passType);
      if (row) order2a.push(row);
    }
    rows.push(...order2a);
    if (lunchRow) rows.push(lunchRow);
  } else {
    rows.push(...pass2Rows);
  }

  rows.push({
    kind: "pass",
    key: "pass3",
    passType: "pass3",
    label: "Pass 3 · 13:15–13:45",
  });
  return rows;
}

function InspiratorCard({ inspiration, slots }: { inspiration: string; slots: SessionSlot[] }) {
  const byPass = new Map(slots.map((s) => [s.pass_type, s]));
  const bookedPassCount = slots.filter((s) => s.placed_count > 0).length;
  const lunchTrack = suggestedLunchTrack(slots);
  const scheduleRows = inspiratorScheduleRows(slots);

  return (
    <section className="schema-room-card">
      <header className="schema-room-card-header">
        <h3>{inspiration}</h3>
        <span className="schema-room-cap">
          {bookedPassLabel(bookedPassCount)}
          {lunchTrack ? ` · Lunch ${LUNCH_TIMES[lunchTrack]}` : ""}
        </span>
      </header>
      <ul className="schema-room-list">
        {scheduleRows.map((row) => {
          if (row.kind === "lunch") {
            return (
              <li key={row.key} className="schema-inspirator-lunch-row">
                <span className="schema-room-pass">{row.label}</span>
                <span className="schema-room-insp schema-inspirator-lunch-venue">
                  Restaurang Alexander
                </span>
                <span className="schema-room-meta" />
              </li>
            );
          }
          const slot = byPass.get(row.passType);
          return (
            <li key={row.key}>
              <span className="schema-room-pass">{row.label}</span>
              {isBooked(slot) ? (
                <>
                  <span className="schema-room-insp">{slot.room_name}</span>
                  <span className="schema-room-meta">
                    {slotLabel(slot, slot.room_capacity)}
                  </span>
                </>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function InspiratorsView({ slotsByInspirator }: { slotsByInspirator: Map<string, SessionSlot[]> }) {
  const inspiratorsWithBookings = useMemo(
    () =>
      [...slotsByInspirator.entries()]
        .filter(([, list]) => list.some((s) => s.placed_count > 0))
        .map(([name]) => name)
        .sort((a, b) => a.localeCompare(b, "sv")),
    [slotsByInspirator]
  );

  const [selected, setSelected] = useState<string | "all">("all");

  if (inspiratorsWithBookings.length === 0) {
    return <p className="schema-empty">Inga bokade pass ännu.</p>;
  }

  const visible =
    selected === "all"
      ? inspiratorsWithBookings
      : inspiratorsWithBookings.filter((name) => name === selected);

  return (
    <>
      <div className="schema-room-toolbar no-print">
        <label>
          Inspiratör
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            <option value="all">Alla inspiratörer med bokningar</option>
            {inspiratorsWithBookings.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="schema-rooms-print">
        {visible.map((name) => (
          <InspiratorCard
            key={name}
            inspiration={name}
            slots={slotsByInspirator.get(name) ?? []}
          />
        ))}
      </div>
    </>
  );
}

function RoomsView({
  rooms,
  slotsByRoom,
}: {
  rooms: Room[];
  slotsByRoom: Map<number, SessionSlot[]>;
}) {
  const roomsWithBookings = useMemo(
    () =>
      rooms.filter((r) => {
        const list = slotsByRoom.get(r.id) ?? [];
        return list.some((s) => s.placed_count > 0);
      }),
    [rooms, slotsByRoom]
  );

  const [selectedId, setSelectedId] = useState<number | "all">("all");

  if (roomsWithBookings.length === 0) {
    return <p className="schema-empty">Inga bokade pass ännu.</p>;
  }

  const visible =
    selectedId === "all"
      ? roomsWithBookings
      : roomsWithBookings.filter((r) => r.id === selectedId);

  return (
    <>
      <div className="schema-room-toolbar no-print">
        <label>
          Rum
          <select
            value={selectedId === "all" ? "all" : String(selectedId)}
            onChange={(e) =>
              setSelectedId(e.target.value === "all" ? "all" : Number(e.target.value))
            }
          >
            <option value="all">Alla rum med bokningar</option>
            {roomsWithBookings.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="schema-rooms-print">
        {visible.map((room) => (
          <RoomCard key={room.id} room={room} slots={slotsByRoom.get(room.id) ?? []} />
        ))}
      </div>
    </>
  );
}

function compareStudents(a: Student, b: Student): number {
  const ln = a.last_name.localeCompare(b.last_name, "sv");
  if (ln !== 0) return ln;
  return a.first_name.localeCompare(b.first_name, "sv");
}

export function SchemaTab({ rooms, slots, students }: Props) {
  const [view, setView] = useState<View>("overview");
  const [school, setSchool] = useState("");
  const [studentId, setStudentId] = useState<number | "">("");

  const schools = useMemo(() => {
    const counts = new Map<string, number>();
    for (const s of students) {
      counts.set(s.school, (counts.get(s.school) ?? 0) + 1);
    }
    return [...counts.entries()]
      .map(([entrySchool, count]) => ({ school: entrySchool, count }))
      .sort((a, b) => a.school.localeCompare(b.school, "sv"));
  }, [students]);

  const studentsInSchool = useMemo(() => {
    if (!school) return [];
    return students.filter((s) => s.school === school).sort(compareStudents);
  }, [students, school]);

  const selectedStudent = useMemo(
    () => (studentId === "" ? undefined : students.find((s) => s.id === studentId)),
    [students, studentId]
  );

  useEffect(() => {
    if (schools.length === 0) {
      setSchool("");
      setStudentId("");
      return;
    }
    if (!school || !schools.some((s) => s.school === school)) {
      setSchool(schools[0].school);
    }
  }, [schools, school]);

  useEffect(() => {
    if (studentsInSchool.length === 0) {
      setStudentId("");
      return;
    }
    if (studentId === "" || !studentsInSchool.some((s) => s.id === studentId)) {
      setStudentId(studentsInSchool[0].id);
    }
  }, [studentsInSchool, studentId]);

  const slotMap = useMemo(() => {
    const m = new Map<string, SessionSlot>();
    for (const s of slots) m.set(`${s.room_id}-${s.pass_type}`, s);
    return m;
  }, [slots]);

  const slotsByRoom = useMemo(() => {
    const m = new Map<number, SessionSlot[]>();
    for (const s of slots) {
      const list = m.get(s.room_id) ?? [];
      list.push(s);
      m.set(s.room_id, list);
    }
    return m;
  }, [slots]);

  const slotsByInspirator = useMemo(() => {
    const m = new Map<string, SessionSlot[]>();
    for (const s of slots) {
      if (!s.inspiration) continue;
      const list = m.get(s.inspiration) ?? [];
      list.push(s);
      m.set(s.inspiration, list);
    }
    return m;
  }, [slots]);

  const bookedCount = useMemo(
    () => slots.filter((s) => s.placed_count > 0).length,
    [slots]
  );

  const print = () => {
    const style = document.createElement("style");
    style.id = "schema-print-page";
    style.textContent =
      view === "overview"
        ? "@media print { @page { size: A4 landscape; margin: 10mm 10mm 12mm; } }"
        : "@media print { @page { size: A4 portrait; margin: 12mm; } }";
    document.head.appendChild(style);
    const cleanup = () => {
      style.remove();
      window.removeEventListener("afterprint", cleanup);
    };
    window.addEventListener("afterprint", cleanup);
    window.print();
  };

  const leadHint =
    view === "overview"
      ? "Översikten skrivs ut i liggande A4-format."
      : view === "rooms"
        ? "Rum-vyn skrivs ut i stående (porträtt) A4-format, ett rum per sida."
        : view === "inspirators"
          ? "Inspiratör-vyn skrivs ut i stående (porträtt) A4-format, en inspiratör per sida."
          : "Elev-schemat skrivs ut i stående A4-format, en elev per sida (samma layout som PDF).";

  const printSubtitle =
    view === "overview"
      ? "Översikt alla rum"
      : view === "rooms"
        ? "Bokningar per rum"
        : view === "inspirators"
          ? "Schema per inspiratör"
          : selectedStudent
            ? `${selectedStudent.school} – ${selectedStudent.first_name} ${selectedStudent.last_name}`
            : "Schema per elev";

  const printSectionTitle =
    view === "overview"
      ? "Översikt – rum och pass"
      : view === "rooms"
        ? "Bokningar per rum"
        : view === "inspirators"
          ? "Schema per inspiratör"
          : "Schema per elev";

  return (
    <div className="schema-tab">
      <div className="card schema-toolbar no-print">
        <div className="schema-toolbar-row">
          <h2>Schema</h2>
          <button type="button" className="primary" onClick={print}>
            Skriv ut
          </button>
        </div>
        <p className="schema-lead">
          {view === "student" ? (
            <>Personligt schema per elev. {leadHint}</>
          ) : (
            <>
              Utskriftsvänlig översikt – endast pass med placerade elever ({bookedCount}{" "}
              bokningar). {leadHint}
            </>
          )}
        </p>
        <div className="schema-view-toggle" role="tablist" aria-label="Schemavy">
          <button
            type="button"
            role="tab"
            aria-selected={view === "overview"}
            className={view === "overview" ? "active" : ""}
            onClick={() => setView("overview")}
          >
            Översikt
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === "rooms"}
            className={view === "rooms" ? "active" : ""}
            onClick={() => setView("rooms")}
          >
            Rum
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === "inspirators"}
            className={view === "inspirators" ? "active" : ""}
            onClick={() => setView("inspirators")}
          >
            Inspiratör
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === "student"}
            className={view === "student" ? "active" : ""}
            onClick={() => setView("student")}
            disabled={students.length === 0}
          >
            Elev
          </button>
        </div>
        {view === "student" && students.length > 0 && (
          <div className="schema-student-toolbar">
            <label>
              Skola
              <select value={school} onChange={(e) => setSchool(e.target.value)}>
                {schools.map((s) => (
                  <option key={s.school} value={s.school}>
                    {s.school} ({s.count})
                  </option>
                ))}
              </select>
            </label>
            <label>
              Elev
              <select
                value={studentId === "" ? "" : String(studentId)}
                onChange={(e) => setStudentId(Number(e.target.value))}
                disabled={studentsInSchool.length === 0}
              >
                {studentsInSchool.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.last_name}, {s.first_name}
                  </option>
                ))}
              </select>
            </label>
            {school ? (
              <a href={api.pdfSchoolOnePerPageUrl(school)} download>
                <button type="button" className="primary">
                  Ladda ner PDF (alla)
                </button>
              </a>
            ) : (
              <button type="button" className="primary" disabled>
                Ladda ner PDF (alla)
              </button>
            )}
          </div>
        )}
      </div>

      <div className={`schema-print-area card schema-print-${view}`}>
        <div className="schema-print-header only-print">
          <h1>Karriär – Schema</h1>
          <p>
            {printSubtitle} · {new Date().toLocaleDateString("sv-SE")}
          </p>
        </div>

        {view === "overview" ? (
          <>
            <h3 className="schema-section-title only-print">{printSectionTitle}</h3>
            <OverviewTable rooms={rooms} slotMap={slotMap} />
          </>
        ) : view === "rooms" ? (
          <>
            <h3 className="schema-section-title only-print">{printSectionTitle}</h3>
            <RoomsView rooms={rooms} slotsByRoom={slotsByRoom} />
          </>
        ) : view === "inspirators" ? (
          <>
            <h3 className="schema-section-title only-print">{printSectionTitle}</h3>
            <InspiratorsView slotsByInspirator={slotsByInspirator} />
          </>
        ) : selectedStudent ? (
          <>
            <h3 className="schema-section-title only-print">{printSectionTitle}</h3>
            <StudentSchedulePreview student={selectedStudent} />
          </>
        ) : (
          <p className="schema-empty">Inga elever importerade ännu.</p>
        )}
      </div>
    </div>
  );
}
