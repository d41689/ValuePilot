export type DcfGrowthRateOption = {
  key: string;
  label: string;
  value: number;
};

export type DcfOepsSeriesEntry = {
  year: number;
  value: number;
};

export type DcfDefaults = {
  oepsNormalized: number | null;
  oepsSeries: DcfOepsSeriesEntry[];
  growthRateOptions: DcfGrowthRateOption[];
  basedOnSelection: 'norm' | number;
  basedOnOverride: string;
  growthRateSelection: string | null;
  growthRate: number | null;
};

export function resolveDcfDefaults(payload: unknown): DcfDefaults;
