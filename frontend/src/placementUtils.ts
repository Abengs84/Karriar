import { Placement, SessionSlot, Student } from "./api";

const PASS2 = new Set(["pass2a", "pass2b"]);
export const PASS2_VARIANTS = ["pass2a", "pass2b"] as const;

export function schedulePassKey(passType: string): string {
  return PASS2.has(passType) ? "pass2" : passType;
}

export function studentChoices(s: Student): string[] {
  return [s.choice1, s.choice2, s.choice3, s.reserve].filter(Boolean) as string[];
}

/** Val 1–3 + reserv (unika), för manuell placering under Elever. */
export function studentPlacementChoices(s: Student): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const val of [s.choice1, s.choice2, s.choice3, s.reserve]) {
    if (val && !seen.has(val)) {
      seen.add(val);
      out.push(val);
    }
  }
  return out;
}

/** Val 1–3 (reserv räknas inte som oplacerad grupp i schemat). */
export function studentRequiredChoices(s: Student): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  let reserveSubstituteUsed = false;
  for (const field of ["choice1", "choice2", "choice3"] as const) {
    const val = s[field];
    if (!val) continue;
    if (seen.has(val)) {
      if (!reserveSubstituteUsed && s.reserve && !seen.has(s.reserve)) {
        out.push(s.reserve);
        seen.add(s.reserve);
        reserveSubstituteUsed = true;
      }
      continue;
    }
    seen.add(val);
    out.push(val);
  }
  return out;
}

/** Elever som valt inspiratören i val 1–3 (samma logik som statistik-API). */
export function studentsWhoChoseInspirator(students: Student[], inspiration: string): Student[] {
  return students
    .filter((s) => studentRequiredChoices(s).includes(inspiration))
    .sort((a, b) =>
      `${a.last_name} ${a.first_name}`.localeCompare(`${b.last_name} ${b.first_name}`, "sv")
    );
}

/** Vilka val (1–3) eleven angav för inspiratören. */
export function studentChoiceRanksForInspirator(s: Student, inspiration: string): number[] {
  const ranks: number[] = [];
  if (s.choice1 === inspiration) ranks.push(1);
  if (s.choice2 === inspiration) ranks.push(2);
  if (s.choice3 === inspiration) ranks.push(3);
  return ranks;
}

export function formatChoiceRanks(ranks: number[]): string {
  if (ranks.length === 0) return "";
  return `(${ranks.map((r) => `Val ${r}`).join(", ")})`;
}

/** Inspiratörer med ≤ threshold elever (val 1–3). 0 = av. */
export function getSuppressedInspirations(
  students: Student[],
  threshold: number
): Set<string> {
  if (threshold <= 0) return new Set();
  const counts = new Map<string, number>();
  for (const s of students) {
    for (const insp of studentRequiredChoices(s)) {
      counts.set(insp, (counts.get(insp) ?? 0) + 1);
    }
  }
  const suppressed = new Set<string>();
  for (const [insp, n] of counts) {
    if (n <= threshold) suppressed.add(insp);
  }
  return suppressed;
}

/** Val 1–3; undertröskel ersätts av reserv (en gång per elev). */
export function effectiveRequiredChoices(
  s: Student,
  suppressed: Set<string>
): string[] {
  const out: string[] = [];
  let reserveUsed = false;
  for (const c of studentRequiredChoices(s)) {
    if (suppressed.has(c)) {
      if (
        !reserveUsed &&
        s.reserve &&
        !suppressed.has(s.reserve) &&
        !out.includes(s.reserve)
      ) {
        out.push(s.reserve);
        reserveUsed = true;
      }
    } else {
      out.push(c);
    }
  }
  return out;
}

export function studentChoseForPlacement(
  s: Student,
  inspiration: string,
  suppressed?: Set<string>
): boolean {
  if (suppressed && suppressed.size > 0) {
    return effectiveRequiredChoices(s, suppressed).includes(inspiration);
  }
  return studentRequiredChoices(s).includes(inspiration);
}

export function isPlacedWithInspirator(s: Student, inspiration: string): boolean {
  return s.placements.some((p) => p.inspiration === inspiration);
}

export function collectInspirations(students: Student[]): string[] {
  const set = new Set<string>();
  for (const s of students) {
    for (const c of studentChoices(s)) {
      set.add(c);
    }
  }
  return [...set].sort();
}

function collectEffectiveInspirations(
  students: Student[],
  suppressed: Set<string>
): string[] {
  const set = new Set<string>();
  for (const s of students) {
    for (const c of effectiveRequiredChoices(s, suppressed)) {
      set.add(c);
    }
  }
  return [...set].sort();
}

/** Unika elever som syns i oplacerade grupper (samma som backend-räkning). */
export function countUniqueUnplacedStudents(
  students: Student[],
  minStudentsThreshold = 0
): number {
  const suppressed = getSuppressedInspirations(students, minStudentsThreshold);
  const ids = new Set<number>();
  for (const inspiration of collectEffectiveInspirations(students, suppressed)) {
    for (const s of students) {
      if (isUnplacedForInspirator(s, inspiration, suppressed)) {
        ids.add(s.id);
      }
    }
  }
  return ids.size;
}

export function unplacedByInspirator(
  students: Student[],
  minStudentsThreshold = 0
): [string, Student[]][] {
  const suppressed = getSuppressedInspirations(students, minStudentsThreshold);
  const map = new Map<string, Student[]>();
  for (const inspiration of collectEffectiveInspirations(students, suppressed)) {
    const group = students.filter((s) =>
      isUnplacedForInspirator(s, inspiration, suppressed)
    );
    if (group.length > 0) {
      map.set(inspiration, group);
    }
  }
  return [...map.entries()].sort((a, b) => b[1].length - a[1].length);
}

export type AutoPassAssignment = {
  studentId: number;
  passType: "pass1" | "pass2" | "pass3";
  sessionSlotId: number;
};

const SCHEDULE_PASSES = ["pass1", "pass2", "pass3"] as const;

/** Förslag till automatisk placering i Elever (samma regler som dropdown). */
export function buildAutoPassAssignments(
  students: Student[],
  slotsByPass: Record<"pass1" | "pass2" | "pass3", SessionSlot[]>
): AutoPassAssignment[] {
  const cap = new Map<number, number>();
  for (const key of SCHEDULE_PASSES) {
    for (const sl of slotsByPass[key]) {
      cap.set(sl.id, Math.max(0, sl.room_capacity - sl.placed_count));
    }
  }

  const out: AutoPassAssignment[] = [];
  for (const student of students) {
    const usedInsp = new Set(
      student.placements
        .map((p) => p.inspiration)
        .filter((v): v is string => Boolean(v))
    );

    for (const passType of SCHEDULE_PASSES) {
      if (placementAtSchedulePass(student, passType)) continue;

      const choiceOrder = studentPlacementChoices(student);
      const slot = slotsByPass[passType]
        .filter((sl) => choiceOrder.includes(sl.inspiration))
        .filter((sl) => !usedInsp.has(sl.inspiration))
        .filter((sl) => (cap.get(sl.id) ?? 0) > 0)
        .sort(
          (a, b) =>
            choiceOrder.indexOf(a.inspiration) - choiceOrder.indexOf(b.inspiration)
        )[0];

      if (!slot) continue;

      out.push({ studentId: student.id, passType, sessionSlotId: slot.id });
      usedInsp.add(slot.inspiration);
      cap.set(slot.id, (cap.get(slot.id) ?? 0) - 1);
    }
  }
  return out;
}

export function countUnplacedSchedulePasses(students: Student[]): number {
  let n = 0;
  for (const student of students) {
    for (const passType of SCHEDULE_PASSES) {
      if (!placementAtSchedulePass(student, passType)) n += 1;
    }
  }
  return n;
}

export function placementAtSchedulePass(
  student: Student,
  passType: "pass1" | "pass2" | "pass3"
): Placement | undefined {
  const key = passType === "pass2" ? "pass2" : passType;
  return student.placements.find((p) => p.pass_type && schedulePassKey(p.pass_type) === key);
}

export function hasPlacementAtSchedulePass(student: Student, passType: string): boolean {
  const key = schedulePassKey(passType);
  return student.placements.some((p) => p.pass_type && schedulePassKey(p.pass_type) === key);
}

/** Eleven har redan pass 1, 2 och 3 – inget ledigt tidspass kvar. */
export function studentHasFullSchedule(student: Student): boolean {
  return (
    hasPlacementAtSchedulePass(student, "pass1") &&
    hasPlacementAtSchedulePass(student, "pass2") &&
    hasPlacementAtSchedulePass(student, "pass3")
  );
}

/** Ska visas som oplacerad för inspiratören (val 1–3, ej träffad, har ledigt pass). */
export function isUnplacedForInspirator(
  student: Student,
  inspiration: string,
  suppressed?: Set<string>
): boolean {
  if (!studentChoseForPlacement(student, inspiration, suppressed)) return false;
  if (isPlacedWithInspirator(student, inspiration)) return false;
  if (studentHasFullSchedule(student)) return false;
  return true;
}

/** Totalt antal val 1–3 (samma elev kan räknas flera gånger). */
export function totalRequiredChoiceSlots(students: Student[]): number {
  return students.reduce((sum, s) => sum + studentRequiredChoices(s).length, 0);
}

/** Unika elever där alla val 1–3 är placerade hos respektive inspiratör. */
export function countStudentsWithAllChoicesPlaced(students: Student[]): number {
  return students.filter((s) => {
    const choices = studentRequiredChoices(s);
    return choices.length > 0 && choices.every((insp) => isPlacedWithInspirator(s, insp));
  }).length;
}

/** Unika elever med minst ett oplacerat val 1–3 (samma logik som per-rad oplacerade). */
export function countStudentsWithUnplacedChoice(students: Student[]): number {
  return students.filter((s) =>
    studentRequiredChoices(s).some((insp) => isUnplacedForInspirator(s, insp))
  ).length;
}

/** Vilket lunchspår inspiratören redan använder (pass2a eller pass2b). */
export function inspiratorPass2VariantLocked(
  slots: SessionSlot[],
  inspiration: string
): "pass2a" | "pass2b" | null {
  const types = slots
    .filter((s) => s.inspiration === inspiration)
    .map((s) => s.pass_type);
  if (types.includes("pass2a")) return "pass2a";
  if (types.includes("pass2b")) return "pass2b";
  return null;
}

/** Välj pass2a eller pass2b vid placering (samma logik som backend). */
export function resolveInspiratorPass2Variant(
  slots: SessionSlot[],
  inspiration: string
): "pass2a" | "pass2b" {
  const locked = inspiratorPass2VariantLocked(slots, inspiration);
  if (locked) return locked;
  let n2a = 0;
  let n2b = 0;
  for (const s of slots) {
    if (s.pass_type === "pass2a") n2a += s.placed_count;
    if (s.pass_type === "pass2b") n2b += s.placed_count;
  }
  return n2a <= n2b ? "pass2a" : "pass2b";
}

/** Inspiratörens session samma pass i annat rum (dubbelbokning). */
export function inspiratorBookedElsewhereAtPass(
  slots: SessionSlot[],
  inspiration: string,
  passType: string,
  roomId: number
): SessionSlot | undefined {
  const actualPass = resolvePlacementPassType(passType, slots, inspiration);
  return slots.find(
    (s) =>
      s.inspiration === inspiration &&
      s.pass_type === actualPass &&
      s.room_id !== roomId
  );
}

/** Översätt schemacell (pass2) till faktisk passtyp för API. */
export function resolvePlacementPassType(
  passType: string,
  slots: SessionSlot[],
  inspiration: string
): string {
  if (passType === "pass2") {
    return resolveInspiratorPass2Variant(slots, inspiration);
  }
  return passType;
}

export type PlacementEligibility = {
  eligibleIds: number[];
  skip_already_at_pass: number;
  skip_already_with_inspirator: number;
  skip_not_chose: number;
  inspirator_double_booked: boolean;
};

/** Delar upp elev-id:n efter samma regler som backend vid placering. */
export function splitStudentsForPlacement(
  students: Student[],
  studentIds: number[],
  inspiration: string,
  passType: string,
  roomId?: number,
  slots?: SessionSlot[],
  minStudentsThreshold = 0
): PlacementEligibility {
  const suppressed = getSuppressedInspirations(students, minStudentsThreshold);
  const byId = new Map(students.map((s) => [s.id, s]));
  const eligibleIds: number[] = [];
  let skip_already_at_pass = 0;
  let skip_already_with_inspirator = 0;
  let skip_not_chose = 0;
  const inspirator_double_booked =
    roomId != null &&
    slots != null &&
    inspiratorBookedElsewhereAtPass(slots, inspiration, passType, roomId) != null;

  if (inspirator_double_booked) {
    return {
      eligibleIds: [],
      skip_already_at_pass: 0,
      skip_already_with_inspirator: 0,
      skip_not_chose: 0,
      inspirator_double_booked: true,
    };
  }

  for (const id of studentIds) {
    const s = byId.get(id);
    if (!s) continue;
    if (!studentChoseForPlacement(s, inspiration, suppressed)) {
      skip_not_chose += 1;
      continue;
    }
    if (isPlacedWithInspirator(s, inspiration)) {
      skip_already_with_inspirator += 1;
      continue;
    }
    if (hasPlacementAtSchedulePass(s, passType)) {
      skip_already_at_pass += 1;
      continue;
    }
    eligibleIds.push(id);
  }

  return {
    eligibleIds,
    skip_already_at_pass,
    skip_already_with_inspirator,
    skip_not_chose,
    inspirator_double_booked: false,
  };
}
