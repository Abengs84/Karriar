import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { fetchAuthStatus, logout } from "./auth";
import {
  api,
  AuthError,
  AutoSolveResult,
  InspiratorStat,
  RetentionStatus,
  Room,
  SessionSlot,
  Student,
  setUnauthorizedHandler,
} from "./api";
import { RetentionCountdown } from "./RetentionCountdown";
import { LoginScreen } from "./LoginScreen";
import { PrivacyNotice } from "./PrivacyNotice";
import {
  countPlacedForInspirator,
  countStudentsWithAllChoicesPlaced,
  countStudentsWithUnplacedChoice,
  countUnplacedForInspirator,
  formatChoiceRanks,
  isPlacedWithInspirator,
  schedulePassCountByInspirator,
  studentHasFullSchedule,
  studentChoiceRanksForInspirator,
  studentsWhoChoseInspirator,
  totalRequiredChoiceSlots,
} from "./placementUtils";
import { AutoPlaceTab } from "./AutoPlaceTab";
import { LunchTab } from "./LunchTab";
import { PlacementBoard } from "./PlacementBoard";
import { SchemaTab } from "./SchemaTab";
import {
  readMinStudentsThreshold,
  writeMinStudentsThreshold,
} from "./placementThreshold";
import { StudentPlacementTab } from "./StudentPlacementTab";
import { useToast } from "./Toast";

type Tab =
  | "rum"
  | "import"
  | "statistik"
  | "auto"
  | "placering"
  | "schema"
  | "lunch"
  | "elever"
  | "pdf"
  | "integritet";

export default function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [tab, setTab] = useState<Tab>("rum");
  const [rooms, setRooms] = useState<Room[]>([]);
  const [students, setStudents] = useState<Student[]>([]);
  const [slots, setSlots] = useState<SessionSlot[]>([]);
  const [stats, setStats] = useState<InspiratorStat[]>([]);
  const [schools, setSchools] = useState<{ school: string; count: number }[]>([]);
  const [loading, setLoading] = useState(false);
  const [minStudentsThreshold, setMinStudentsThreshold] = useState(readMinStudentsThreshold);
  const [highlightStudentId, setHighlightStudentId] = useState<number | null>(null);
  const [retention, setRetention] = useState<RetentionStatus | null>(null);
  const [autoPlacePreview, setAutoPlacePreview] = useState<AutoSolveResult | null>(null);
  const showMsg = useToast();

  const refreshRetention = useCallback(async () => {
    try {
      const r = await api.retention.status();
      setRetention(r);
    } catch (e) {
      if (e instanceof AuthError) return;
    }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setAuthenticated(false));
    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    fetchAuthStatus()
      .then((s) => setAuthenticated(s.authenticated))
      .catch(() => setAuthenticated(false));
  }, []);

  const goToStudent = (studentId: number) => {
    setHighlightStudentId(studentId);
    setTab("elever");
  };

  const updateMinStudentsThreshold = (value: number) => {
    const n = Math.max(0, Math.floor(value));
    setMinStudentsThreshold(n);
    writeMinStudentsThreshold(n);
  };

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [r, s, sl, st, sc, ret] = await Promise.all([
        api.rooms.list(),
        api.students.list(),
        api.sessionSlots.list(),
        api.stats(),
        api.schools(),
        api.retention.status(),
      ]);
      setRooms(r);
      setStudents(s);
      setSlots(sl);
      setStats(st);
      setSchools(sc);
      setRetention(ret);
    } catch (e) {
      if (e instanceof AuthError) return;
      showMsg("error", e instanceof Error ? e.message : "Kunde inte hämta data");
    } finally {
      setLoading(false);
    }
  }, [showMsg]);

  /** Uppdaterar elever + pass utan "Laddar…" – används efter drag-drop. */
  const refreshPlacement = useCallback(async () => {
    try {
      const [s, sl, sc, st] = await Promise.all([
        api.students.list(),
        api.sessionSlots.list(),
        api.schools(),
        api.stats(),
      ]);
      setStudents(s);
      setSlots(sl);
      setSchools(sc);
      setStats(st);
      return { students: s, slots: sl };
    } catch (e) {
      showMsg("error", e instanceof Error ? e.message : "Kunde inte uppdatera placering");
      throw e;
    }
  }, [showMsg]);

  useEffect(() => {
    if (authenticated) refresh();
  }, [refresh, authenticated]);

  useEffect(() => {
    if (!authenticated) return;
    const id = window.setInterval(() => refreshRetention(), 60_000);
    return () => window.clearInterval(id);
  }, [authenticated, refreshRetention]);

  const onRetentionExpired = useCallback(async () => {
    showMsg(
      "success",
      `Elevdata har raderats automatiskt (${retention?.retention_hours ?? 3} timmar efter import).`
    );
    await refresh();
  }, [refresh, showMsg, retention?.retention_hours]);

  const clearDatabase = async () => {
    if (
      !confirm(
        "Töm alla elever, placeringar och schemaceller? Rum behålls. Detta går inte att ångra."
      )
    ) {
      return;
    }
    try {
      const r = await api.students.clearAll();
      showMsg(
        "success",
        `Tog bort ${r.removed_students} elever, ${r.removed_placements} placeringar och ${r.removed_session_slots} schemaceller.`
      );
      await refresh();
    } catch (e) {
      showMsg("error", e instanceof Error ? e.message : "Kunde inte tömma databasen");
    }
  };

  if (authenticated === null) {
    return (
      <div className="login-page">
        <p className="login-lead">Kontrollerar inloggning…</p>
      </div>
    );
  }

  if (!authenticated) {
    return <LoginScreen onLoggedIn={() => setAuthenticated(true)} />;
  }

  const handleLogout = async () => {
    await logout();
    setAuthenticated(false);
  };

  return (
    <>
      <header className="app-header">
        <div className="app-header-left">
          <h1>Karriär – Placering</h1>
          <span className="app-header-meta">
            {students.length} elever · {rooms.length} rum
            <RetentionCountdown retention={retention} onExpired={onRetentionExpired} />
          </span>
        </div>
        <div className="app-header-actions">
          <button
            type="button"
            className="app-header-clear"
            onClick={clearDatabase}
            disabled={loading || (students.length === 0 && slots.length === 0)}
            title="Ta bort alla elever, placeringar och schemaceller (GDPR: rätt till radering)"
          >
            Töm elever/databas
          </button>
          <button type="button" className="app-header-logout" onClick={handleLogout}>
            Logga ut
          </button>
        </div>
      </header>

      <nav className="tabs">
        {(
          [
            ["rum", "Rum"],
            ["import", "Import"],
            ["statistik", "Inspiratör"],
            ["auto", "Auto-placering"],
            ["placering", "Placering"],
            ["schema", "Schema"],
            ["lunch", "Lunch"],
            ["elever", "Elever"],
            ["pdf", "PDF"],
            ["integritet", "Integritet"],
          ] as const
        ).map(([id, label]) => (
          <button key={id} className={`tab ${tab === id ? "active" : ""}`} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </nav>

      <main className="main">
        {loading && <p style={{ color: "var(--muted)" }}>Laddar…</p>}

        {tab === "rum" && (
          <RoomsTab rooms={rooms} onRefresh={refresh} showMsg={showMsg} />
        )}
        {tab === "import" && (
          <ImportTab
            onDone={refresh}
            onImportComplete={setRetention}
            showMsg={showMsg}
          />
        )}
        {tab === "statistik" && (
          <StatsTab
            stats={stats}
            students={students}
            slots={slots}
            onStudentClick={goToStudent}
          />
        )}
        {tab === "auto" && (
          <AutoPlaceTab
            studentCount={students.length}
            roomCount={rooms.length}
            students={students}
            slots={slots}
            rooms={rooms}
            minStudentsThreshold={minStudentsThreshold}
            onMinStudentsThresholdChange={updateMinStudentsThreshold}
            onPreview={setAutoPlacePreview}
            onDone={async () => {
              setAutoPlacePreview(null);
              await refresh();
            }}
            showMsg={showMsg}
          />
        )}
        {tab === "placering" && (
          <PlacementBoard
            rooms={rooms}
            students={students}
            slots={slots}
            minStudentsThreshold={minStudentsThreshold}
            autoPlacePreview={autoPlacePreview}
            onRefresh={refreshPlacement}
            showMsg={showMsg}
          />
        )}
        {tab === "schema" && <SchemaTab rooms={rooms} slots={slots} students={students} />}
        {tab === "lunch" && (
          <LunchTab
            students={students}
            onStudentClick={goToStudent}
            onRefresh={refreshPlacement}
            showMsg={showMsg}
          />
        )}
        {tab === "elever" && (
          <StudentPlacementTab
            students={students}
            slots={slots}
            schoolOptions={schools.map((s) => s.school)}
            highlightStudentId={highlightStudentId}
            onHighlightClear={() => setHighlightStudentId(null)}
            onRefresh={refreshPlacement}
            showMsg={showMsg}
          />
        )}
        {tab === "pdf" && <PdfTab schools={schools} />}
        {tab === "integritet" && <IntegritetTab studentCount={students.length} />}
      </main>
    </>
  );
}

function RoomsTab({
  rooms,
  onRefresh,
  showMsg,
}: {
  rooms: Room[];
  onRefresh: () => Promise<void>;
  showMsg: (t: "error" | "success", m: string) => void;
}) {
  const [name, setName] = useState("");
  const [cap, setCap] = useState(30);

  const add = async () => {
    if (!name.trim()) return;
    try {
      await api.rooms.create(name.trim(), cap);
      setName("");
      showMsg("success", "Rum skapat");
      await onRefresh();
    } catch (e) {
      showMsg("error", e instanceof Error ? e.message : "Fel");
    }
  };

  const remove = async (id: number) => {
    try {
      await api.rooms.delete(id);
      showMsg("success", "Rum borttaget");
      await onRefresh();
    } catch (e) {
      showMsg("error", e instanceof Error ? e.message : "Kunde inte ta bort");
    }
  };

  const updateCapacity = async (id: number, capacity: number) => {
    if (!Number.isFinite(capacity) || capacity < 1) return;
    try {
      await api.rooms.update(id, { capacity });
      await onRefresh();
    } catch (e) {
      showMsg("error", e instanceof Error ? e.message : "Kunde inte uppdatera kapacitet");
    }
  };

  return (
    <div className="card">
      <h2>Rum</h2>
      <div className="form-row">
        <label>
          Namn (t.ex. F606)
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="F606" />
        </label>
        <label>
          Kapacitet
          <input
            type="number"
            min={1}
            value={cap}
            onChange={(e) => setCap(Number(e.target.value))}
          />
        </label>
        <button className="primary" onClick={add}>
          Lägg till rum
        </button>
      </div>
      <table>
        <thead>
          <tr>
            <th>Namn</th>
            <th>Kapacitet</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rooms.map((r) => (
            <tr key={r.id}>
              <td>{r.name}</td>
              <td>
                <input
                  type="number"
                  min={1}
                  className="capacity-input"
                  defaultValue={r.capacity}
                  key={`${r.id}-${r.capacity}`}
                  onBlur={(e) => {
                    const next = Number(e.target.value);
                    if (next !== r.capacity) void updateCapacity(r.id, next);
                  }}
                />
              </td>
              <td>
                <button className="danger" onClick={() => remove(r.id)}>
                  Ta bort
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ImportTab({
  onDone,
  onImportComplete,
  showMsg,
}: {
  onDone: () => Promise<void>;
  onImportComplete: (r: RetentionStatus) => void;
  showMsg: (t: "error" | "success", m: string) => void;
}) {
  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const r = await api.import(file);
      onImportComplete(r.retention);
      showMsg(
        "success",
        `Importerade ${r.imported} nya elever. Hoppade över ${r.skipped_duplicates} dubbletter. Totalt: ${r.total_students}. Elevdata raderas om ${r.retention.retention_hours} timmar.`
      );
      await onDone();
    } catch (err) {
      showMsg("error", err instanceof Error ? err.message : "Import misslyckades");
    }
    e.target.value = "";
  };

  return (
    <div className="card">
      <h2>Importera Excel</h2>
      <p style={{ color: "var(--muted)", fontSize: "0.9rem" }}>
        Kolumner: A = timestamp, B = efternamn, C = förnamn, D = skola, E–G = INSPIRATIONSTRÄFF 1–3, H = INSPIRATIONSTRÄFF - RESERV.
        Format: &quot;Ekonom – Cecilia Ruotsala&quot;. Vid dubbletter i filen (samma namn + skola) används raden med senaste timestamp.
      </p>
      <input type="file" accept=".xlsx,.xls" onChange={handleFile} />
    </div>
  );
}

function StatsTab({
  stats,
  students,
  slots,
  onStudentClick,
}: {
  stats: InspiratorStat[];
  students: Student[];
  slots: SessionSlot[];
  onStudentClick: (studentId: number) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  const toggleExpanded = (inspiration: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(inspiration)) next.delete(inspiration);
      else next.add(inspiration);
      return next;
    });
  };

  const passCountByInspirator = useMemo(
    () => schedulePassCountByInspirator(slots),
    [slots]
  );
  const totalPasses = useMemo(
    () =>
      stats.reduce(
        (sum, s) => sum + (passCountByInspirator.get(s.inspiration) ?? 0),
        0
      ),
    [stats, passCountByInspirator]
  );
  const totalChoiceSlots = totalRequiredChoiceSlots(students);
  const totalPlacedStudents = countStudentsWithAllChoicesPlaced(students);
  const totalUnplacedStudents = countStudentsWithUnplacedChoice(students);

  return (
    <div className="card">
      <h2>Val per inspiratör</h2>
      <p style={{ fontSize: "0.9rem", color: "var(--muted)", marginTop: 0 }}>
        Antal unika elever som valt inspiratören i val 1–3 (kolumn E, F, G). Reservval
        (H) räknas inte. Antal pass = tidspass 1–3 i Placering (max 3 per inspiratör;
        pass 2 = antingen 2a eller 2b). Placerade/Oplacerade per rad följer samma regler
        som listan under raden (elever med tre pass via andra val räknas inte som
        oplacerade). Summan under Oplacerade visar unika elever som saknar minst ett
        val (samma som Elever-fliken), inte summan av kolumnen – en elev kan stå på
        flera rader. Klicka på triangeln för att se eleverna; klicka på ett namn för
        att gå till Elever-fliken.
      </p>
      <table className="stats-table">
        <thead>
          <tr>
            <th className="stats-expand-col" aria-label="Visa elever" />
            <th>Inspiratör</th>
            <th>Antal elever</th>
            <th>Antal pass</th>
            <th>Placerade</th>
            <th>Oplacerade</th>
          </tr>
        </thead>
        <tbody>
          {stats.map((s) => {
            const isOpen = expanded.has(s.inspiration);
            const inspiratorStudents = studentsWhoChoseInspirator(students, s.inspiration);
            const placedCount = countPlacedForInspirator(students, s.inspiration);
            const unplacedCount = countUnplacedForInspirator(students, s.inspiration);
            return (
              <Fragment key={s.inspiration}>
                <tr className={isOpen ? "stats-row-expanded" : undefined}>
                  <td className="stats-expand-cell">
                    <button
                      type="button"
                      className="stats-expand-btn"
                      aria-expanded={isOpen}
                      aria-label={isOpen ? "Dölj elever" : "Visa elever"}
                      disabled={s.count === 0}
                      onClick={() => toggleExpanded(s.inspiration)}
                    >
                      <span className={`stats-expand-icon ${isOpen ? "expanded" : ""}`}>
                        ▶
                      </span>
                    </button>
                  </td>
                  <td>{s.inspiration}</td>
                  <td>{inspiratorStudents.length}</td>
                  <td>{passCountByInspirator.get(s.inspiration) ?? 0}</td>
                  <td>
                    <span className="badge ok">{placedCount}</span>
                  </td>
                  <td>
                    {unplacedCount > 0 ? (
                      <span className="badge warn">{unplacedCount}</span>
                    ) : (
                      <span className="badge ok">0</span>
                    )}
                  </td>
                </tr>
                {isOpen && (
                  <tr className="stats-students-row">
                    <td />
                    <td colSpan={5}>
                      {inspiratorStudents.length === 0 ? (
                        <p className="stats-students-empty">Inga elever har valt denna inspiratör.</p>
                      ) : (
                        <ul className="stats-student-list">
                          {inspiratorStudents.map((st) => {
                            const choiceLabel = formatChoiceRanks(
                              studentChoiceRanksForInspirator(st, s.inspiration)
                            );
                            return (
                            <li key={st.id}>
                              <button
                                type="button"
                                className="stats-student-link"
                                onClick={() => onStudentClick(st.id)}
                              >
                                {st.first_name} {st.last_name}
                              </button>
                              {choiceLabel && (
                                <span className="stats-student-choice">{choiceLabel}</span>
                              )}
                              <span className="stats-student-meta">{st.school}</span>
                              {isPlacedWithInspirator(st, s.inspiration) ? (
                                <span className="badge ok stats-student-status">Placerad</span>
                              ) : studentHasFullSchedule(st) ? (
                                <span className="badge ok stats-student-status">
                                  Tre pass (annat val)
                                </span>
                              ) : (
                                <span className="badge warn stats-student-status">Oplacerad</span>
                              )}
                            </li>
                            );
                          })}
                        </ul>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
        <tfoot>
          <tr className="stats-total-row">
            <td />
            <th scope="row">Summa</th>
            <td>
              <strong>{students.length}</strong>
              {totalChoiceSlots !== students.length && (
                <span className="stats-total-meta"> ({totalChoiceSlots} val totalt)</span>
              )}
            </td>
            <td>
              <strong>{totalPasses}</strong>
            </td>
            <td>
              <span className="badge ok">{totalPlacedStudents}</span>
            </td>
            <td>
              {totalUnplacedStudents > 0 ? (
                <span className="badge warn">{totalUnplacedStudents}</span>
              ) : (
                <span className="badge ok">{totalUnplacedStudents}</span>
              )}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

function IntegritetTab({ studentCount }: { studentCount: number }) {
  const [showPrivacy, setShowPrivacy] = useState(false);

  return (
    <div className="card">
      <h2>Integritet och GDPR</h2>
      <p style={{ color: "var(--muted)", fontSize: "0.9rem" }}>
        Hantera personuppgifter enligt GDPR. Dela inte lösenord eller exportfiler med obehöriga.
      </p>
      <ul className="integritet-list">
        <li>
          <button type="button" className="link-button" onClick={() => setShowPrivacy(true)}>
            Läs integritetsinformation
          </button>
        </li>
        <li>
          <a href={api.gdprExportUrl} download="karriar_registerutdrag.json">
            <button type="button" className="primary">
              Ladda ner registerutdrag (JSON)
            </button>
          </a>
          <span className="integritet-hint">
            {studentCount} elever i databasen
          </span>
        </li>
        <li>
          Använd «Töm elever/databas» i sidhuvudet när evenemanget är slut (rätt till radering).
        </li>
      </ul>
      {showPrivacy && <PrivacyNotice onClose={() => setShowPrivacy(false)} />}
    </div>
  );
}

function PdfTab({ schools }: { schools: { school: string; count: number }[] }) {
  return (
    <div className="card">
      <h2>PDF per skola</h2>
      <p style={{ color: "var(--muted)", fontSize: "0.9rem" }}>
        Fyra elever per sida (2×2). Kontrollera att alla pass är placerade innan export.
      </p>
      <div className="pdf-bundle-actions" style={{ marginBottom: "1.25rem" }}>
        <a href={api.pdfPlacementBundleUrl()} download>
          <button type="button" className="primary">
            Ladda ner allt som ZIP
          </button>
        </a>
        <p style={{ color: "var(--muted)", fontSize: "0.85rem", margin: "0.5rem 0 0" }}>
          Innehåller Schema (översikt), Rum, Inspiratör och en PDF per skola (
          {schools.length + 3} filer).
        </p>
      </div>
      <table>
        <thead>
          <tr>
            <th>Skola</th>
            <th>Elever</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {schools.map((s) => (
            <tr key={s.school}>
              <td>{s.school}</td>
              <td>{s.count}</td>
              <td>
                <a href={api.pdfUrl(s.school)} download>
                  <button className="primary">Ladda ner PDF</button>
                </a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
