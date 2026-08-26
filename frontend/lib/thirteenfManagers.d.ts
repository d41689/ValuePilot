export type ThirteenFManager = {
  id: number;
  displayName: string;
  canonicalName: string;
  cik: string | null;
  managerType: string;
  stylePrimary: string;
  capitalStructure: string;
  marketCapFocus: string | null;
  geoFocus: string | null;
  historicalTurnover: string | null;
  ideologyTags: string[];
  classificationRationale: string | null;
  isFeatured: boolean;
  latestFiling: {
    quarter: string | null;
    quarterEndDate: string | null;
    formType: string | null;
    status: string;
    acceptedAt: string | null;
  } | null;
};

export type ThirteenFManagerQuarter = {
  quarter: string | null;
  quarterEndDate: string | null;
  status: string;
  filing: Record<string, unknown> | null;
  caveats: Array<{ code: string; message: string }>;
};

export type ThirteenFManagerPosition = {
  id: number;
  positionRank: number | null;
  stockId: number | null;
  ticker: string | null;
  companyName: string;
  issuerName: string;
  titleOfClass: string | null;
  valueUsd: number | null;
  shares: number | null;
  shareType: string | null;
  putCall: string | null;
  weightPct: number | null;
  weightUnavailableReason: string | null;
  holdingStreakQuarters: number | null;
  constituentRowCount: number;
  cusips: string[];
  mappingStatus: string;
  impliedReportPrice: number | null;
  marketContext: {
    latestPrice: number | null;
    latestPriceDate: string | null;
    changeSinceReportPct: number | null;
    week52Low: number | null;
    week52High: number | null;
    source: string | null;
  } | null;
};

export type ThirteenFManagerHoldings = {
  status: string;
  reason: { code?: string; message?: string } | null;
  quarter: string | null;
  quarterEndDate: string | null;
  filing: Record<string, unknown> | null;
  caveats: Array<{ code: string; message: string }>;
  summary: {
    commonPositionCount: number;
    reportedCommonValueUsd: number | null;
  };
  commonHoldings: ThirteenFManagerPosition[];
  options: ThirteenFManagerPosition[];
};

export type ThirteenFManagerChange = {
  id: number;
  reportQuarter: string | null;
  quarterEndDate: string | null;
  previousReportQuarter: string | null;
  ticker: string | null;
  companyName: string;
  stockId: number | null;
  changeStatus: string;
  confidenceLevel: string;
  isPrimarySignalEligible: boolean;
  caveatCodes: string[];
  unavailableReason: string | null;
  currentValueUsd: number | null;
  previousValueUsd: number | null;
  valueDeltaUsd: number | null;
  currentShares: number | null;
  previousShares: number | null;
  shareDelta: number | null;
  shareChangePct: number | null;
  currentWeightPct: number | null;
  previousWeightPct: number | null;
  weightDeltaPct: number | null;
  portfolioImpactPct: number | null;
};

export type ThirteenFManagerChanges = {
  status: string;
  reason: { code?: string; message?: string } | null;
  items: ThirteenFManagerChange[];
};

export type ThirteenFManagerHistoryQuarter = {
  quarter: string | null;
  quarterEndDate: string | null;
  status: string;
  filing: Record<string, unknown> | null;
  caveats: Array<{ code: string; message: string }>;
  reportedCommonValueUsd: number | null;
  commonPositionCount: number | null;
  optionPositionCount: number;
  concentration: {
    top1Pct: number | null;
    top5Pct: number | null;
    top10Pct: number | null;
  };
  topHoldings: ThirteenFManagerPosition[];
};

export type ThirteenFManagerHistory = {
  status: string;
  reason: { code?: string; message?: string } | null;
  quarters: ThirteenFManagerHistoryQuarter[];
  activity: ThirteenFManagerChange[];
};

export type ThirteenFManagerPositionHistory = {
  status: string;
  reason: { code?: string; message?: string } | null;
  manager: ThirteenFManager;
  stock: {
    id: number;
    ticker: string | null;
    companyName: string;
    exchange: string | null;
  };
  items: Array<{
    quarter: string | null;
    quarterEndDate: string | null;
    shares: number | null;
    portfolioWeightPct: number | null;
    reportedValueUsd: number | null;
    impliedReportPrice: number | null;
    activity: ThirteenFManagerChange | null;
    caveats: Array<{ code: string; message: string }>;
  }>;
};

export type ThirteenFNewBuyClusterBuyer = {
  manager: ThirteenFManager;
  currentValueUsd: number | null;
  currentShares: number | null;
  portfolioWeightPct: number | null;
  confidenceLevel: string;
  caveatCodes: string[];
  includedInScore: boolean;
  scoreExclusionReasons: string[];
  managerSignalWeight: number | null;
};

export type ThirteenFNewBuyClusters = {
  quarter: string | null;
  managerScope: string;
  filingWindowOpen: boolean;
  officialFilingDeadline: string | null;
  periods: string[];
  coverage: {
    reportedManagerCount: number;
    trackedManagerCount: number;
  };
  items: Array<{
    stock: {
      id: number;
      ticker: string;
      companyName: string;
      exchange: string | null;
    };
    clusterSize: number;
    visibleBuyerCount: number;
    qualityWeightedClusterScore: number;
    hasExcludedEvidence: boolean;
    buyers: ThirteenFNewBuyClusterBuyer[];
  }>;
};

export type ThirteenFFilingSeason = {
  digestDate: string | null;
  inSeason: boolean;
  quarter: string | null;
  deadlineDate: string | null;
  daysSinceDeadline: number | null;
  coverage: {
    reportedManagerCount: number;
    trackedManagerCount: number;
  };
  digests: Array<{
    digestDate: string | null;
    items: Array<{
      manager: ThirteenFManager;
      quarter: string | null;
      filingDate: string | null;
      acceptedAt: string | null;
      holdingsCount: number;
      filingStatus: string;
      caveats: Array<{ code: string; message: string }>;
      topNewPositions: Array<{
        stock: { id: number; ticker: string; companyName: string };
        currentValueUsd: number | null;
        portfolioWeightPct: number | null;
        confidenceLevel: string;
        includedInScore: boolean;
        caveatCodes: string[];
      }>;
    }>;
  }>;
};

export const VALUE_STYLES: string[];
export function titleizeCode(value: unknown): string;
export function normalizeManagers(items: unknown[]): ThirteenFManager[];
export function filterManagers(
  managers: ThirteenFManager[],
  filters?: { scope?: string; style?: string; search?: string },
): ThirteenFManager[];
export function normalizeQuarters(items: unknown[]): ThirteenFManagerQuarter[];
export function normalizeManagerHoldings(payload: unknown): ThirteenFManagerHoldings;
export function normalizeManagerChanges(payload: unknown): ThirteenFManagerChanges;
export function normalizeManagerHistory(payload: unknown): ThirteenFManagerHistory;
export function normalizeManagerPositionHistory(payload: unknown): ThirteenFManagerPositionHistory;
export function filterManagerActivity(
  items: ThirteenFManagerChange[],
  view: string,
): ThirteenFManagerChange[];
export function sortManagerActivity(
  items: ThirteenFManagerChange[],
  view?: string,
): ThirteenFManagerChange[];
export function activityLabel(item: ThirteenFManagerChange): string;
export function normalizeNewBuyClusters(payload: unknown): ThirteenFNewBuyClusters;
export function normalizeFilingSeason(payload: unknown): ThirteenFFilingSeason;
export function formatCurrency(value: unknown): string;
export function formatInteger(value: unknown): string;
export function formatPercentPoints(value: unknown, digits?: number): string;
export function actionLabel(value: unknown): string;
