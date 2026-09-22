export type DocumentProcessingResult = {
  tone: 'success' | 'warning' | 'danger';
  title: string;
  description: string;
  warnings: string[];
};
export function getCalculationWarnings(payload: unknown): string[];
export function getDocumentProcessingResult(payload: unknown): DocumentProcessingResult;
