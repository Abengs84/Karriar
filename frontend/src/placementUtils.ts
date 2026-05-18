import { Placement, Student } from "./api";

const PASS2 = new Set(["pass2a", "pass2b"]);

export function schedulePassKey(passType: string): string {
  return PASS2.has(passType) ? "pass2" : passType;
}

export function studentChoices(s: Student): string[] {
  return [s.choice1, s.choice2, s.choice3, s.reserve].filter(Boolean) as string[];
}

/** Val 1–3 (reserv räknas inte som oplacerad grupp i schemat). */
export function studentRequiredChoices(s: Student): string[] {
  return [s.choice1, s.choice2, s.choice3].filter(Boolean) as string[];
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
      if (!reserveUsed && s.reserve && !suppressed.has(s.reserve)) {
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

export function unplacedByInspirator(
  students: Student[],
  minStudentsThreshold = 0
): [string, Student[]][] {
  const suppressed = getSuppressedInspirations(students, minStudentsThreshold);
  const map = new Map<string, Student[]>();
  for (const inspiration of collectEffectiveInspirations(students, suppressed)) {
    const group = students.filter(
      (s) =>
        studentChoseForPlacement(s, inspiration, suppressed) &&
        !isPlacedWithInspirator(s, inspiration)
    );
    if (group.length > 0) {
      map.set(inspiration, group);
    }
  }
  return [...map.entries()].sort((a, b) => b[1].length - a[1].length);
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

export type PlacementEligibility = {
  eligibleIds: number[];
  skip_already_at_pass: number;
  skip_already_with_inspirator: number;
  skip_not_chose: number;
};

/** Delar upp elev-id:n efter samma regler som backend vid placering. */
export function splitStudentsForPlacement(
  students: Student[],
  studentIds: number[],
  inspiration: string,
  passType: string
): PlacementEligibility {
  const byId = new Map(students.map((s) => [s.id, s]));
  const eligibleIds: number[] = [];
  let skip_already_at_pass = 0;
  let skip_already_with_inspirator = 0;
  let skip_not_chose = 0;

  for (const id of studentIds) {
    const s = byId.get(id);
    if (!s) continue;
    if (!studentChoices(s).includes(inspiration)) {
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
  };
}
