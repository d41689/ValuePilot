# SEC financial-history form-aware selection

Status: complete

Owner: Product / Engineering

Date: 2026-08-30

## Goal

Replace raw filing-recency slicing for locked gold-case history acquisition with
a deterministic, form-aware selection that is driven by completed fiscal-year
coverage. Ten years of annual evidence must remain reachable even when recent
interim filings—especially foreign `6-K` filings—are much more numerous.

This advances “estimate normalized owner earnings,” “understand business
quality,” and “disconfirm before deciding” by retaining the annual primary
evidence needed to reconstruct long-run economics while keeping missing years
and bounded-scan limitations explicit. Success is observable when annual filing
coverage wins selection capacity, useful interim evidence is supplemental, and
an incomplete denominator returns typed failures rather than a success-shaped
short recent slice.

## Acceptance criteria

- Gold-case acquisition derives up to ten completed fiscal years from the
  locked case fiscal-year end, available-history start, evaluation cutoff, and
  cap.
- For each expected fiscal year, `10-K`/`10-K/A` or `20-F`/`20-F/A` is selected
  before supplemental interim forms consume the bounded filing count.
- US `10-Q`/`10-Q/A` may supplement selected annual history.
- A foreign `6-K` is supplemental only when its filing description is
  deterministically classified as financial-results evidence; a generic or
  unrelated `6-K` never crowds out annual history.
- Historical-submissions scanning continues until annual fiscal-year coverage
  is satisfied or its existing request bound is exhausted. Ten completed years
  fit within the filing and request bounds.
- Missing selected annual years and exhausted scans are typed failures.
- Exact PIT replay returns cutoff-visible terminal parse failures as typed,
  nonzero results alongside any successful filings; an empty success means
  there is genuinely no eligible filing or run history at the requested cutoff.
- Causally impossible report periods are excluded before coverage and rejected
  at the database boundary. Legitimate after-hours SEC acceptance followed by
  a next-business-day official filing date remains valid.
- As-of filtering, `known_at` behavior, append-only lineage, reviewed identity,
  and deterministic ingestion order remain unchanged.

## Scope

### In

- Coverage target and form-aware discovery/selection in SEC financial
  ingestion.
- Locked manifest cutoff/history wiring in the gold-case operator command.
- Deterministic tests for US annual priority, foreign annual priority over noisy
  `6-K`, useful/unhelpful `6-K` classification, completed fiscal-year
  denominator, request-bound gaps, PIT ordering, and filing-period integrity.
- A database constraint and fail-closed migration preflight for impossible SEC
  report-period metadata.

### Out

- SEC artifact or parse-input manifest hashing.
- Canonical SEC-to-`metric_facts` mapping or financial comparability policy.
- Treating `6-K` as a `10-Q` equivalent.
- Changes to the locked gold-set manifest.

## PRD and architecture references

- `AGENTS.md`
- `docs/architecture/research-decision-support.md`
- `docs/architecture/coverage-source-policy.md`
- `docs/architecture/parsing.md`
- `docs/plans/financial_truth_decision_loop_beta_acceptance.md` §2
- `docs/prd/value-pilot-prd-v0.1.md` §H.3 and §H.7
- `docs/BACKLOG.md` FT-03 and FT-05
- `docs/acceptance/financial_truth_beta_gold_set.yml`
- [SEC filing-date guidance for after-hours submissions](https://www.sec.gov/submit-filings/filer-support-resources/how-do-i-guides/determine-status-my-filing)

## Files to change

- `backend/app/services/sec_financial_ingestion.py`
- `backend/app/cli/sec_financials.py`
- `backend/app/acceptance/financial_truth_gold_set.py`
- `backend/app/models/sec_financials.py`
- `backend/alembic/versions/20260830120000-sec-financial-filing-period-integrity.py`
- `backend/tests/unit/test_sec_financial_history_selection.py` (new)
- `backend/tests/unit/test_sec_financial_cli.py`
- `backend/tests/unit/test_sec_financial_lineage.py`
- `backend/tests/unit/test_sec_financial_lineage_migration.py`
- `backend/tests/unit/test_financial_truth_gold_set.py`
- `docs/tasks/2026-08-30_sec-financial-history-selection.md`

## Test plan

1. `docker compose exec -T api pytest -q tests/unit/test_sec_financial_history_selection.py tests/unit/test_sec_financial_cli.py tests/unit/test_sec_financial_lineage.py tests/unit/test_sec_financial_lineage_migration.py tests/unit/test_financial_truth_gold_set.py tests/unit/test_sec_financial_source_guard.py`
2. Isolated Alembic round-trip, dirty-data preflight, and valid after-hours
   preservation are exercised by `test_sec_financial_lineage_migration.py`.
3. `git diff --check`

The exact full canonical commands remain the closing gate for the complete
multi-step repair. This standalone step will not claim final readiness.

## Decisions and gotchas

- 2026-08-30: annual coverage is defined by annual filing `report_date` fiscal
  year, not by count of approved forms. Amendments remain independently eligible
  but cannot consume the one-per-year annual coverage reservation ahead of an
  older fiscal year.
- 2026-08-30: `6-K` usefulness is a conservative metadata classification. It
  controls acquisition priority only and does not assert quarterly equivalence,
  canonical meaning, or comparability.
- 2026-08-30: a gold-case run defaults to the locked evaluation cutoff; an
  explicit timezone-aware `--as-of` may request a different filing-selection
  slice. This filters SEC `accepted_at`; it is not a knowledge cutoff and never
  backdates newly acquired lineage.
- 2026-08-30: adversarial review found that conflicting duplicate accessions
  could satisfy annual coverage before the final last-write-wins dictionary
  collapsed them. Duplicate accessions are now canonicalized before every
  coverage decision. Exact semantic duplicates choose a deterministic source;
  a conflict in form, dates, primary document, or classification description is
  excluded and reported through a bounded `conflicting_filing_metadata` failure.
- 2026-08-30: adversarial review required filing-selection time and evidence
  knowledge time to be visibly separate. The CLI prints runtime only as
  `ingestion_attempted_at`; replay before the first complete evidence boundary
  exits nonzero with `pit_evidence_unavailable`.
- 2026-08-30: `6-K` usefulness accepts only result-bearing earnings/financial
  report phrases. Call, conference, announcement, notice, and generic foreign-
  issuer descriptions remain excluded; the negative vocabulary takes explicit
  precedence when a description combines it with a positive phrase.
- 2026-08-30: operator output includes the stable selection cutoff, regime,
  fiscal-year end, available-history start, exact expected fiscal-year list and
  count, plus the evidence/PIT availability statement.
- 2026-08-30: follow-up review rejected earliest filing `known_at` as a replay
  boundary. The service now derives the earliest fully replayable successful
  evidence set from the effective reviewed identity, filing acceptance and
  knowledge times, retained exact inputs, input-link and storage creation
  markers, and successful parse-run completion/knowledge time, then verifies
  the candidate through the canonical PIT selector. A failed first parse has no
  replay boundary; a later successful retry does, and an idempotent rerun cannot
  move an earlier valid boundary forward.
- 2026-08-30: `_utc_now()` is labeled only as `ingestion_attempted_at`. After
  commit the CLI queries and prints the actual earliest replayable boundary, or
  the typed `pit_evidence_availability=unavailable` state when no complete
  successful evidence exists.
- 2026-08-30: accession shape is validated before grouping, coverage, or
  operator output. Invalid accessions are excluded and represented by a bounded
  SHA-256 token; valid semantic conflicts keep the fixed bounded conflict
  failure.
- 2026-08-30: invalid-accession tokenization uses deterministic
  `backslashreplace` UTF-8 encoding so malformed text containing lone Unicode
  surrogates cannot crash discovery or leak raw unbounded content.
- 2026-08-30: exact replay separately queries identity-valid terminal parse
  runs visible at the requested cutoff. `required_artifact_unavailable`,
  `no_inline_xbrl_facts`, and other bounded internal parse codes are surfaced
  with exit 2 alongside successful evidence from other filings. A later visible
  success supersedes an earlier failed run only for the same filing; no history
  remains a genuine empty success.
- 2026-08-30: recurring fiscal-year-end metadata rejects `0229` consistently in
  both locked-manifest validation and history-target calculation. The current
  static `MMDD` model cannot represent February 29 across non-leap years.
- 2026-08-30: discovery rejects a `report_date` later than either `filed_on` or
  the UTC date of `accepted_at` before it can satisfy coverage. The same rule is
  a database `CHECK`; its migration counts and fails on genuinely invalid legacy
  rows instead of rewriting or backdating them.
- 2026-08-30: the shared-data audit initially found four `10-Q` rows whose
  official `filed_on` was the business day after acceptance. All were accepted
  after 5:30 p.m. ET, matching the SEC's documented next-business-day filing-
  date rule. They are valid semantic exceptions to `filed_on <= accepted date`,
  not dirty data. The narrowed report-period constraint finds zero violations
  and the migration regression proves these rows remain admissible.

## Sign-off trail

- Red tests: the new history-target import failed before implementation; a
  divergent target/filing-selection cutoff was then accepted until its
  fail-closed guard was added. Review regressions reproduced main/history and
  history/history accession conflicts, overly broad `earnings` classification,
  missing stable CLI target output, success-shaped pre-knowledge replay,
  failed-only replay returning empty success, lone-surrogate hashing failure,
  inconsistent recurring `0229` behavior, mixed success/failure replay,
  impossible report dates, broad result-bearing `6-K` combinations, and the
  initially over-strict treatment of valid after-hours SEC filings.
- Targeted Docker tests: `88 passed` across history selection, gold-case CLI,
  SEC lineage and isolated migrations, locked manifest, and SEC source guard
  suites.
- `git diff --check`: passed.
- Adversarial review: Terra PASS on 2026-08-30 with no remaining P0/P1/P2
  findings after the form selection, PIT replay, accession safety, filing-period
  integrity, and SEC after-hours semantics repair rounds.
