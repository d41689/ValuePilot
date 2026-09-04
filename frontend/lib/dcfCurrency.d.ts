import type { CanonicalCurrentPrice } from './currentPrice';
import type { DcfCurrencyState, DcfInputsResponsePayload } from './dcfInputsSeries';

export type { DcfCurrencyState } from './dcfInputsSeries';

export function resolveDcfCurrencyState(
  payload: DcfInputsResponsePayload,
  selection: 'norm' | number,
): DcfCurrencyState;
export function formatDcfMoney(value: number, currencyState: DcfCurrencyState): string;
export function resolveSafeMarginState(input: {
  currencyState: DcfCurrencyState;
  currentPrice: CanonicalCurrentPrice | null;
  totalValue: number;
}): { status: 'available' | 'unavailable'; reason_code: string | null; value: number | null };
