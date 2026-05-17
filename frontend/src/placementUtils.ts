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

export function studentChoseForPlacement(s: Student, inspiration: string): boolean {
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

function collectRequiredInspirations(students: Student[]): string[] {
  const set = new Set<string>();
  for (const s of students) {
    for (const c of studentRequiredChoices(s)) {
      set.add(c);
    }
  }
  return [...set].sort();
}

export function unplacedByInspirator(students: Student[]): [string, Student[]][] {
  const map = new Map<string, Student[]>();
  for (const inspiration of collectRequiredInspirations(students)) {
    const group = students.filter(
      (s) => studentChoseForPlacement(s, inspiration) && !isPlacedWithInspirator(s, inspiration)
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
