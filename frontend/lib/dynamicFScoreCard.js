const dynamicFScoreYears = ['2022', '2023', '2024', '2025', '2026'];

const dynamicFScoreRows = [
  {
    category: '盈利',
    check: 'ROA > 0',
    scores: [1, 1, 1, 1, 1],
    status: '✅',
    statusTone: 'success',
    comment: '底盘极其稳健。',
  },
  {
    category: '',
    check: 'CFO>ROA',
    scores: [1, 1, 0, 0, 0],
    status: '❌',
    statusTone: 'danger',
    comment: '警惕：利润调节风险。',
  },
  {
    category: '安全',
    check: '杠杆率下降',
    scores: [0, 0, 1, 1, 1],
    status: '✅',
    statusTone: 'success',
    comment: '债务压力显著减轻。',
  },
  {
    category: '效率',
    check: '毛利率提升',
    scores: [1, 1, 1, 0, 0],
    status: '⚠️',
    statusTone: 'warning',
    comment: '核心风险：成本上涨。',
  },
  {
    category: '总计',
    check: 'F-Score',
    scores: [7, 7, 8, 7, 7],
    status: '--',
    statusTone: 'secondary',
    comment: '结论：基本面维持强壮。',
  },
];

function getDynamicFScoreTotalRow() {
  return dynamicFScoreRows[dynamicFScoreRows.length - 1];
}

module.exports = {
  dynamicFScoreYears,
  dynamicFScoreRows,
  getDynamicFScoreTotalRow,
};
