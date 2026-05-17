const API = "/api";

export type Room = { id: number; name: string; capacity: number };
export type SessionSlot = {
  id: number;
  room_id: number;
  pass_type: string;
  inspiration: string;
  room_name: string;
  room_capacity: number;
  placed_count: number;
};
export type Placement = {
  id: number;
  session_slot_id: number;
  inspiration?: string;
  pass_type?: string;
  room_name?: string;
};
export type Student = {
  id: number;
  first_name: string;
  last_name: string;
  school: string;
  choice1: string | null;
  choice2: string | null;
  choice3: string | null;
  reserve: string | null;
  lunch_track: string | null;
  placements: Placement[];
};
export type AutoSolveResult = {
  placed_new: number;
  slots_created: number;
  unplaced_count: number;
  unplaced_sample: {
    student_id: number;
    inspiration: string;
    choice_field: string;
    rank: number;
  }[];
  score: number;
  by_choice_field: Record<string, number>;
  summary: string;
  dry_run: boolean;
};

export type InspiratorStat = {
  inspiration: string;
  count: number;
  placed: number;
  unplaced: number;
};

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Något gick fel");
  }
  return res.json();
}

export const api = {
  rooms: {
    list: () => json<Room[]>(`${API}/rooms`),
    create: (name: string, capacity: number) =>
      json<Room>(`${API}/rooms`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, capacity }),
      }),
    update: (id: number, data: Partial<{ name: string; capacity: number }>) =>
      json<Room>(`${API}/rooms/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    delete: (id: number) => fetch(`${API}/rooms/${id}`, { method: "DELETE" }),
  },
  students: {
    list: () => json<Student[]>(`${API}/students`),
  },
  schools: () => json<{ school: string; count: number }[]>(`${API}/schools`),
  sessionSlots: {
    list: (passType?: string) =>
      json<SessionSlot[]>(
        `${API}/session-slots${passType ? `?pass_type=${passType}` : ""}`
      ),
    create: (room_id: number, pass_type: string, inspiration: string) =>
      json<SessionSlot>(`${API}/session-slots`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ room_id, pass_type, inspiration }),
      }),
    delete: (id: number) =>
      json<{ ok: boolean; removed_placements: number }>(`${API}/session-slots/${id}`, {
        method: "DELETE",
      }),
  },
  import: async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${API}/import/excel`, { method: "POST", body: fd });
    if (!res.ok) throw new Error((await res.json()).detail || "Import misslyckades");
    return res.json() as Promise<{
      imported: number;
      skipped_duplicates: number;
      total_students: number;
    }>;
  },
  stats: () => json<InspiratorStat[]>(`${API}/stats/inspirators`),
  placements: {
    atCell: (
      student_ids: number[],
      room_id: number,
      pass_type: string,
      inspiration: string
    ) =>
      json<{
        placed: number;
        skipped_capacity: number;
        skipped_ineligible: number;
        skip_already_at_pass?: number;
        skip_already_with_inspirator?: number;
        skip_not_chose?: number;
      }>(`${API}/placements/at-cell`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ student_ids, room_id, pass_type, inspiration }),
        }
      ),
    bulk: (student_ids: number[], session_slot_id: number) =>
      json<{ placed: number; skipped_capacity: number; skipped_ineligible: number }>(
        `${API}/placements/bulk`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ student_ids, session_slot_id }),
        }
      ),
    remove: (id: number) => fetch(`${API}/placements/${id}`, { method: "DELETE" }),
    setStudentPass: (
      student_id: number,
      pass_type: "pass1" | "pass2" | "pass3",
      session_slot_id: number | null
    ) =>
      json<Student>(`${API}/placements/student-pass`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ student_id, pass_type, session_slot_id }),
      }),
    autoSolve: (body: { mode: "fill" | "replace"; dry_run: boolean }) =>
      json<AutoSolveResult>(`${API}/placements/auto-solve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
  },
  pdfUrl: (school: string) => `${API}/pdf/school/${encodeURIComponent(school)}`,
  lunchTrack: (studentId: number, lunch_track: string | null) =>
    fetch(`${API}/students/${studentId}/lunch-track`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lunch_track }),
    }),
};
