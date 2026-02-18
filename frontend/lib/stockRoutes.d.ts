export type StockRouteView = 'summary' | 'dcf';

export function normalizeTicker(value: string): string;
export function buildStockRoute(ticker: string, view: StockRouteView): string;
