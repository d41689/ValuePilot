export const DCF_MODEL_BOUNDS: Readonly<{
  maxYears: number;
  maxRatePct: number;
  maxAbsPerShare: number;
  maxResultPerShare: number;
}>;

export function computeGrowthValue(
  baseValue: number,
  discountRatePct: number,
  years: number,
  growthRatePct: number
): number;

export function computeTerminalValue(
  baseValue: number,
  discountRatePct: number,
  growthYears: number,
  growthRatePct: number,
  terminalYears: number,
  terminalRatePct: number
): number;

export function computeTotalValue(growthValue: number, terminalValue: number): number;
