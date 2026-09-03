# FT-01 — canonical current-price truth

## Goal

Deliver one authoritative, fail-closed EOD current-price contract for stock
summary, DCF, research workspace/cases, and watchlist. This advances the product
north star by preventing stale, unauthorised, or document-reference prices from
silently changing valuation and margin-of-safety conclusions.

## Acceptance criteria

- Every target surface receives the same canonical EOD fields for the same
  stock and `as_of`: observation id/value/date/source/currency, expected session,
  freshness state/policy, availability state, and typed unavailable reason.
- A current price is comparison-eligible only when its source is authorised,
  its currency is known and exact, and it is fresh for the resolved exchange
  session. Missing, stale, unknown-calendar, unknown-currency, inactive-stock,
  and unauthorised-source states fail closed.
- Stock summary labels `mkt.price` only as a dated report reference. It never
  labels or substitutes it as current price.
- DCF, research, and watchlist publish no margin-of-safety or discount arithmetic
  from an ineligible canonical price. A manual DCF scenario price is explicitly
  separate from current market price and cannot masquerade as canonical.
- Cross-surface tests prove identical valid/missing/stale/unknown-currency/
  unauthorised outcomes and deterministic same-day source selection.
- Product code does not directly select `stock_prices` outside the canonical
  market-data service.

## Scope

### In

- Canonical price read/serialization/eligibility contract.
- Stock summary and DCF API/UI.
- Research workspace/case UI.
- Watchlist API/UI, including safe daily delta behavior.
- Focused backend and frontend contract tests.

### Out

- Licensed long-history and corporate-action adjusted data (FT-15).
- SEC publication or financial-source reconciliation.
- Trading, order, broker, or option execution rails.
- Automatic acquisition beyond the existing coverage refresh job.

## Authority

- GitHub issue #138.
- `docs/BACKLOG.md` FT-01.
- `docs/plans/financial_truth_decision_loop_beta_acceptance.md`.
- `docs/architecture/research-decision-support.md` §§6.2–6.3, 10.2.
- `docs/prd/watchlist/watchlist-v1.md` canonical EOD read contract.
- `docs/architecture/coverage-source-policy.md`.

PR #128 is historical context only. No code, commit, or migration is copied or
cherry-picked from it.

## Design decisions

- Extend the current `CanonicalEodPrice` application contract; do not create a
  second price table or publish price into `metric_facts`.
- Treat source authorisation as a read invariant, not merely an acquisition
  invariant. Test/fixture sources are explicitly injected by policy in tests;
  production defaults remain fail-closed.
- Retain a stale observation for transparent dated display, but set the
  comparison value to unavailable and carry the blocking reason.
- Use one serializer so API surfaces cannot rename or omit decision-critical
  fields independently.
- No migration is expected; add one only if current storage cannot uphold the
  contract.

## Files expected to change

- `backend/app/services/market_data_service.py`
- `backend/app/api/v1/endpoints/stocks.py`
- `backend/app/api/v1/endpoints/stock_pools.py`
- `backend/app/services/research_workspace.py`
- relevant backend tests
- stock summary, DCF, watchlist, and research workspace frontend files
- relevant frontend source-contract tests
- `docs/BACKLOG.md`

## Test plan

Test first with targeted Docker runs, then run the exact repository closing gate:

```text
docker compose up -d --build
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
git diff --check
```

## Sign-off trail

- 2026-09-03: task opened from current `origin/main` (`52a0c3ec`); no #128
  commits or migrations reused.
- 2026-09-03: Draft PR #141 opened before implementation. Contract tests were
  committed red; the implementation extends the existing canonical reader and
  requires no schema or migration change.
- 2026-09-03: focused backend regression set passed (91 tests); frontend unit
  tests passed (220 tests), lint passed, and the production build passed.
- 2026-09-03: exact closing gate passed: Compose rebuild, Alembic upgrade,
  backend `2134 passed`, frontend `220 passed`, frontend lint, production build,
  and `git diff --check`. The first Compose lint attempt found an old anonymous
  `node_modules` volume; `npm install` inside the web container synchronized it,
  after which the exact frontend unit/lint/build commands all passed.
- 2026-09-03: Terra adversarial review round 1 found four valid boundary gaps.
  Remediation now redacts unauthorized coverage evidence before persistence,
  evaluates notifications against the same completed-session clock, routes
  Oracle's Lens arithmetic through the canonical eligible observation, and
  gives 13F comparisons an authorized same-currency current/history context.
  Negative tests cover unauthorized, stale, unknown-currency,
  currency-mismatch, inactive-stock, and post-close states. The focused
  remediation gate passed (`115 passed` backend; `30 passed` frontend); a new
  full closing gate follows before round-2 review.
- 2026-09-03: post-remediation exact closing gate passed: Compose rebuild,
  Alembic upgrade, backend `2146 passed`, frontend `220 passed`, frontend lint,
  production build, and `git diff --check`. No migration was added.
- 2026-09-03: Terra adversarial review round 2 found two remaining read-contract
  gaps. Coverage serialization now revalidates the persisted `stock_price`
  source reference against current provider authorization, redacts the close
  and changes ready/stale wire state to typed `source_unavailable` when that
  authority is absent, and treats missing legacy authorization metadata as
  unproven. The same safe projection drives coverage lists, research workspace
  coverage/missing items, and coverage-change notifications. Regression tests
  cover pre-existing legacy rows and provider revocation after persistence.
- 2026-09-03: manual portfolio positions now return the complete shared
  canonical `current_price` object instead of a second decomposed price
  contract. The UI consumes the shared type and evidence/reason labels and
  renders availability, typed reason, source authorization, expected session,
  as-of semantics, and policy versions. API/UI regressions cover valid,
  unauthorized, stale, unknown-calendar, and position-currency-mismatch states.
- 2026-09-03: no migration or stored-data rewrite is required for round 2.
  Coverage rows remain audit snapshots; current display permission is enforced
  at every serialization boundary, including legacy rows. The #138 bypass scan
  found and closed notification materialization's direct use of persisted
  coverage state/evidence. Application price reads remain centralized in the
  market-data service; the remaining direct `StockPrice` aggregation is the
  separate quant-trading data-audit surface. Focused round-2 verification passed
  (`160 passed` backend; `37 passed` frontend).
- 2026-09-03: post-round-2 exact closing gate passed: Compose rebuild, Alembic
  upgrade, backend `2149 passed`, frontend `220 passed`, frontend lint,
  production build, and `git diff --check`. No migration was added. Draft PR
  #141 is ready for Terra adversarial review round 3.
- 2026-09-03: Terra adversarial review round 3 found three valid gaps.
  Watchlist daily change now requires two available observations with the same
  known ISO currency and publishes a typed `delta_today_state` blocker for
  missing, unknown-currency, or cross-currency inputs. Research workspace and
  Oracle's Lens current-price labels now use one ISO-code formatter, including
  explicit CAD coverage.
- 2026-09-03: canonical point and series readers now exclude observations whose
  `stock_prices.created_at` is after the caller's knowledge cutoff. Exact live
  evaluations pass their timestamp through current and history selection;
  date-only reads use a documented conservative start/end-of-exchange-day
  cutoff. Negative regressions cover a late duplicate, late series history,
  historical alert materialization, and an Oracle's Lens historical 13F
  snapshot. Historical alert fixtures now set their intended ingestion time
  instead of relying on the database's real current clock.
- 2026-09-03: the PIT guarantee is intentionally bounded to append-only
  application writes plus the stored `created_at` ingestion timestamp. Both
  market-data acquisition paths append observations and never update selected
  OHLC rows; there is no claim that this read filter can reconstruct an
  out-of-band mutation to an existing row. No schema or migration change was
  added in round 3. Focused verification passed (`63 passed` backend; `24
  passed` frontend plus frontend lint). A full closing gate follows before
  Terra round 4.
- 2026-09-03: the first round-3 full backend run found one coverage-current
  regression (`2152 passed, 1 failed`): current-day coverage evaluation had a
  precise `evaluated_at` but did not pass it into the price reader, so an
  observation ingested earlier the same day was conservatively hidden by the
  date-only start-of-day cutoff. Coverage now uses its exact evaluation time
  for the current projection while historical service-level dates retain the
  date-only cutoff. The full coverage test file passes (`11 passed`); the exact
  full backend command will be rerun.
- 2026-09-03: post-round-3 exact closing gate passed after the coverage cutoff
  fix: Compose rebuild, Alembic upgrade, backend `2153 passed`, frontend `222
  passed`, frontend lint, production build, and `git diff --check`. The Next
  production build's generated `tsconfig.json` include entry was removed after
  verification; it is not part of the product change. No migration was added.
  Draft PR #141 is ready for Terra adversarial review round 4.
- 2026-09-03: Terra adversarial review round 4 found one valid currency-
  authority gap: the canonical reader accepted any three uppercase letters, so
  a `ZZZ` price and `ZZZ` fact could authorize arithmetic. A single vendored,
  deterministic registry now validates current monetary ISO 4217 codes for
  canonical reads, provider writes, valuation/Oracle facts, stock-summary
  references, and manual-position input. The registry is a 2026-09-03 snapshot
  of the official SIX ISO 4217 Maintenance Agency List One; it has no runtime
  network or locale dependency. `XTS` (testing) and `XXX` (no currency) remain
  fail-closed even though they are reserved List One codes.
- 2026-09-03: round-4 tests were written red first. They reproduced four `ZZZ`
  bypasses in the canonical reader, provider persistence, Watchlist margin of
  safety, and Oracle discount/owner-yield paths, plus invalid manual-position
  input and the explicit-currency/fallback-unit conflict. The focused green run
  passed (`59 passed`); a full closing gate follows before Terra round 5.
- 2026-09-03: post-round-4 exact closing gate passed: Compose rebuild, Alembic
  upgrade, backend `2162 passed`, frontend `222 passed`, frontend lint,
  production build, and `git diff --check`. The Next production build's
  generated `tsconfig.json` include entry was removed after verification; it is
  not part of the product change. No migration or stored-data rewrite was
  added. Draft PR #141 is ready for Terra adversarial review round 5.
- 2026-09-03: Terra adversarial review round 5 found two valid residual gaps.
  Canonical point and series selection had truncated `created_at` to whole
  seconds, allowing a newer microsecond observation with a lower id to lose to
  an older observation. Both readers now share one deterministic selection key:
  explicit source priority, full UTC ingestion datetime, then id. Point and
  series regressions reverse microseconds and ids within the same second.
- 2026-09-03: persisted ready coverage now revalidates both provider authority
  and the referenced `stock_prices.currency` through one exact primary-key
  lookup. A legacy `ZZZ` row is projected as typed
  `price_currency_unavailable`, with display close/currency cleared and state
  blocked. The same serialization drives coverage lists, workspace coverage,
  workspace `missing_items`, and coverage-change notification eligibility, so
  an invalid-currency ready snapshot cannot materialize a ready notification.
  The focused round-5 file suite passed (`56 passed`); a full closing gate
  follows before Terra round 6.
- 2026-09-03: post-round-5 exact closing gate passed: Compose rebuild, Alembic
  upgrade, backend `2166 passed`, frontend `222 passed`, frontend lint,
  production build, and `git diff --check`. The Next production build's
  generated `tsconfig.json` include entry was removed after verification. No
  migration, stored-data rewrite, full-table scan, or alternate canonical
  reader was added. Draft PR #141 is ready for Terra adversarial review round 6.
- 2026-09-03: Terra adversarial review round 6 found one valid read-time
  eligibility gap: a persisted ready price requirement could remain ready after
  the expected market session advanced, or when its cited observation no longer
  matched its evidence/canonical selection. Coverage projection now captures
  one request timestamp and batch-loads both canonical current-price contexts
  and exact cited observations. Ready requires the cited id to exist for the
  same stock, its source/currency/date to match persisted evidence, the
  canonical result to remain eligible at that timestamp, and its selected id to
  equal the citation.
- 2026-09-03: a session rollover projects typed stale
  `price_older_than_expected_session`; mismatched evidence date or canonical id
  projects blocked `price_reference_mismatch`. Both redact the comparison close,
  enter workspace `missing_items`, and cannot materialize a ready notification.
  List, workspace, and notification paths use the same batch serializer, with
  two fixed-count scoped price queries rather than per-row reads or a full-table
  scan. The existing canonical point contract performs all eligibility and
  selection logic. Focused round-6 verification passed (`58 passed`); a full
  closing gate follows before the next Terra review.
- 2026-09-03: post-round-6 exact closing gate passed: Compose rebuild, Alembic
  upgrade, backend `2168 passed`, frontend `222 passed`, frontend lint,
  production build, and `git diff --check`. The first full backend execution
  reached completion but its command session lost the final summary; the exact
  backend command was rerun only after confirming no pytest process remained,
  and returned an explicit green exit (`2168 passed` in 617.36 seconds). The
  Next production build's generated `tsconfig.json` include entry was removed
  after verification. No migration or stored-data rewrite was added. Draft PR
  #141 is ready for the next Terra adversarial review.
- 2026-09-03: Terra adversarial review round 7 found two valid residual gaps.
  Persisted coverage source identity compared a raw evidence label against a
  normalized cited label, so valid aliases could be blocked. A single public
  `normalize_price_source` contract now drives provider construction,
  authorization, selection, and both sides of coverage identity comparison.
  Raw stored/evidence source labels remain unchanged for audit display.
  Regressions cover `yahoo`/`yfinance` and
  `twelve_data`/`12data`/`twelvedata` across coverage list, workspace, and
  ready-notification materialization.
- 2026-09-03: canonical current, point, and current-plus-history readers now
  have composable batch APIs. Every current/context batch captures one
  `evaluated_at`; point batches retain per-stock date-only knowledge cutoffs.
  All batch results delegate the existing single-reader selection,
  authorization, ISO-currency, PIT, and freshness contract. Watchlist, manual
  portfolio, Oracle's Lens, and 13F list projections now use scoped batch Stock,
  price, history, and valuation-fact reads rather than per-item reads. The
  101-stock regression holds point/current/context price queries to `1/1/2`;
  the 101-member Watchlist regression fell from a reproduced `405` SQL
  statements to exactly `5`, with one response clock and expected session.
- 2026-09-03: the first round-7 full backend run exposed one source-scanner
  regression (`2174 passed, 1 failed`): the equivalent batched valuation filter
  no longer contained the machine-verifiable `source_type="parsed"` keyword
  boundary. The batch filter now uses an explicit keyword helper for both
  `manual` and `parsed`, retaining the single scoped fact query. The red guard
  passed before the full rerun.
- 2026-09-03: post-round-7 exact closing gate passed: Compose rebuild, Alembic
  upgrade, backend `2175 passed`, frontend `222 passed`, frontend lint,
  production build, and `git diff --check`. The Next production build's
  generated `tsconfig.json` include entry was removed after verification. No
  migration, stored-data rewrite, unscoped/full-table price read, or alternate
  canonical reader was added. Draft PR #141 is ready for Terra adversarial
  review round 8.
