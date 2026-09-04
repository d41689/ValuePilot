export type DcfModelInputs = {
  net_profit_per_share: string | number;
  depreciation_per_share: string | number;
  capital_spending_per_share: string | number;
  based_on_per_share: string | number;
  discount_rate_pct: string | number;
  growth_years: string | number;
  growth_rate_pct: string | number;
  terminal_years: string | number;
  terminal_rate_pct: string | number;
};

export type DcfCanonicalInputs = {
  net_profit_per_share: string | number | null;
  depreciation_per_share: string | number | null;
  capital_spending_per_share: string | number | null;
  based_on_per_share: string | number | null;
};

export function buildDcfModelPayload(options: {
  selection: 'norm' | number;
  inputManifest: Record<string, unknown> | null | undefined;
  inputManifestToken: string | null | undefined;
  canonicalInputs: DcfCanonicalInputs | null | undefined;
  actualInputs: DcfModelInputs;
  growthRateSelection: string | null;
}): Record<string, unknown> | null;
