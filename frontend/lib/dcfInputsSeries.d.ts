export type DcfInput = {
  value: number | null;
  source?: 'fact' | 'computed' | 'missing';
};

export type DcfInputsPayload = {
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

