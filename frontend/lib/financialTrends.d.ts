import type { FinancialHistory, FinancialHistoryRow } from './financialHistory';
export type AnnualChange = { status: 'available' | 'unavailable' | 'not_meaningful'; reason: string | null; text: string; factIds: number[]; policy: string; caveat: string | null; direction: 'up' | 'down' | 'flat' | null };
export type AnnualPoint = { year: number; observations: FinancialHistoryRow[]; states: FinancialHistoryRow[]; reason: string | null; row: FinancialHistoryRow | null; change: AnnualChange };
export type AnnualReading = { metric: { key: string; label: string; description: string; basis: string }; points: AnnualPoint[] };
export function annualReading(history: FinancialHistory, metricKey: string): AnnualReading;
export function compareAnnual(current: FinancialHistoryRow | null | undefined, previous: FinancialHistoryRow | null | undefined): AnnualChange;
export function formatBillions(row: FinancialHistoryRow): { text: string; unitLabel: string };
export function cashQuestion(income: AnnualReading, cash: AnnualReading): string;
export function chartGeometry(readings: AnnualReading[]): {
  reason: string | null; zeroY: number; minRow: FinancialHistoryRow | null; maxRow: FinancialHistoryRow | null;
  series: { key: string; segments: { x: number; y: number; row: FinancialHistoryRow; year: number }[][] }[];
};
