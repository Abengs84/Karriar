import { useMemo } from "react";
import { Student } from "./api";

type Props = {
  students: Student[];
  onStudentClick: (studentId: number) => void;
};

type LunchTrack = "2a" | "2b";

const TRACKS: {
  track: LunchTrack;
  title: string;
  lunchTime: string;
  passTime: string;
}[] = [
  {
    track: "2a",
    title: "Lunchspår 2a",
    passTime: "Pass 2: 11:45–12:15",
    lunchTime: "Lunch: 12:15–13:00",
  },
  {
    track: "2b",
    title: "Lunchspår 2b",
    lunchTime: "Lunch: 11:30–12:15",
    passTime: "Pass 2: 12:30–13:00",
  },
];

function studentName(s: Student): string {
  return `${s.first_name} ${s.last_name}`;
}

function compareStudents(a: Student, b: Student): number {
  const ln = a.last_name.localeCompare(b.last_name, "sv");
  if (ln !== 0) return ln;
  return a.first_name.localeCompare(b.first_name, "sv");
}

export function LunchTab({ students, onStudentClick }: Props) {
  const { byTrack, unassigned } = useMemo(() => {
    const byTrack: Record<LunchTrack, Student[]> = { "2a": [], "2b": [] };
    const unassigned: Student[] = [];
    for (const s of students) {
      if (s.lunch_track === "2a") byTrack["2a"].push(s);
      else if (s.lunch_track === "2b") byTrack["2b"].push(s);
      else unassigned.push(s);
    }
    byTrack["2a"].sort(compareStudents);
    byTrack["2b"].sort(compareStudents);
    unassigned.sort(compareStudents);
    return { byTrack, unassigned };
  }, [students]);

  const totalAssigned = byTrack["2a"].length + byTrack["2b"].length;

  return (
    <div className="card lunch-tab">
      <h2>Lunch</h2>
      <p className="lunch-tab-lead">
        Översikt över lunchspår enligt placering på pass 2a eller 2b. Totalt{" "}
        <strong>{totalAssigned}</strong> elever med tilldelat lunchspår av{" "}
        {students.length}.
      </p>

      <div className="lunch-summary">
        {TRACKS.map(({ track, lunchTime }) => (
          <div key={track} className={`lunch-summary-card lunch-summary-${track}`}>
            <span className="lunch-summary-label">Spår {track}</span>
            <span className="lunch-summary-count">{byTrack[track].length}</span>
            <span className="lunch-summary-time">{lunchTime}</span>
          </div>
        ))}
        {unassigned.length > 0 && (
          <div className="lunch-summary-card lunch-summary-unassigned">
            <span className="lunch-summary-label">Ej tilldelat</span>
            <span className="lunch-summary-count">{unassigned.length}</span>
            <span className="lunch-summary-time">Inget lunchspår ännu</span>
          </div>
        )}
      </div>

      <div className="lunch-columns">
        {TRACKS.map(({ track, title, lunchTime, passTime }) => (
          <section key={track} className="lunch-column" aria-labelledby={`lunch-heading-${track}`}>
            <h3 id={`lunch-heading-${track}`}>
              {title}{" "}
              <span className="lunch-column-count">({byTrack[track].length})</span>
            </h3>
            <p className="lunch-column-times">
              {passTime} · {lunchTime}
            </p>
            {byTrack[track].length === 0 ? (
              <p className="lunch-empty">Inga elever på detta lunchspår.</p>
            ) : (
              <ul className="lunch-student-list">
                {byTrack[track].map((s) => (
                  <li key={s.id}>
                    <button
                      type="button"
                      className="lunch-student-link"
                      onClick={() => onStudentClick(s.id)}
                    >
                      {studentName(s)}
                    </button>
                    <span className="lunch-student-meta">{s.school}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        ))}
      </div>

      {unassigned.length > 0 && (
        <section className="lunch-unassigned" aria-labelledby="lunch-heading-unassigned">
          <h3 id="lunch-heading-unassigned">
            Ej tilldelat lunchspår{" "}
            <span className="lunch-column-count">({unassigned.length})</span>
          </h3>
          <p className="lunch-column-times">
            Lunchspår sätts när eleven placeras på pass 2a eller 2b, eller vid auto-placering.
          </p>
          <ul className="lunch-student-list">
            {unassigned.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  className="lunch-student-link"
                  onClick={() => onStudentClick(s.id)}
                >
                  {studentName(s)}
                </button>
                <span className="lunch-student-meta">{s.school}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
