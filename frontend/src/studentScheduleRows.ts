import { Placement, Student } from "./api";
import { placementAtSchedulePass, studentRequiredChoices } from "./placementUtils";

export const EVENT_DATE = "Fredag 23.8.2026";
export const EVENT_PLACE = "Åbo Akademi, Vasa";
export const LUNCH_TEXT = "LUNCH, Restaurang Alexander";

const PASS2_LABELS: Record<string, string> = {
  pass2a: "11:45-12:15",
  pass2b: "12:30-13:00",
};

export type StudentScheduleRow =
  | { time: string; kind: "text"; text: string }
  | { time: string; kind: "slot"; inspiration: string; room: string };

function inspirationLabel(student: Student, inspiration: string): string {
  if (
    student.reserve &&
    inspiration === student.reserve &&
    !studentRequiredChoices(student).includes(inspiration)
  ) {
    return `${inspiration} (reserv)`;
  }
  return inspiration;
}

function slotFromPlacement(placement: Placement | undefined): {
  inspiration: string;
  room: string;
} | null {
  if (!placement) return null;
  return {
    inspiration: placement.inspiration ?? "—",
    room: placement.room_name ?? "?",
  };
}

export function buildStudentScheduleRows(student: Student): StudentScheduleRow[] {
  const rows: StudentScheduleRow[] = [
    { time: "10:00-10:45", kind: "text", text: "ÖPPNING I AKADEMISALEN" },
  ];

  const p1 = placementAtSchedulePass(student, "pass1");
  const slot1 = slotFromPlacement(p1);
  rows.push({
    time: "11:00-11:30",
    kind: "slot",
    inspiration: slot1 ? inspirationLabel(student, slot1.inspiration) : "—",
    room: slot1?.room ?? "—",
  });

  const p2 = placementAtSchedulePass(student, "pass2");
  const p3 = placementAtSchedulePass(student, "pass3");

  let track = student.lunch_track;
  if (!track && p2?.pass_type) {
    track = p2.pass_type === "pass2a" ? "2a" : "2b";
  }

  if (track === "2b") {
    rows.push({ time: "11:30-12:15", kind: "text", text: LUNCH_TEXT });
    const slot2 = slotFromPlacement(p2);
    rows.push({
      time: PASS2_LABELS.pass2b,
      kind: "slot",
      inspiration: slot2 ? inspirationLabel(student, slot2.inspiration) : "—",
      room: slot2?.room ?? "—",
    });
  } else {
    const slot2 = slotFromPlacement(p2);
    rows.push({
      time: PASS2_LABELS.pass2a,
      kind: "slot",
      inspiration: slot2 ? inspirationLabel(student, slot2.inspiration) : "—",
      room: slot2?.room ?? "—",
    });
    rows.push({ time: "12:15-13:00", kind: "text", text: LUNCH_TEXT });
  }

  const slot3 = slotFromPlacement(p3);
  rows.push({
    time: "13:15-13:45",
    kind: "slot",
    inspiration: slot3 ? inspirationLabel(student, slot3.inspiration) : "—",
    room: slot3?.room ?? "—",
  });
  rows.push({ time: "14:00", kind: "text", text: "HEMFÄRD" });
  return rows;
}
