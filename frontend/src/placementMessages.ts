export type PlacementResult = {
  placed: number;
  skipped_capacity: number;
  skipped_ineligible: number;
  skip_already_at_pass?: number;
  skip_already_with_inspirator?: number;
  skip_not_chose?: number;
};

const PASS_LABELS: Record<string, string> = {
  pass1: "pass 1",
  pass2: "pass 2",
  pass2a: "pass 2a",
  pass2b: "pass 2b",
  pass3: "pass 3",
};

export function formatInspiratorDoubleBookedError(
  inspiration: string,
  otherRoomName: string
): string {
  return (
    `«${inspiration}» har redan ett pass i ${otherRoomName} denna tid. ` +
    "En inspiratör kan bara vara på ett ställe åt gången."
  );
}

export function formatPlacementError(result: PlacementResult, passType: string): string {
  const passLabel = PASS_LABELS[passType] ?? passType;
  const atPass = result.skip_already_at_pass ?? 0;
  const withInsp = result.skip_already_with_inspirator ?? 0;
  const notChose = result.skip_not_chose ?? 0;
  const capacity = result.skipped_capacity ?? 0;

  const parts: string[] = [];
  if (atPass > 0) {
    parts.push(
      `${atPass} elev${atPass === 1 ? "" : "er"} har redan ett annat pass på ${passLabel} (varje elev kan bara ha ett pass per tid)`
    );
  }
  if (withInsp > 0) {
    parts.push(
      `${withInsp} elev${withInsp === 1 ? "" : "er"} är redan placerade hos denna inspiratör`
    );
  }
  if (notChose > 0) {
    parts.push(`${notChose} elev${notChose === 1 ? "" : "er"} har inte valt inspiratören`);
  }
  if (capacity > 0) {
    parts.push(`${capacity} fick inte plats (rummet fullt)`);
  }

  if (parts.length > 0) {
    const hint =
      atPass > 0 && passType === "pass1"
        ? " Prova att dra gruppen till pass 2 eller pass 3 i stället."
        : atPass > 0
          ? " Prova ett annat pass."
          : "";
    return parts.join(". ") + "." + hint;
  }

  return "Ingen elev kunde placeras.";
}

/** Delvis placering: elever som inte kunde placeras av regler (inte kapacitet). */
export function formatPartialIneligibleWarning(
  result: PlacementResult,
  passType: string
): string {
  const n = result.skipped_ineligible ?? 0;
  if (n <= 0) return "";

  const passLabel = PASS_LABELS[passType] ?? passType;
  const atPass = result.skip_already_at_pass ?? 0;
  const withInsp = result.skip_already_with_inspirator ?? 0;
  const notChose = result.skip_not_chose ?? 0;

  const head =
    n === 1
      ? "1 elev kunde inte placeras och finns kvar under Oplacerade grupper"
      : `${n} elever kunde inte placeras och finns kvar under Oplacerade grupper`;

  const reasons: string[] = [];
  if (atPass > 0) {
    reasons.push(
      `${atPass} har redan ett annat pass på ${passLabel}`
    );
  }
  if (withInsp > 0) {
    reasons.push(`${withInsp} är redan placerade hos inspiratören`);
  }
  if (notChose > 0) {
    reasons.push(`${notChose} har inte valt inspiratören`);
  }

  if (reasons.length === 0) return `${head}.`;
  return `${head} (${reasons.join(", ")}).`;
}

/** Elever som inte fick plats i rummet (kapacitet) men övriga placerades. */
export function formatCapacityReturnWarning(count: number): string {
  if (count <= 0) return "";
  if (count === 1) {
    return "Rummet blev fullt – 1 elev kunde inte placeras och finns kvar under Oplacerade grupper.";
  }
  return `Rummet blev fullt – ${count} elever kunde inte placeras och finns kvar under Oplacerade grupper.`;
}
