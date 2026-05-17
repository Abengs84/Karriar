import { useState } from "react";
import { api, type AutoSolveResult } from "./api";
import type { ToastType } from "./Toast";

const CHOICE_LABELS: Record<string, string> = {
  choice1: "Val 1",
  choice2: "Val 2",
  choice3: "Val 3",
  reserve: "Reserv",
};

type Props = {
  studentCount: number;
  roomCount: number;
  onDone: () => Promise<void>;
  showMsg: (type: ToastType, text: string) => void;
};

export function AutoPlaceTab({ studentCount, roomCount, onDone, showMsg }: Props) {
  const [mode, setMode] = useState<"fill" | "replace">("fill");
  const [preview, setPreview] = useState<AutoSolveResult | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (dryRun: boolean) => {
    setBusy(true);
    try {
      const result = await api.placements.autoSolve({ mode, dry_run: dryRun });
      if (dryRun) {
        setPreview(result);
        showMsg("success", result.summary);
      } else {
        setPreview(result);
        await onDone();
        showMsg("success", `Klart. ${result.summary}`);
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
        vägs tyngst, därefter val 2 och val 3. Reserv placeras inte automatiskt – den är valfri.
        Varje elev kan ha högst tre pass (pass 1, pass 2 och pass 3) och högst en gång per
        inspiratör. Pass 2 fördelas ungefär hälften på 2a och hälften på 2b (olika lunch).
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
          <ul className="auto-place-stats">
            <li>
              <strong>{preview.placed_new}</strong> nya pass
            </li>
            <li>
              <strong>{preview.slots_created}</strong> nya sessioner (rum + pass)
            </li>
            <li>
              <strong>{preview.unplaced_count}</strong> val 1–3 utan pass
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
              <h4>Val 1–3 som fortfarande saknar pass (max 80)</h4>
              <div className="auto-place-unplaced-scroll">
                <table className="data-table compact">
                  <thead>
                    <tr>
                      <th>Elev-id</th>
                      <th>Inspiratör</th>
                      <th>Val</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.unplaced_sample.map((row) => (
                      <tr key={`${row.student_id}-${row.inspiration}`}>
                        <td>{row.student_id}</td>
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
