import { useMemo, useState } from "react";
import {
  CHOICE_WEIGHTS_CP_SAT,
  CP_SAT_CONFIG_WEIGHTS,
  HARD_CONSTRAINT_ROWS,
  OBJECTIVE_ROWS,
  estimateConstraints,
  estimateObjective,
} from "./cpSatModelEstimate";

type Props = {
  studentCount: number;
  inspiratorCount: number;
  roomCount: number;
  roomLockCount: number;
  minimizeSessionsCount: number;
  minSessionSize: number;
  sameRoomPerInspirator: boolean;
  balanceLunchTracks: boolean;
  minimizeSessionsEnabled: boolean;
};

function pct(part: number, total: number): string {
  if (total <= 0) return "0";
  return ((100 * part) / total).toFixed(0);
}

function WeightBar({
  label,
  value,
  max,
}: {
  label: string;
  value: number;
  max: number;
}) {
  const width = max > 0 ? Math.max(2, (100 * value) / max) : 0;
  return (
    <div className="cp-sat-weight-row">
      <span className="cp-sat-weight-label">{label}</span>
      <div className="cp-sat-weight-track" aria-hidden="true">
        <div className="cp-sat-weight-fill" style={{ width: `${width}%` }} />
      </div>
      <span className="cp-sat-weight-value">{value}</span>
    </div>
  );
}

function SliceList({
  items,
  total,
}: {
  items: Array<{ label: string; value: number }>;
  total: number;
}) {
  return (
    <ul className="cp-sat-slice-list">
      {items.map((d) => (
        <li key={d.label}>
          <span>{d.label}</span>
          <span className="cp-sat-slice-meta">
            {d.value.toLocaleString("sv-SE")} ({pct(d.value, total)} %)
          </span>
        </li>
      ))}
    </ul>
  );
}

export function CpSatModelView({
  studentCount,
  inspiratorCount,
  roomCount,
  roomLockCount,
  minimizeSessionsCount,
  minSessionSize,
  sameRoomPerInspirator,
  balanceLunchTracks,
  minimizeSessionsEnabled,
}: Props) {
  const [override, setOverride] = useState(false);
  const [s, setS] = useState(String(studentCount));
  const [i, setI] = useState(String(inspiratorCount));
  const [r, setR] = useState(String(roomCount));

  const S = override ? Math.max(0, Number(s) || 0) : studentCount;
  const I = override ? Math.max(0, Number(i) || 0) : inspiratorCount;
  const R = override ? Math.max(0, Number(r) || 0) : roomCount;
  const M = minimizeSessionsCount;
  const L = roomLockCount;

  const cEst = useMemo(
    () => estimateConstraints(S, I, R, L, minSessionSize, sameRoomPerInspirator),
    [S, I, R, L, minSessionSize, sameRoomPerInspirator]
  );

  const oEst = useMemo(
    () =>
      estimateObjective(
        S,
        I,
        M,
        minSessionSize,
        sameRoomPerInspirator,
        balanceLunchTracks,
        minimizeSessionsEnabled && M > 0
      ),
    [
      S,
      I,
      M,
      minSessionSize,
      sameRoomPerInspirator,
      balanceLunchTracks,
      minimizeSessionsEnabled,
    ]
  );

  const allWeights = [
    ...CHOICE_WEIGHTS_CP_SAT.map((w) => ({ label: w.label, value: w.value })),
    ...CP_SAT_CONFIG_WEIGHTS.map((w) => ({ label: w.label, value: w.value })),
  ];
  const maxWeight = Math.max(...allWeights.map((w) => w.value), 1);

  const constraintSlices = [
    { label: "Elevplacering", value: cEst.assign },
    { label: "Session", value: cEst.session },
    { label: "Kapacitet", value: cEst.capacity },
    { label: "Rum × passtyp", value: cEst.roomPass },
    { label: "Övrigt", value: cEst.exclusive + cEst.roomLocks },
  ].filter((d) => d.value > 0);

  const objectiveSlices = [
    { label: "Valrang", value: oEst.choice },
    { label: "Delat rum", value: oEst.sharing },
    { label: "Liten session", value: oEst.small },
    { label: "Lunch", value: oEst.lunch },
    { label: "Färre sessioner", value: oEst.minSess },
  ].filter((d) => d.value > 0);

  return (
    <div className="cp-sat-model">
      <header className="cp-sat-model-head">
        <div>
          <h2>CP-SAT-modell</h2>
          <p className="meta">
            Översikt av hårda regler, måltermer och vikter i{" "}
            <code>placement_cp_sat.py</code>. Uppskattade antal är ungefärliga.
          </p>
        </div>
        <div className="cp-sat-model-stats">
          <span>
            <strong>{cEst.total.toLocaleString("sv-SE")}</strong> constraints
          </span>
          <span>
            <strong>{oEst.total.toLocaleString("sv-SE")}</strong> måltermer
          </span>
        </div>
      </header>

      <div className="cp-sat-flow" aria-label="Modellflöde">
        <span>Elever &amp; rum</span>
        <span className="cp-sat-flow-arrow" aria-hidden="true">
          →
        </span>
        <span>Variabler</span>
        <span className="cp-sat-flow-arrow" aria-hidden="true">
          →
        </span>
        <span>Hårda regler</span>
        <span className="cp-sat-flow-arrow" aria-hidden="true">
          →
        </span>
        <span className="cp-sat-flow-solve">CP-SAT</span>
        <span className="cp-sat-flow-arrow" aria-hidden="true">
          →
        </span>
        <span>Maximize mål</span>
        <span className="cp-sat-flow-arrow" aria-hidden="true">
          →
        </span>
        <span>Slots</span>
      </div>

      <section className="card cp-sat-model-section">
        <h3>Vikter (maximeras)</h3>
        <div className="cp-sat-weight-chart">
          {allWeights.map((w) => (
            <WeightBar key={w.label} label={w.label} value={w.value} max={maxWeight} />
          ))}
        </div>
        <table className="data-table compact cp-sat-config-table">
          <thead>
            <tr>
              <th>Config-parameter</th>
              <th>Standard</th>
              <th>Betydelse</th>
            </tr>
          </thead>
          <tbody>
            {CP_SAT_CONFIG_WEIGHTS.map((w) => (
              <tr key={w.key}>
                <td>
                  <code>{w.key}</code>
                </td>
                <td>{w.value}</td>
                <td>{w.desc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card cp-sat-model-section">
        <h3>Uppskattning med era data</h3>
        <label className="cp-sat-override-toggle">
          <input
            type="checkbox"
            checked={override}
            onChange={(e) => {
              setOverride(e.target.checked);
              if (!e.target.checked) {
                setS(String(studentCount));
                setI(String(inspiratorCount));
                setR(String(roomCount));
              }
            }}
          />
          Justera S / I / R manuellt
        </label>
        {!override ? (
          <p className="meta cp-sat-live-meta">
            S = {S} elever (3 val) · I = {I} inspiratörer · R = {R} rum · L = {L}{" "}
            rumslås · min session = {minSessionSize}
            {minimizeSessionsEnabled && M > 0
              ? ` · färre sessioner för ${M} inspiratör(er)`
              : ""}
          </p>
        ) : (
          <div className="cp-sat-override-grid">
            <label>
              Elever (S)
              <input type="number" min={0} value={s} onChange={(e) => setS(e.target.value)} />
            </label>
            <label>
              Inspiratörer (I)
              <input type="number" min={0} value={i} onChange={(e) => setI(e.target.value)} />
            </label>
            <label>
              Rum (R)
              <input type="number" min={0} value={r} onChange={(e) => setR(e.target.value)} />
            </label>
          </div>
        )}
        <div className="cp-sat-estimate-grid">
          <div>
            <h4>Constraints (~{cEst.total.toLocaleString("sv-SE")})</h4>
            <SliceList items={constraintSlices} total={cEst.total} />
          </div>
          <div>
            <h4>Måltermer (~{oEst.total.toLocaleString("sv-SE")})</h4>
            <SliceList items={objectiveSlices} total={oEst.total} />
          </div>
        </div>
        <p className="auto-place-option-hint">
          Post-placering och reserv körs utanför CP-SAT (heuristik) och ingår inte här.
          Tidsgräns solver: 120 s · 8 söktrådar.
        </p>
      </section>

      <section className="card cp-sat-model-section">
        <h3>Hårda regler</h3>
        <table className="data-table compact">
          <thead>
            <tr>
              <th>Regel</th>
              <th>Antal (formel)</th>
              <th>CP-SAT</th>
            </tr>
          </thead>
          <tbody>
            {HARD_CONSTRAINT_ROWS.map((row) => (
              <tr key={row.name}>
                <td>{row.name}</td>
                <td>
                  <code>{row.formula}</code>
                </td>
                <td className="meta">{row.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card cp-sat-model-section">
        <h3>Målfunktion</h3>
        <table className="data-table compact">
          <thead>
            <tr>
              <th>Term</th>
              <th>Antal (formel)</th>
              <th>Vikt</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {OBJECTIVE_ROWS.map((row) => (
              <tr key={row.name}>
                <td>{row.name}</td>
                <td>
                  <code>{row.formula}</code>
                </td>
                <td>{row.weight}</td>
                <td>{row.optional ? "valfri" : "alltid"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
