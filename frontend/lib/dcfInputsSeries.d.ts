export type DcfInput = {
  value: number | null;
  source?: 'fact' | 'computed' | 'missing';
};

export type DcfCurrencyState = {
  status: 'available' | 'unavailable';
  reason_code: string | null;
  currency: string | null;
  provenance?: Array<Record<string, unknown>>;
};

export type DcfInputsPayload = {
  valuation_currency?: string | null;
  currency_state?: DcfCurrencyState;
  input_manifest?: Record<string, unknown> | null;
  input_manifest_token?: string | null;
  canonical_model_inputs?: {
    net_profit_per_share: string | null;
    depreciation_per_share: string | null;
    capital_spending_per_share: string | null;
    based_on_per_share: string | null;
  };
  net_profit_per_share: DcfInput;
  depreciation_per_share: DcfInput;
  capital_spending_per_share: DcfInput;
};

export type DcfInputsSeriesEntry = DcfInputsPayload & { year: number };

export type DcfInputsResponsePayload = {
  dcf_inputs?: DcfInputsPayload | null;
  dcf_inputs_series?: DcfInputsSeriesEntry[] | null;
};

export function resolveDcfInputsPayload(
  payload: DcfInputsResponsePayload,
  selection: 'norm' | number
): DcfInputsPayload | DcfInputsSeriesEntry | null;

export function resolveDcfComponentInputs(
  payload: DcfInputsResponsePayload,
  selection: 'norm' | number
): {
  netProfitPerShare: string;
  depreciationPerShare: string;
  capexPerShare: string;
};
