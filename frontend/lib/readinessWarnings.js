/* eslint-disable @typescript-eslint/no-require-imports */
// Renders 13F readiness warnings. Extracted from the Oracle's Lens page so the
// render boundary that crashed is unit-testable in the `node --test lib/*.test.js`
// harness (a `.tsx` page cannot be — no JSX transpile in raw node).
//
// Backend `thirteenf_readiness` emits warnings/blockers as structured
// `{ code, message }` (via `_message`). Rendering the object directly threw
// "Objects are not valid as a React child" and keyed on `[object Object]`,
// unmounting the whole page. Render the message; key on the code. A legacy bare
// string is tolerated.
const React = require('react');

function warningText(warning) {
  return warning && typeof warning === 'object' ? warning.message : warning;
}

function warningKey(warning, index) {
  const code = warning && typeof warning === 'object' ? warning.code : undefined;
  return code ?? index;
}

function ReadinessWarnings({ warnings, limit = 3, className = 'space-y-1' }) {
  const list = Array.isArray(warnings) ? warnings.slice(0, limit) : [];
  return React.createElement(
    'div',
    { className },
    list.map((warning, index) =>
      React.createElement('div', { key: warningKey(warning, index) }, warningText(warning)),
    ),
  );
}

module.exports = { ReadinessWarnings, warningText, warningKey };
