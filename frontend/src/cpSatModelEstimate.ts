/** Uppskattning av CP-SAT-modellstorlek (placement_cp_sat.py). */

export const CP_SAT_CONFIG_WEIGHTS = [
  { key: "lunch_imbalance_weight", label: "Lunchbalans", value: 50, desc: "Per elev i |2a − 2b|" },
  { key: "room_sharing_penalty", label: "Delat rum", value: 10, desc: "Per inspiratörpar (hybrid: ÷4)" },
  {
    key: "small_session_penalty_weight",
    label: "Liten session",
    value: 200,
    desc: "Per underskott mot min_session_size",
  },
  {
    key: "minimize_sessions_weight",
    label: "Färre sessioner",
    value: 500,
    desc: "Per aktiv session (valda inspiratörer)",
  },
] as const;

export const CHOICE_WEIGHTS_CP_SAT = [
  { id: "choice1", label: "Val 1", value: 1000 },
  { id: "choice2", label: "Val 2", value: 500 },
  { id: "choice3", label: "Val 3", value: 200 },
] as const;

export const CHOICE_WEIGHT_RESERVE = {
  id: "reserve",
  label: "Reserv",
  value: 50,
} as const;

export const HARD_CONSTRAINT_ROWS = [
  { name: "Ett pass per elev–inspiratör", formula: "3S", note: "sum(assign[s,i,*]) = 1" },
  { name: "Ett möte per elev och tidspass", formula: "3S", note: "sum(assign[s,*,p]) = 1" },
  {
    name: "Sessionsstorlek",
    formula: "3IP … 6IP",
    note: "sz, aktiv/inaktiv; underskott om min>1",
  },
  { name: "Eget rum (AllDifferent)", formula: "0 eller 1", note: "när same_room och I ≤ R" },
  { name: "Rumslås", formula: "L", note: "room_of[i] = låst rum" },
  { name: "Rumskapacitet", formula: "3I", note: "session_size ≤ kapacitet" },
  { name: "En inspiratör per (rum, passtyp)", formula: "4R", note: "pass1, 2a, 2b, pass3" },
  {
    name: "Minsta session (mjuk)",
    formula: "≤3I",
    note: "deficit × small_session_penalty",
  },
] as const;

export const OBJECTIVE_ROWS = [
  { name: "Valrang", formula: "9S", weight: "1000 / 500 / 200", optional: false },
  { name: "Delat rum", formula: "I(I−1)/2", weight: "10 (÷4 hybrid)", optional: true },
  { name: "Liten session", formula: "≤3I", weight: "200", optional: true },
  { name: "Lunchbalans", formula: "1", weight: "50 × |2a−2b|", optional: true },
  { name: "Färre sessioner", formula: "3×M", weight: "500 × aktiv", optional: true },
] as const;

export function estimateConstraints(
  S: number,
  I: number,
  R: number,
  locks: number,
  minSession: number,
  sameRoom: boolean
): Record<string, number> {
  const assign = 6 * S;
  const sessionPer = minSession > 1 ? 6 : 3;
  const session = sessionPer * 3 * I;
  const capacity = 3 * I;
  const roomPass = 4 * R;
  const exclusive = sameRoom && I <= R ? 1 : 0;
  return {
    assign,
    session,
    capacity,
    roomPass,
    exclusive,
    roomLocks: locks,
    total: assign + session + capacity + roomPass + exclusive + locks,
  };
}

export function estimateObjective(
  S: number,
  I: number,
  M: number,
  minSession: number,
  sameRoom: boolean,
  balanceLunch: boolean,
  minimizeSessions: boolean
): Record<string, number> {
  const choice = 9 * S;
  const sharing = sameRoom ? (I * (I - 1)) / 2 : 0;
  const small = minSession > 1 ? 3 * I : 0;
  const lunch = balanceLunch ? 1 : 0;
  const minSess = minimizeSessions ? 3 * M : 0;
  return {
    choice,
    sharing,
    small,
    lunch,
    minSess,
    total: choice + sharing + small + lunch + minSess,
  };
}
