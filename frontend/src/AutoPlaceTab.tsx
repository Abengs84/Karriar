import { useState } from "react";
import { api, type AutoSolveResult, type Room, type SessionSlot, type Student } from "./api";
import { DemandHeatmap } from "./DemandHeatmap";
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

function formatUnplacedStatus(
  unplaced_count: number,
  unplaced_student_count: number
): string {
  const parts: string[] = [];
  if (unplaced_count === 0) {
    parts.push("Alla val 1–3 har matchande inspiratör.");
  } else if (unplaced_count === 1) {
    parts.push("1 val 1–3 utan matchande pass.");
  } else {
    parts.push(`${unplaced_count} val 1–3 utan matchande pass.`);
  }
  if (unplaced_student_count === 1) {
    parts.push(
      "1 elev saknar fortfarande pass enligt schemat (samma som oplacerade grupper)."
    );
  } else if (unplaced_student_count > 1) {
    parts.push(
      `${unplaced_student_count} elever saknar fortfarande pass enligt schemat (samma som oplacerade grupper).`
    );
  }
  return parts.join(" ");
}

function formatAutoPlaceToast(result: AutoSolveResult, phase: "preview" | "apply"): string {
  const { placed_new, slots_created, unplaced_count, unplaced_student_count } = result;
  const sessions = formatSessionCount(slots_created);
  const status = formatUnplacedStatus(
    unplaced_count,
    unplaced_student_count ?? result.missing_pass_count ?? 0
  );

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
  students: Student[];
  slots: SessionSlot[];
  rooms: Room[];
  minStudentsThreshold: number;
  onMinStudentsThresholdChange: (value: number) => void;
  onDone: () => Promise<void>;
  showMsg: (type: ToastType, text: string) => void;
};

export function AutoPlaceTab({
  studentCount,
  roomCount,
  students,
  slots,
  rooms,
  minStudentsThreshold,
  onMinStudentsThresholdChange,
  onDone,
  showMsg,
}: Props) {
  const [mode, setMode] = useState<"fill" | "replace">("fill");
  const [tryReserveForUnplaced, setTryReserveForUnplaced] = useState(false);
  const [balanceLunchTracks, setBalanceLunchTracks] = useState(true);
  const [consolidateSmallGroups, setConsolidateSmallGroups] = useState(true);
  const [sameRoomPerInspirator, setSameRoomPerInspirator] = useState(false);
  const [prioritizeHighDemand, setPrioritizeHighDemand] = useState(true);
  const [preview, setPreview] = useState<AutoSolveResult | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (dryRun: boolean) => {
    setBusy(true);
    try {
      const result = await api.placements.autoSolve({
        mode,
        dry_run: dryRun,
        min_students_threshold: minStudentsThreshold,
        try_reserve_for_unplaced: tryReserveForUnplaced,
        balance_lunch_tracks: balanceLunchTracks,
        consolidate_small_groups: consolidateSmallGroups,
        same_room_per_inspirator: sameRoomPerInspirator,
        prioritize_high_demand: prioritizeHighDemand,
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
    <div className="auto-place-page">
      <section className="card auto-place-settings">
        <div className="auto-place-settings-head">
          <div>
            <h2>Automatisk placering</h2>
            <p className="meta auto-place-meta">
              {studentCount} elever · {roomCount} rum
            </p>
          </div>
          <div className="auto-place-actions">
            <button
              type="button"
              className="primary"
              disabled={busy || roomCount === 0}
              onClick={() => void run(true)}
            >
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
                void run(false);
              }}
            >
              Verkställ placering
            </button>
          </div>
        </div>

        <details className="auto-place-details">
          <summary>Hur fungerar det?</summary>
          <p>
            Systemet placerar elever på inspiratörspass med så få krockar som möjligt. Val 1 vägs
            tyngst. Varje elev har högst tre tidspass; pass 2 är antingen 2a eller 2b. Börja med
            förhandsgranskning innan du verkställer.
          </p>
        </details>

        <div className="auto-place-settings-grid">
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
            checked={sameRoomPerInspirator}
            onChange={(e) => setSameRoomPerInspirator(e.target.checked)}
            disabled={busy}
          />
          Ett rum per inspiratör (alla pass i samma rum)
        </label>
        <p className="auto-place-option-hint">
          Varje inspiratör får ett eget rum för pass 1, 2 och 3. Rum tilldelas efter antal
          val (störst efterfrågan → största sal). Befintliga sessioner flyttas till rätt rum
          vid körning. Utan kryss kan flera inspiratörer dela rum på olika tider.
        </p>
        <label>
          <input
            type="checkbox"
            checked={prioritizeHighDemand}
            onChange={(e) => setPrioritizeHighDemand(e.target.checked)}
            disabled={busy}
          />
          Prioritera stora grupper (efterfrågan)
        </label>
        <p className="auto-place-option-hint">
          Med få rum: de mest valda inspiratörerna får sal först. Låg efterfrågan kan
          flyttas bort från stora sal. Kombinera med tröskel för att dölja små inspiratörer.
        </p>
        <label>
          <input
            type="checkbox"
            checked={consolidateSmallGroups}
            onChange={(e) => setConsolidateSmallGroups(e.target.checked)}
            disabled={busy}
          />
          Samla små grupper på ett pass per inspiratör
        </label>
        <p className="auto-place-option-hint">
          Fyller befintliga sessioner först och samlar små grupper till ett pass efter
          placering (t.ex. 8 elever på tre tidspass → en gemensam träff när det finns plats).
        </p>
        <label>
          <input
            type="checkbox"
            checked={balanceLunchTracks}
            onChange={(e) => setBalanceLunchTracks(e.target.checked)}
            disabled={busy}
          />
          Balansera lunchspår (2a / 2b)
        </label>
        <p className="auto-place-option-hint">
          Fördelar inspiratörer utan låst pass 2 mellan lunch 2a och 2b så att ungefär
          hälften av eleverna hamnar på varje spår. Inspiratörer som redan ligger på 2a
          eller 2b behålls.
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
          Efter huvudloopen: elever med kvarvarande val 1–3 försöker placeras på reserv.
          Räknar även reservval vid rumstorlek (t.ex. många på KRIMINOLOG → större sal).
          Omflyttning till annan tid om ett pass är fullt.
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
        </div>

      <p className="auto-place-hint">
        Börja alltid med <strong>Förhandsgranska</strong>. Jämför alternativ med{" "}
        <strong>Omplacera allt</strong> – i läget «Fyll tomma» ändras sällan poäng om schemat
        redan är fullt.
      </p>

      {preview && (
        <div className="auto-place-result">
          <h3>{preview.dry_run ? "Förhandsgranskning" : "Resultat"}</h3>
          {preview.dry_run && (
            <p className="pool-hint" style={{ marginTop: 0 }}>
              Siffrorna nedan visar hur det blir <strong>efter</strong> Verkställ placering (ingenting
              är sparat ännu).
            </p>
          )}
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
              <strong>{preview.unplaced_count}</strong> val 1–3 utan matchande pass
            </li>
            <li>
              <strong>
                {preview.unplaced_student_count ?? preview.missing_pass_count ?? 0}
              </strong>{" "}
              elever i oplacerade grupper (saknar pass enligt schemat)
            </li>
            <li>
              Lunch 2a / 2b: <strong>{preview.lunch_2a ?? 0}</strong> /{" "}
              <strong>{preview.lunch_2b ?? 0}</strong> elever
            </li>
            {(preview.rooms_relocated ?? 0) > 0 && (
              <li>
                <strong>{preview.rooms_relocated}</strong> sessioner flyttade till annat rum
              </li>
            )}
            {(preview.reserve_placed_count ?? 0) > 0 && (
              <li>
                <strong>{preview.reserve_placed_count}</strong> elever fick reserv på ledigt pass
              </li>
            )}
            <li className="auto-place-score-note">
              Poäng <strong>{preview.score}</strong> – summerar vikt för uppfyllda val (val 1 = 1000,
              val 2 = 500, val 3 = 200). Blir ofta lika när alla val 1–3 är placerade; titta på
              sessioner, lunch och sammanfattningen ovan för skillnader mellan kryssrutor.
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
              <h4>Val 1–3 utan matchande inspiratör (max 80)</h4>
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

      <section className="card auto-place-heatmap-panel">
        <DemandHeatmap
          students={students}
          slots={slots}
          rooms={rooms}
          minStudentsThreshold={minStudentsThreshold}
          previewSlots={preview?.dry_run ? preview.preview_slots ?? null : null}
          previewInspiratorStatus={
            preview?.dry_run ? preview.preview_inspirator_status ?? null : null
          }
        />
      </section>
    </div>
  );
}
