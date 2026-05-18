import { useEffect, useMemo, useState } from "react";
import { api, SessionSlot, Student } from "./api";
import { placementAtSchedulePass, schedulePassKey, studentChoices } from "./placementUtils";

const PASS_ROWS = [
  { key: "pass1" as const, label: "Pass 1", time: "11:00–11:30" },
  { key: "pass2" as const, label: "Pass 2", time: "11:45–13:00" },
  { key: "pass3" as const, label: "Pass 3", time: "13:15–13:45" },
];

type Props = {
  students: Student[];
  slots: SessionSlot[];
  highlightStudentId?: number | null;
  onHighlightClear?: () => void;
  onRefresh: () => Promise<void>;
  showMsg: (type: "error" | "success", text: string) => void;
};

function slotLabel(s: SessionSlot): string {
  const free = Math.max(0, s.room_capacity - s.placed_count);
  return `${s.inspiration}, ${s.room_name} (${free} lediga)`;
}

export function StudentPlacementTab({
  students,
  slots,
  highlightStudentId,
  onHighlightClear,
  onRefresh,
  showMsg,
}: Props) {
  const [schoolFilter, setSchoolFilter] = useState("");
  const [search, setSearch] = useState("");
  const [savingId, setSavingId] = useState<number | null>(null);
  const [focusedId, setFocusedId] = useState<number | null>(null);

  useEffect(() => {
    if (!highlightStudentId) return;
    const student = students.find((s) => s.id === highlightStudentId);
    if (!student) {
      onHighlightClear?.();
      return;
    }
    setSchoolFilter("");
    setSearch(`${student.first_name} ${student.last_name}`);
    setFocusedId(highlightStudentId);
    const frame = requestAnimationFrame(() => {
      document
        .getElementById(`student-row-${highlightStudentId}`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    const timer = window.setTimeout(() => {
      setFocusedId(null);
      onHighlightClear?.();
    }, 2500);
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
  }, [highlightStudentId, students, onHighlightClear]);

  const schools = useMemo(
    () => [...new Set(students.map((s) => s.school))].sort((a, b) => a.localeCompare(b, "sv")),
    [students]
  );

  const slotsByPass = useMemo(() => {
    const map: Record<"pass1" | "pass2" | "pass3", SessionSlot[]> = {
      pass1: [],
      pass2: [],
      pass3: [],
    };
    for (const s of slots) {
      const key = schedulePassKey(s.pass_type) as "pass1" | "pass2" | "pass3";
      if (key in map) map[key].push(s);
    }
    for (const key of Object.keys(map) as Array<keyof typeof map>) {
      map[key].sort((a, b) => a.room_name.localeCompare(b.room_name, "sv"));
    }
    return map;
  }, [slots]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return students.filter((s) => {
      if (schoolFilter && s.school !== schoolFilter) return false;
      if (q) {
        const name = `${s.first_name} ${s.last_name}`.toLowerCase();
        if (!name.includes(q) && !s.school.toLowerCase().includes(q)) return false;
      }
      return true;
    });
  }, [students, schoolFilter, search]);

  const changePass = async (
    student: Student,
    passType: "pass1" | "pass2" | "pass3",
    sessionSlotId: number | null
  ) => {
    setSavingId(student.id);
    try {
      await api.placements.setStudentPass(student.id, passType, sessionSlotId);
      await onRefresh();
    } catch (err) {
      showMsg("error", err instanceof Error ? err.message : "Kunde inte uppdatera");
    } finally {
      setSavingId(null);
    }
  };

  if (slots.length === 0) {
    return (
      <div className="card">
        <h2>Elever – individuella pass</h2>
        <p style={{ color: "var(--muted)" }}>
          Skapa pass under fliken Placering först (dra grupper till schemat). Därefter kan du finjustera
          här per elev.
        </p>
      </div>
    );
  }

  return (
    <div className="card student-pass-tab">
      <h2>Elever – individuella pass</h2>
      <p className="pool-hint" style={{ marginTop: 0 }}>
        Visa varje elevs val och välj rum/pass. Endast sessioner som skapats under Placering visas i listorna.
      </p>

      <div className="form-row student-pass-filters">
        <label>
          Skola
          <select value={schoolFilter} onChange={(e) => setSchoolFilter(e.target.value)}>
            <option value="">Alla skolor</option>
            {schools.map((sc) => (
              <option key={sc} value={sc}>
                {sc}
              </option>
            ))}
          </select>
        </label>
        <label>
          Sök namn
          <input
            type="search"
            placeholder="Namn eller skola…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
      </div>

      <p style={{ fontSize: "0.85rem", color: "var(--muted)", margin: "0 0 0.75rem" }}>
        Visar {filtered.length} av {students.length} elever
      </p>

      <div className="student-pass-table-wrap">
        <table className="student-pass-table">
          <thead>
            <tr>
              <th>Elev</th>
              <th>Skola</th>
              <th>Val 1</th>
              <th>Val 2</th>
              <th>Val 3</th>
              <th>Reserv</th>
              {PASS_ROWS.map((p) => (
                <th key={p.key}>
                  {p.label}
                  <span className="pass-time">{p.time}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((s) => (
              <tr
                key={s.id}
                id={`student-row-${s.id}`}
                className={[
                  savingId === s.id ? "saving" : "",
                  focusedId === s.id ? "student-row-focus" : "",
                ]
                  .filter(Boolean)
                  .join(" ") || undefined}
              >
                <td className="student-name">
                  {s.first_name} {s.last_name}
                </td>
                <td>{s.school}</td>
                <td className="choice-cell">{s.choice1 || "—"}</td>
                <td className="choice-cell">{s.choice2 || "—"}</td>
                <td className="choice-cell">{s.choice3 || "—"}</td>
                <td className="choice-cell">{s.reserve || "—"}</td>
                {PASS_ROWS.map((p) => {
                  const current = placementAtSchedulePass(s, p.key);
                  let options = slotsByPass[p.key].filter((sl) =>
                    studentChoices(s).includes(sl.inspiration)
                  );
                  if (current) {
                    const curSlot = slots.find((sl) => sl.id === current.session_slot_id);
                    if (curSlot && !options.some((o) => o.id === curSlot.id)) {
                      options = [curSlot, ...options];
                    }
                  }
                  return (
                    <td key={p.key}>
                      <select
                        className="pass-select"
                        disabled={savingId === s.id}
                        value={current?.session_slot_id ?? ""}
                        onChange={(e) => {
                          const v = e.target.value;
                          changePass(s, p.key, v === "" ? null : Number(v));
                        }}
                      >
                        <option value="">— Oplacerad —</option>
                        {options.map((sl) => (
                          <option key={sl.id} value={sl.id}>
                            {slotLabel(sl)}
                          </option>
                        ))}
                      </select>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
