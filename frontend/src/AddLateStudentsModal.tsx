import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "./api";

export type DraftStudentRow = {
  id: string;
  firstName: string;
  lastName: string;
  school: string;
  choice1: string;
  choice2: string;
  choice3: string;
  reserve: string;
};

function emptyRow(): DraftStudentRow {
  return {
    id: crypto.randomUUID(),
    firstName: "",
    lastName: "",
    school: "",
    choice1: "",
    choice2: "",
    choice3: "",
    reserve: "",
  };
}

type Props = {
  schoolOptions: string[];
  inspirationOptions: string[];
  onClose: () => void;
  onCreated: () => Promise<void>;
  showMsg: (type: "error" | "success", text: string) => void;
};

export function AddLateStudentsModal({
  schoolOptions,
  inspirationOptions,
  onClose,
  onCreated,
  showMsg,
}: Props) {
  const [rows, setRows] = useState<DraftStudentRow[]>(() => [emptyRow()]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !saving) onClose();
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = "";
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose, saving]);

  const updateRow = (id: string, patch: Partial<DraftStudentRow>) => {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  };

  const addRow = () => {
    setRows((prev) => [...prev, emptyRow()]);
  };

  const removeRow = (id: string) => {
    setRows((prev) => (prev.length <= 1 ? prev : prev.filter((r) => r.id !== id)));
  };

  const submit = async () => {
    const valid = rows.filter(
      (r) => r.firstName.trim() && r.lastName.trim() && r.school.trim()
    );
    if (valid.length === 0) {
      showMsg("error", "Fyll i minst förnamn, efternamn och skola för en elev.");
      return;
    }

    setSaving(true);
    try {
      const result = await api.students.createBulk(
        valid.map((r) => ({
          first_name: r.firstName.trim(),
          last_name: r.lastName.trim(),
          school: r.school.trim(),
          choice1: r.choice1.trim() || null,
          choice2: r.choice2.trim() || null,
          choice3: r.choice3.trim() || null,
          reserve: r.reserve.trim() || null,
        }))
      );
      await onCreated();
      const parts: string[] = [];
      if (result.created > 0) {
        parts.push(
          `Skapade ${result.created} elev${result.created === 1 ? "" : "er"}.`
        );
      }
      if (result.skipped_duplicates > 0) {
        const names =
          result.skipped_names.length > 0
            ? `: ${result.skipped_names.join("; ")}`
            : "";
        parts.push(
          `Hoppade över ${result.skipped_duplicates} dubblett${result.skipped_duplicates === 1 ? "" : "er"}${names}.`
        );
      }
      showMsg(result.created > 0 ? "success" : "error", parts.join(" ") || "Inga elever skapades.");
      if (result.created > 0) onClose();
    } catch (err) {
      showMsg("error", err instanceof Error ? err.message : "Kunde inte skapa elever");
    } finally {
      setSaving(false);
    }
  };

  const missingOptions = schoolOptions.length === 0 || inspirationOptions.length === 0;

  return createPortal(
    <div
      className="privacy-overlay late-students-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="late-students-title"
      onClick={() => {
        if (!saving) onClose();
      }}
    >
      <div
        className="privacy-dialog card late-students-dialog"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="late-students-title">Sena anmälningar</h2>
        <p className="privacy-muted" style={{ marginTop: 0 }}>
          Lägg till elever som saknas i Excel-importen. Skolor och inspiratörer kommer från befintlig
          data i systemet.
        </p>
        {missingOptions && (
          <p className="badge warn" style={{ display: "inline-block" }}>
            Importera Excel först så att skolor och inspiratörer finns i listorna.
          </p>
        )}

        <div className="late-students-table-wrap">
          <table className="late-students-table">
            <thead>
              <tr>
                <th>Förnamn</th>
                <th>Efternamn</th>
                <th>Skola</th>
                <th>Val 1</th>
                <th>Val 2</th>
                <th>Val 3</th>
                <th>Reserv</th>
                <th aria-label="Ta bort rad" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <input
                      type="text"
                      value={row.firstName}
                      disabled={saving}
                      placeholder="Förnamn"
                      onChange={(e) => updateRow(row.id, { firstName: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      type="text"
                      value={row.lastName}
                      disabled={saving}
                      placeholder="Efternamn"
                      onChange={(e) => updateRow(row.id, { lastName: e.target.value })}
                    />
                  </td>
                  <td>
                    <select
                      value={row.school}
                      disabled={saving || schoolOptions.length === 0}
                      onChange={(e) => updateRow(row.id, { school: e.target.value })}
                    >
                      <option value="">Välj skola…</option>
                      {schoolOptions.map((sc) => (
                        <option key={sc} value={sc}>
                          {sc}
                        </option>
                      ))}
                    </select>
                  </td>
                  {(["choice1", "choice2", "choice3", "reserve"] as const).map((field) => (
                    <td key={field}>
                      <select
                        value={row[field]}
                        disabled={saving || inspirationOptions.length === 0}
                        onChange={(e) => updateRow(row.id, { [field]: e.target.value })}
                      >
                        <option value="">—</option>
                        {inspirationOptions.map((insp) => (
                          <option key={insp} value={insp}>
                            {insp}
                          </option>
                        ))}
                      </select>
                    </td>
                  ))}
                  <td className="late-students-row-actions">
                    <button
                      type="button"
                      className="late-students-remove"
                      disabled={saving || rows.length <= 1}
                      title="Ta bort rad"
                      aria-label="Ta bort rad"
                      onClick={() => removeRow(row.id)}
                    >
                      ×
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="late-students-toolbar">
          <button type="button" disabled={saving} onClick={addRow} title="Lägg till rad">
            + Ny rad
          </button>
        </div>

        <div className="privacy-actions late-students-actions">
          <button type="button" disabled={saving} onClick={onClose}>
            Avbryt
          </button>
          <button
            type="button"
            className="primary"
            disabled={saving || missingOptions}
            onClick={() => void submit()}
          >
            {saving ? "Skapar…" : "Skapa nya"}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
