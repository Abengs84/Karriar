import type { Room, Student } from "./api";
import { getSuppressedInspirations, studentRequiredChoices } from "./placementUtils";

export type RoomCapacityInsight = {
  studentCount: number;
  roomCount: number;
  inspiratorCount: number;
  totalSeatsPerPass: number;
  maxInspiratorDemand: number;
  topInspirator: string | null;
  recommendedRoomCount: number;
  recommendedMinCapacity: number;
  shortageInspiratorRooms: number;
  shortageSeatsPerPass: number;
  severity: "ok" | "warn";
  summary: string;
  detailLines: string[];
};

/** Uppskattar rums-/kapacitetsbrist utifrån elevval och befintliga rum. */
export function analyzeRoomCapacity(
  students: Student[],
  rooms: Room[],
  minStudentsThreshold: number
): RoomCapacityInsight | null {
  if (students.length === 0 || rooms.length === 0) {
    return null;
  }

  const suppressed = getSuppressedInspirations(students, minStudentsThreshold);
  const demand = new Map<string, number>();
  for (const s of students) {
    const seen = new Set<string>();
    for (const insp of studentRequiredChoices(s)) {
      if (suppressed.has(insp) || seen.has(insp)) continue;
      seen.add(insp);
      demand.set(insp, (demand.get(insp) ?? 0) + 1);
    }
  }

  const ranked = [...demand.entries()].sort((a, b) => b[1] - a[1]);
  const inspiratorCount = ranked.length;
  const maxInspiratorDemand = ranked[0]?.[1] ?? 0;
  const topInspirator = ranked[0]?.[0] ?? null;
  const studentCount = students.length;
  const roomCount = rooms.length;
  const totalSeatsPerPass = rooms.reduce((sum, r) => sum + r.capacity, 0);
  const largestExistingCapacity = Math.max(...rooms.map((r) => r.capacity), 0);

  const recommendedRoomCount = inspiratorCount;
  const recommendedMinCapacity =
    maxInspiratorDemand > 0 ? Math.max(1, Math.ceil(maxInspiratorDemand / 3)) : 0;

  const shortageInspiratorRooms = Math.max(0, inspiratorCount - roomCount);
  const shortageSeatsPerPass = Math.max(0, studentCount - totalSeatsPerPass);

  const hasShortage = shortageInspiratorRooms > 0 || shortageSeatsPerPass > 0;
  const severity: "ok" | "warn" = hasShortage ? "warn" : "ok";

  const detailLines: string[] = [];

  if (shortageInspiratorRooms > 0) {
    detailLines.push(
      `${inspiratorCount} inspiratörer har val men bara ${roomCount} rum – ${shortageInspiratorRooms} inspiratör(er) måste dela rum (hybrid) eller ni behöver fler rum.`
    );
  }

  if (shortageSeatsPerPass > 0) {
    detailLines.push(
      `Totalt ${totalSeatsPerPass} platser per tidspass (pass 1, 2 eller 3), men ${studentCount} elever ska ha ett pass vardera – brist på cirka ${shortageSeatsPerPass} platser per tid om alla skulle ligga samtidigt.`
    );
  }

  if (maxInspiratorDemand > largestExistingCapacity) {
    detailLines.push(
      `Största gruppen (${topInspirator ?? "—"}, ${maxInspiratorDemand} elever) behöver flera pass i samma rum – största sal idag har ${largestExistingCapacity} platser.`
    );
  }

  let summary: string;
  if (!hasShortage && maxInspiratorDemand <= largestExistingCapacity) {
    summary =
      `Rum och kapacitet ser rimliga ut för ${studentCount} elever och ${inspiratorCount} inspiratörer med val.`;
  } else {
    summary =
      `Det vore optimalt med minst ${recommendedRoomCount} rum` +
      (recommendedMinCapacity > 0
        ? ` med kapacitet cirka ${recommendedMinCapacity}–${maxInspiratorDemand} platser`
        : "") +
      ` (idag ${roomCount} rum, största sal ${largestExistingCapacity} platser).`;
  }

  return {
    studentCount,
    roomCount,
    inspiratorCount,
    totalSeatsPerPass,
    maxInspiratorDemand,
    topInspirator,
    recommendedRoomCount,
    recommendedMinCapacity,
    shortageInspiratorRooms,
    shortageSeatsPerPass,
    severity,
    summary,
    detailLines,
  };
}
