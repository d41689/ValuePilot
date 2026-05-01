export type DynamicFScoreStatusTone = 'success' | 'warning' | 'danger' | 'secondary';

export type DynamicFScoreRow = {
  category: string;
  check: string;
  scores: number[];
  status: string;
  statusTone: DynamicFScoreStatusTone;
  comment: string;
};

export const dynamicFScoreYears: string[];
export const dynamicFScoreRows: DynamicFScoreRow[];
export function getDynamicFScoreTotalRow(): DynamicFScoreRow;
