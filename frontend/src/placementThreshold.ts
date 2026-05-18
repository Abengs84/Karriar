export const MIN_STUDENTS_THRESHOLD_KEY = "karriar_min_students_threshold";

export function readMinStudentsThreshold(): number {
  try {
    const v = localStorage.getItem(MIN_STUDENTS_THRESHOLD_KEY);
    if (v == null) return 0;
    const n = parseInt(v, 10);
    return Number.isFinite(n) && n >= 0 ? n : 0;
  } catch {
    return 0;
  }
}

export function writeMinStudentsThreshold(value: number): void {
  const n = Math.max(0, Math.floor(value));
  localStorage.setItem(MIN_STUDENTS_THRESHOLD_KEY, String(n));
}
