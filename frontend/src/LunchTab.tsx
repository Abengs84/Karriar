import { useMemo, useState } from "react";
import { api, LunchRebalanceResult, Student } from "./api";

type Props = {
  students: Student[];
  onStudentClick: (studentId: number) => void;
  onRefresh: () => Promise<void>;
  showMsg: (type: "success" | "error", text: string) => void;
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

function formatMove(m: LunchRebalanceResult["moves"][0]): string {
  if (m.kind === "swap" && m.inspiration_b) {
    return `${m.room_name}: byt lunchspår mellan «${m.inspiration}» (${m.student_count} el.) och «${m.inspiration_b}» (${m.student_count_b} el.)`;
  }
  return `${m.room_name}: «${m.inspiration}» flyttas från lunch ${m.from_track} → ${m.to_track} (${m.student_count} el.)`;
}

export function LunchTab({ students, onStudentClick, onRefresh, showMsg }: Props) {
  const [preview, setPreview] = useState<LunchRebalanceResult | null>(null);
  const [busy, setBusy] = useState(false);

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

  const suggestRebalance = async () => {
    setBusy(true);
    try {
      const result = await api.lunch.rebalance(true);
      setPreview(result);
      showMsg(
        result.moves.length > 0 ? "success" : "error",
        result.summary
      );
    } catch (err) {
      showMsg("error", err instanceof Error ? err.message : "Kunde inte beräkna förslag");
      setPreview(null);
    } finally {
      setBusy(false);
    }
  };

  const applyRebalance = async () => {
    if (!preview?.moves.length) return;
    setBusy(true);
    try {
      const result = await api.lunch.rebalance(false);
      setPreview(result);
      await onRefresh();
      showMsg("success", result.summary);
    } catch (err) {
      showMsg("error", err instanceof Error ? err.message : "Kunde inte verkställa");
    } finally {
      setBusy(false);
    }
  };

  const clearPreview = () => setPreview(null);

  return (
    <div className="card lunch-tab">
      <h2>Lunch</h2>
      <p className="lunch-tab-lead">
        Översikt över lunchspår enligt placering på pass 2a eller 2b. Totalt{" "}
        <strong>{totalAssigned}</strong> elever med tilldelat lunchspår av{" "}
        {students.length}.
      </p>

      <div className="lunch-rebalance-actions">
        <button
          type="button"
          className="primary"
          disabled={busy}
          onClick={() => void suggestRebalance()}
        >
          {busy && !preview ? "Beräknar…" : "Föreslå omfördelning"}
        </button>
        {preview && preview.moves.length > 0 && (
          <>
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => void applyRebalance()}
            >
              {busy ? "Verkställer…" : "Verkställ omfördelning"}
            </button>
            <button type="button" disabled={busy} onClick={clearPreview}>
              Avbryt
            </button>
          </>
        )}
        {preview && preview.moves.length === 0 && (
          <button type="button" disabled={busy} onClick={clearPreview}>
            Stäng
          </button>
        )}
      </div>
      <p className="lunch-rebalance-hint">
        Flyttar hela pass-2-sessioner mellan 2a och 2b (samma rum och inspiratör) så att
        lunchspåren blir jämnare. Påverkar inte pass 1 eller pass 3.
      </p>

      {preview && (
        <section className="lunch-rebalance-preview" aria-live="polite">
          <h3>Förslag på omfördelning</h3>
          <p className="lunch-rebalance-summary">{preview.summary}</p>
          <div className="lunch-rebalance-counts">
            <span>
              Spår 2a: {preview.lunch_2a_before} → <strong>{preview.lunch_2a_after}</strong>
            </span>
            <span>
              Spår 2b: {preview.lunch_2b_before} → <strong>{preview.lunch_2b_after}</strong>
            </span>
          </div>
          {preview.moves.length > 0 ? (
            <ol className="lunch-rebalance-moves">
              {preview.moves.map((m, i) => (
                <li key={`${m.kind}-${m.session_slot_id}-${m.session_slot_id_b ?? i}`}>
                  {formatMove(m)}
                </li>
              ))}
            </ol>
          ) : (
            preview.blocked_reason && (
              <p className="lunch-rebalance-blocked">{preview.blocked_reason}</p>
            )
          )}
        </section>
      )}

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
