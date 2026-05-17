import { useCallback, useEffect, useState } from "react";
import { api, InspiratorStat, Room, SessionSlot, Student } from "./api";
import { AutoPlaceTab } from "./AutoPlaceTab";
import { PlacementBoard } from "./PlacementBoard";
import { StudentPlacementTab } from "./StudentPlacementTab";
import { useToast } from "./Toast";

type Tab = "rum" | "import" | "statistik" | "auto" | "placering" | "elever" | "pdf";

export default function App() {
  const [tab, setTab] = useState<Tab>("rum");
  const [rooms, setRooms] = useState<Room[]>([]);
  const [students, setStudents] = useState<Student[]>([]);
  const [slots, setSlots] = useState<SessionSlot[]>([]);
  const [stats, setStats] = useState<InspiratorStat[]>([]);
  const [schools, setSchools] = useState<{ school: string; count: number }[]>([]);
  const [loading, setLoading] = useState(false);
  const showMsg = useToast();

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [r, s, sl, st, sc] = await Promise.all([
        api.rooms.list(),
        api.students.list(),
        api.sessionSlots.list(),
        api.stats(),
        api.schools(),
      ]);
      setRooms(r);
      setStudents(s);
      setSlots(sl);
      setStats(st);
      setSchools(sc);
    } catch (e) {
      showMsg("error", e instanceof Error ? e.message : "Kunde inte hämta data");
    } finally {
      setLoading(false);
    }
  }, [showMsg]);

  /** Uppdaterar elever + pass utan "Laddar…" – används efter drag-drop. */
  const refreshPlacement = useCallback(async () => {
    try {
      const s = await api.students.list();
      const sl = await api.sessionSlots.list();
      setStudents(s);
      setSlots(sl);
      return { students: s, slots: sl };
    } catch (e) {
      showMsg("error", e instanceof Error ? e.message : "Kunde inte uppdatera placering");
      throw e;
    }
  }, [showMsg]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <>
      <header className="app-header">
        <h1>Karriär – Placering</h1>
        <span style={{ opacity: 0.9, fontSize: "0.9rem" }}>
          {students.length} elever · {rooms.length} rum
        </span>
      </header>

      <nav className="tabs">
        {(
          [
            ["rum", "Rum"],
            ["import", "Import"],
            ["statistik", "Statistik"],
            ["auto", "Auto-placering"],
            ["placering", "Placering"],
            ["elever", "Elever"],
            ["pdf", "PDF"],
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
        {tab === "import" && <ImportTab onDone={refresh} showMsg={showMsg} />}
        {tab === "statistik" && <StatsTab stats={stats} />}
        {tab === "auto" && (
          <AutoPlaceTab
            studentCount={students.length}
            roomCount={rooms.length}
            onDone={refresh}
            showMsg={showMsg}
          />
        )}
        {tab === "placering" && (
          <PlacementBoard
            rooms={rooms}
            students={students}
            slots={slots}
            onRefresh={refreshPlacement}
            showMsg={showMsg}
          />
        )}
        {tab === "elever" && (
          <StudentPlacementTab
            students={students}
            slots={slots}
            onRefresh={refresh}
            showMsg={showMsg}
          />
        )}
        {tab === "pdf" && <PdfTab schools={schools} />}
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
    if (!confirm("Ta bort rummet?")) return;
    const res = await api.rooms.delete(id);
    if (!res.ok) {
      const err = await res.json();
      showMsg("error", err.detail || "Kunde inte ta bort");
      return;
    }
    await onRefresh();
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
              <td>{r.capacity}</td>
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
  showMsg,
}: {
  onDone: () => Promise<void>;
  showMsg: (t: "error" | "success", m: string) => void;
}) {
  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const r = await api.import(file);
      showMsg(
        "success",
        `Importerade ${r.imported} nya elever. Hoppade över ${r.skipped_duplicates} dubbletter. Totalt: ${r.total_students}.`
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
        Kolumner: A = timestamp, B = förnamn, C = efternamn, D = skola, E–G = val 1–3, H = reserv.
        Format: &quot;Ekonom – Cecilia Ruotsala&quot;. Dubbletter (samma namn + skola) hoppas över.
      </p>
      <input type="file" accept=".xlsx,.xls" onChange={handleFile} />
    </div>
  );
}

function StatsTab({ stats }: { stats: InspiratorStat[] }) {
  return (
    <div className="card">
      <h2>Val per inspiratör</h2>
      <p style={{ fontSize: "0.9rem", color: "var(--muted)", marginTop: 0 }}>
        Antal unika elever som valt inspiratören (kolumn E, F, G eller H).
      </p>
      <table>
        <thead>
          <tr>
            <th>Inspiratör</th>
            <th>Antal elever</th>
            <th>Placerade</th>
            <th>Oplacerade</th>
          </tr>
        </thead>
        <tbody>
          {stats.map((s, i) => (
            <tr key={i}>
              <td>{s.inspiration}</td>
              <td>{s.count}</td>
              <td>
                <span className="badge ok">{s.placed}</span>
              </td>
              <td>
                {s.unplaced > 0 ? (
                  <span className="badge warn">{s.unplaced}</span>
                ) : (
                  <span className="badge ok">0</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
