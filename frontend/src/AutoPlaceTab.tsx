import { useState } from "react";
import { api, type AutoSolveResult } from "./api";
import type { ToastType } from "./Toast";

const CHOICE_LABELS: Record<string, string> = {
  choice1: "Val 1",
  choice2: "Val 2",
  choice3: "Val 3",
  reserve: "Reserv",
};

function formatSessionCount(n: number): string {
  if (n === 0) return "inga nya sessioner";
  if (n === 1) return "1 ny session";
  return `${n} nya sessioner`;
}

function formatUnplacedStatus(unplaced_count: number): string {
  if (unplaced_count === 0) {
    return "Ingen elev saknar ledigt tidspass för sina val 1–3.";
  }
  if (unplaced_count === 1) {
    return "1 val 1–3 saknar fortfarande tidspass.";
  }
  return `${unplaced_count} val 1–3 saknar fortfarande tidspass.`;
}

function formatAutoPlaceToast(result: AutoSolveResult, phase: "preview" | "apply"): string {
  const { placed_new, slots_created, unplaced_count } = result;
  const sessions = formatSessionCount(slots_created);
  const status = formatUnplacedStatus(unplaced_count);

  if (phase === "preview") {
    const vals =
      placed_new === 0
        ? "Inga nya val att placera"
        : placed_new === 1
          ? "1 val skulle placeras"
          : `${placed_new} val skulle placeras`;
    return (
      `Förhandsgranskning klar: ${vals}, ${sessions}. ` +
      `${status} Inget är sparat – klicka Verkställ placering om du vill spara.`
    );
  }

  const vals =
    placed_new === 0
      ? "Inga nya val placerade"
      : placed_new === 1
        ? "1 val placerades"
        : `${placed_new} val placerades`;
  return `Placering sparad: ${vals}, ${sessions}. ${status}`;
}

type Props = {
  studentCount: number;
  roomCount: number;
  minStudentsThreshold: number;
  onMinStudentsThresholdChange: (value: number) => void;
  onDone: () => Promise<void>;
  showMsg: (type: ToastType, text: string) => void;
};

export function AutoPlaceTab({
  studentCount,
  roomCount,
  minStudentsThreshold,
  onMinStudentsThresholdChange,
  onDone,
  showMsg,
}: Props) {
  const [mode, setMode] = useState<"fill" | "replace">("fill");
  const [minimizeSessionsPerInspirator, setMinimizeSessionsPerInspirator] = useState(false);
  const [tryReserveForUnplaced, setTryReserveForUnplaced] = useState(false);
  const [preview, setPreview] = useState<AutoSolveResult | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (dryRun: boolean) => {
    setBusy(true);
    try {
      const result = await api.placements.autoSolve({
        mode,
        dry_run: dryRun,
        minimize_sessions_per_inspirator: minimizeSessionsPerInspirator,
        min_students_threshold: minStudentsThreshold,
        try_reserve_for_unplaced: tryReserveForUnplaced,
      });
      if (dryRun) {
        setPreview(result);
        showMsg("success", formatAutoPlaceToast(result, "preview"));
      } else {
        setPreview(result);
        await onDone();
        showMsg("success", formatAutoPlaceToast(result, "apply"));
      }
    } catch (e) {
      showMsg("error", e instanceof Error ? e.message : "Automatisk placering misslyckades");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card auto-place-panel">
      <h2>Automatisk placering</h2>
      <p className="auto-place-intro">
        Systemet försöker placera elever på inspiratörspass med så få krockar som möjligt. Val 1
        vägs tyngst, därefter val 2 och val 3. Reserv kan försökas automatiskt via alternativet nedan.
        Varje elev och varje inspiratör kan ha högst tre tidspass (pass 1, pass 2 och pass 3).
        Varje inspiratör ligger på antingen lunch 2a eller 2b. Elever fördelas ungefär
        hälften på vardera lunchspår.
      </p>

      <p className="meta">
        {studentCount} elever · {roomCount} rum
      </p>

      <fieldset className="auto-place-mode">
        <legend>Läge</legend>
        <label>
          <input
            type="radio"
            name="auto-mode"
            checked={mode === "fill"}
            onChange={() => setMode("fill")}
            disabled={busy}
          />
          Fyll tomma platser (behåll befintliga placeringar)
        </label>
        <label>
          <input
            type="radio"
            name="auto-mode"
            checked={mode === "replace"}
            onChange={() => setMode("replace")}
            disabled={busy}
          />
          Omplacera allt (tar bort alla nuvarande placeringar)
        </label>
      </fieldset>

      <fieldset className="auto-place-options">
        <legend>Alternativ</legend>
        <label>
          <input
            type="checkbox"
            checked={minimizeSessionsPerInspirator}
            onChange={(e) => setMinimizeSessionsPerInspirator(e.target.checked)}
            disabled={busy}
          />
          Prioritera få sessioner per inspiratör (samlar grupper i samma rum/pass)
        </label>
        <p className="auto-place-option-hint">
          När kryssat fylls befintliga sessioner först och större rum väljs vid nya grupper, så
          färre parallella träffar skapas för samma inspiratör.
        </p>
        <label>
          <input
            type="checkbox"
            checked={tryReserveForUnplaced}
            onChange={(e) => setTryReserveForUnplaced(e.target.checked)}
            disabled={busy}
          />
          Försök reserv för elever som saknar pass
        </label>
        <p className="auto-place-option-hint">
          Efter huvudloopen: elever med kvarvarande val 1–3 försöker placeras på reserv. Om
          reserv inte får plats på ett ledigt pass kan systemet flytta ett befintligt pass till
          en annan tid (samma inspiratör) och lägga reserv på det frigjorda passet.
        </p>
        <label className="auto-place-threshold">
          <span>Tröskel: min antal elever per inspiratör (val 1–3)</span>
          <input
            type="number"
            min={0}
            max={500}
            value={minStudentsThreshold}
            onChange={(e) =>
              onMinStudentsThresholdChange(parseInt(e.target.value, 10) || 0)
            }
            disabled={busy}
          />
        </label>
        <p className="auto-place-option-hint">
          <strong>0 = av.</strong> Inspiratörer med högst så många elever döljs i Placering och
          berörda elever styrs mot reserv vid auto-placering (en reserv per elev).
        </p>
      </fieldset>

      <div className="auto-place-actions">
        <button type="button" className="primary" disabled={busy || roomCount === 0} onClick={() => run(true)}>
          Förhandsgranska
        </button>
        <button
          type="button"
          className="primary"
          disabled={busy || roomCount === 0}
          onClick={() => {
            if (
              mode === "replace" &&
              !window.confirm(
                "Alla befintliga placeringar tas bort och ersätts med systemets förslag. Fortsätta?"
              )
            ) {
              return;
            }
            run(false);
          }}
        >
          Verkställ placering
        </button>
      </div>

      <p className="auto-place-hint">
        Börja alltid med <strong>Förhandsgranska</strong>. Läs mer under{" "}
        <code>docs/AUTO_PLACEMENT.md</code> i projektet.
      </p>

      {preview && (
        <div className="auto-place-result">
          <h3>{preview.dry_run ? "Förhandsgranskning" : "Resultat"}</h3>
          <p>{preview.summary}</p>
          {preview.suppressed_inspirators.length > 0 && (
            <p className="auto-place-suppressed">
              <strong>{preview.suppressed_inspirators.length}</strong> inspiratör(er) under
              tröskel (dolda i Placering, elever mot reserv):{" "}
              {preview.suppressed_inspirators.join("; ")}
            </p>
          )}
          <ul className="auto-place-stats">
            <li>
              <strong>{preview.placed_new}</strong>{" "}
              {preview.placed_new === 1 ? "nytt val" : "nya val"}
            </li>
            <li>
              <strong>{preview.slots_created}</strong> nya sessioner (rum + pass)
            </li>
            <li>
              <strong>{preview.unplaced_count}</strong> val 1–3 utan tidspass
            </li>
            <li>
              Poäng (högre = fler prioriterade val uppfyllda): <strong>{preview.score}</strong>
            </li>
          </ul>
          <h4>Uppfyllda val per typ</h4>
          <table className="data-table compact">
            <thead>
              <tr>
                <th>Val</th>
                <th>Antal pass</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(preview.by_choice_field).map(([field, count]) => (
                <tr key={field}>
                  <td>{CHOICE_LABELS[field] ?? field}</td>
                  <td>{count}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {preview.unplaced_sample.length > 0 && (
            <>
              <h4>Val 1–3 som saknar ledigt tidspass (max 80)</h4>
              <div className="auto-place-unplaced-scroll">
                <table className="data-table compact">
                  <thead>
                    <tr>
                      <th>Elev</th>
                      <th>Inspiratör</th>
                      <th>Val</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.unplaced_sample.map((row) => (
                      <tr key={`${row.student_id}-${row.inspiration}`}>
                        <td>{row.student_name}</td>
                        <td>{row.inspiration}</td>
                        <td>{CHOICE_LABELS[row.choice_field] ?? row.choice_field}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
