export type DynamicFScoreStatusTone = 'success' | 'warning' | 'danger' | 'secondary';

export type DynamicFScoreApiRow = {
  category?: string;
  check?: string;
  metric_key?: string;
  formula?: string;
  formula_details?: {
    standard_definition?: string;
    standard_formula?: string;
    fallback_formulas?: string[];
    used_formula?: string;
    used_values?: Array<{
      metric_key?: string;
      value_numeric?: number | null;
      period_end_date?: string;
      fact_nature?: string;
    }>;
  };
  scores?: Array<number | null>;
  score_fact_natures?: Array<string | null>;
  status?: string;
  status_tone?: DynamicFScoreStatusTone | string;
  comment?: string;
};

export type DynamicFScoreApiCard = {
  years?: Array<number | string>;
  rows?: DynamicFScoreApiRow[];
} | null;

export type DynamicFScoreRow = {
  category: string;
  check: string;
  metricKey: string;
  formula: string;
  formulaDetails: DynamicFScoreFormulaDetails;
  scores: Array<number | null>;
  scoreFactNatures: Array<string | null>;
  status: string;
  statusTone: DynamicFScoreStatusTone;
  comment: string;
};

export type DynamicFScoreFormulaDetails = {
  standardDefinition: string;
  standardFormula: string;
  fallbackFormulas: string[];
  usedFormula: string;
  usedValues: Array<{
    metricKey: string;
    valueNumeric: number | null;
    periodEndDate: string;
    factNature: string;
  }>;
};

export type DynamicFScoreCardModel = {
  years: string[];
  rows: DynamicFScoreRow[];
};

export function normalizeDynamicFScoreCard(card: DynamicFScoreApiCard): DynamicFScoreCardModel;
export function normalizeFormulaDetails(details: DynamicFScoreApiRow['formula_details']): DynamicFScoreFormulaDetails;
export function visibleFallbackFormulas(details: Pick<DynamicFScoreFormulaDetails, 'fallbackFormulas' | 'usedFormula'>): string[];
export function formatDynamicFScoreValue(value: number | null | undefined): string;
