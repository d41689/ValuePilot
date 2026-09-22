const RESEARCH_STEPS = [
  { key: 'observation', title: 'Observation', question: 'What changed?', hint: 'Name the metric, years and source. Separate what you observed from what you infer.' },
  { key: 'explanations', title: 'Possible explanations', question: 'What could explain it?', hint: 'List competing explanations, including a temporary effect and a business-quality concern. These are hypotheses, not facts.' },
  { key: 'evidenceNeeded', title: 'Evidence to check', question: 'What would distinguish those explanations?', hint: 'Name the report, note or comparison you need. Attach reviewed evidence separately below; a to-do is not proof.' },
  { key: 'falsification', title: 'Disconfirming evidence', question: 'What would show that you are wrong?', hint: 'State an observable result or condition that would overturn your explanation. Consider permanent impairment, not just a price move.' },
  { key: 'judgment', title: 'Current judgment', question: 'Can you judge responsibly yet?', hint: 'Write your provisional conclusion or “I cannot judge yet”, what remains unknown and when to revisit. This does not select watch, own or pass.' },
];

function emptyResearchNotes() {
  return Object.fromEntries(RESEARCH_STEPS.map(step => [step.key, '']));
}
function hasResearchNotes(notes) {
  return RESEARCH_STEPS.some(step => typeof notes?.[step.key] === 'string' && notes[step.key].trim());
}
function appendResearchNotes(thesis, notes) {
  if (!hasResearchNotes(notes)) return thesis;
  const block = ['Research notes — user observations and hypotheses', ...RESEARCH_STEPS.map((step, i) =>
    `${i + 1}. ${step.title}\n${typeof notes?.[step.key] === 'string' && notes[step.key].trim() ? notes[step.key] : 'Not recorded'}`)].join('\n\n');
  return `${thesis}${thesis ? '\n\n' : ''}${block}`;
}
module.exports = { RESEARCH_STEPS, emptyResearchNotes, hasResearchNotes, appendResearchNotes };
