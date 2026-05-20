# Review result — AGENTS.md restructure (2026-05-20)

## Second-pass verdict (2026-05-20)

**Approved after remediation for the `AGENTS.md` restructure.** The three
original blockers are fixed in the actual contract docs:

1. The enforcement statement is now accurate: it says none of the invariants is
   fully automated, names the partial DB / AST guards, and calls out the nullable
   provenance gaps (`AGENTS.md:77-82`). This matches the model/migration reality:
   `metric_extractions.document_id` and `page_number` are DB `NOT NULL`, while
   `original_text_snippet` and `metric_facts.source_document_id` remain nullable.
2. The canonical command table now matches `.github/workflows/ci.yml` in order
   and command shape, including `exec -T` and
   `sh -lc 'NODE_ENV=production npm run build'` (`AGENTS.md:28-45`,
   `.github/workflows/ci.yml:43-59`).
3. The task log now honestly lists three deliberate policy changes: tiered task
   logging, Git / PR conventions, and "When to stop and ask"
   (`docs/tasks/2026-05-20_agents-md-restructure.md:27-38`). The review prompt's
   main brief and B3 section were also updated to that model
   (`docs/tasks/2026-05-20_agents-md-restructure-review-prompts.md:24-35`,
   `docs/tasks/2026-05-20_agents-md-restructure-review-prompts.md:72-78`).

One non-blocking cleanup remains in the review prompt itself: its final pass bar
still says B3 should confirm "task-logging is the only intentional semantic
change" (`docs/tasks/2026-05-20_agents-md-restructure-review-prompts.md:127-132`),
which contradicts the updated brief above. This is stale meta-review wording, not
a remaining defect in `AGENTS.md`, but it should be corrected if the prompt file
will be reused.

## Original verdict

**Not approved yet.** The rewrite is directionally good and most old rules were
preserved, but the pass bar is not met because three accuracy / semantic-change
issues remain:

1. **C5 blocker — enforcement claim is wrong.** `AGENTS.md` says invariants 1, 4,
   5, 6 are reviewer-enforced and 2/3 have no automated guard
   (`AGENTS.md:73-74`). Repo evidence does not support that exact statement:
   `metric_extractions.document_id` and `page_number` are DB `NOT NULL`, while
   `original_text_snippet` is nullable (`backend/app/models/extractions.py:16-22`;
   migration `backend/alembic/versions/20260117034130-initial_schema.py:202-210`).
   `metric_facts.source_document_id` is also nullable
   (`backend/app/models/facts.py:29`). So invariant 6 is partly DB-enforced and
   partly not enforced. The line should be corrected instead of guessed.
2. **C6 blocker — canonical commands are not the exact CI commands.** The CI
   workflow uses `docker compose exec -T ...` for all service commands and uses
   `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` for
   the frontend build (`.github/workflows/ci.yml:46-59`). `AGENTS.md` omits `-T`
   and lists frontend build as `docker compose exec web npm run build`
   (`AGENTS.md:34-38`) while also saying these are the exact commands CI runs
   (`AGENTS.md:40-45`). Even if `package.json` also sets `NODE_ENV=production`
   (`frontend/package.json:5-8`), the "exact" claim is false.
3. **B3 blocker — task logging is not the only semantic change.** The new
   Git / PR section adds cross-agent policy that was not in old `AGENTS.md`:
   branch off `main`, never commit directly to `main`, branch naming
   `<agent>/<slug>`, check `git config user.email`, commit/push only when asked,
   and required PR-body contents (`AGENTS.md:104-113`). `CLAUDE.md` has no such
   git mechanics (`CLAUDE.md:1-16`). This may be good policy, but it is a new
   policy, not a location-only restructure.

## A. Losslessness

1. **No rule dropped — PASS with one caveat.** I independently walked the old
   normative statements in `git show main:AGENTS.md` and found their equivalents
   in the new `AGENTS.md` or `docs/architecture/`:

   - Docker/container rule: old `main:AGENTS.md:16-26`; new `AGENTS.md:22`,
     `AGENTS.md:26-45`.
   - Three-layer storage, `metric_extractions` never for screeners,
     `metric_facts` always for screeners/formulas/UI: old `main:AGENTS.md:30-36`;
     new `AGENTS.md:51-54`, `AGENTS.md:128-139`.
   - Stock identity low-similarity review: old `main:AGENTS.md:38-44`; new
     `AGENTS.md:146-148`, full detail `docs/architecture/data-layer.md:7-15`.
   - Metric normalization and scale tokens: old `main:AGENTS.md:46-53`; new
     `AGENTS.md:66-68`, `AGENTS.md:141-144`.
   - Locked `is_current`: old `main:AGENTS.md:55-66`; new
     `docs/architecture/metric-facts-is-current.md:1-40`.
   - Manual corrections: old `main:AGENTS.md:68-74`; new `AGENTS.md:150-153`,
     full detail `docs/architecture/data-layer.md:16-28`.
   - Schema-change no-band-aids and Alembic conventions: old
     `main:AGENTS.md:76-99`; new `docs/architecture/data-layer.md:30-60`.
   - Upsert vs `IntegrityError`: old `main:AGENTS.md:101-119`; new
     `docs/architecture/data-layer.md:62-90`.
   - Parsing scope, fixture workflow, EDGAR gotchas: old `main:AGENTS.md:121-143`;
     new `AGENTS.md:161-172`, `docs/architecture/parsing.md:5-29`.
   - Frontend UI standard and scanner caveat: old `main:AGENTS.md:145-153`; new
     `AGENTS.md:183-202`.
   - Naming, normalization failure, provenance: old `main:AGENTS.md:155-166`;
     new `AGENTS.md:174-181`.
   - Test-first, closing gates, long-lived branch caveat, source-scanner caveat:
     old `main:AGENTS.md:178-207`; new `AGENTS.md:91-102`,
     `AGENTS.md:185-202`.
   - Safety contract checks and per-PR checklist: old `main:AGENTS.md:209-224`;
     new `AGENTS.md:47-74`, `AGENTS.md:115-120`.

   Caveat: the old generic "Run inside a service" command example
   (`main:AGENTS.md:20-24`) is not reproduced as a generic row, but the new
   command table and "all tooling inside containers" rule carry the same meaning
   for practical agent use.

2. **Moved content faithful — PASS.** The spot-checks survived with identical
   meaning:

   - Locked `is_current` text includes PO date / Option A, ADBE 42 rows,
     `_reconcile_parsed_fact_current_slot`, tuple scope, read-side tiebreak, and
     Option B gate (`docs/architecture/metric-facts-is-current.md:6-40`).
   - EDGAR gotchas preserve `shrsOrPrnAmt`, `sshPrnamt`, `sshPrnamtType`,
     `xslForm13F_X02/`, `cusip_ticker_map.source` VARCHAR(50) with exactly
     `"openfigi"`, `"sec_co_tickers"`, `"manual"`, and Kahn Brothers
     `0001039565-*` dollar units (`docs/architecture/parsing.md:19-29`).
   - Alembic identifier rules preserve `down_revision` matching the parent
     `revision` variable and "never change identifiers on rename"
     (`docs/architecture/data-layer.md:52-60`).
   - The schema-change Wrong/Right examples are preserved
     (`docs/architecture/data-layer.md:30-50`).

## B. Intentional Policy Change

3. **Only task logging changed — FAIL.** The tiered task-logging rule is explicit
   (`AGENTS.md:78-89`) and the "when unsure, substantive" clause is good
   (`AGENTS.md:89`). The trivial criteria are reasonably tight: typo/copy tweak
   or single localized fix with no contract or migration impact
   (`AGENTS.md:86-88`).

   However, task logging is not the only semantic change. The Git / PR section
   adds new cross-agent policy (`AGENTS.md:104-113`) that was not present in old
   `AGENTS.md` and is not imported from `CLAUDE.md`. Either mark this as a second
   intentional policy addition in the task and review prompt, or move/remove it
   if this PR must be restructure-only.

## C. New Content Accuracy

4. **Critical invariants — PASS with advisory.** Each listed invariant condenses
   real old rules: source-of-truth and numeric screener rules
   (`main:AGENTS.md:30-36`, `main:AGENTS.md:209-216`), `is_current`
   (`main:AGENTS.md:55-66`), no band-aids (`main:AGENTS.md:76-92`), no raw
   SQL/eval (`main:AGENTS.md:209-216`), normalization (`main:AGENTS.md:46-53`),
   provenance (`main:AGENTS.md:163-166`), and exact CI (`main:AGENTS.md:193-205`).

   Advisory: consider adding either stock identity low-similarity review or
   manual-correction immutability to the critical list. Both are data-corruption
   guardrails, though less catastrophic than global `is_current` dedup.

5. **Enforcement claim — FAIL.** See blocker #1. Additional evidence:
   `frontend/lib/uiStandard.test.js:7-30` does enforce the raw-primitive frontend
   rule, but that is not one of the seven critical invariants. Formula evaluation
   uses a restricted AST (`backend/app/services/formula_engine.py:1-74`), and
   screeners use SQLAlchemy expressions against `MetricFact.value_numeric` and
   `is_current` (`backend/app/services/screener_service.py:198-213`), but there is
   no general source scanner proving invariants 1/4/5. The enforcement sentence
   needs a more precise statement, e.g. "Some invariants have partial tests or DB
   constraints, but none should be treated as fully automated."

6. **Canonical commands table — FAIL.** See blocker #2. Exact CI commands are:
   `docker compose up -d --build` (`.github/workflows/ci.yml:43-44`),
   `docker compose exec -T api alembic upgrade head` (`ci.yml:46-47`),
   `docker compose exec -T api pytest -q` (`ci.yml:49-50`),
   `docker compose exec -T web sh -lc 'node --test lib/*.test.js'`
   (`ci.yml:52-53`), `docker compose exec -T web npm run lint`
   (`ci.yml:55-56`), and
   `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'`
   (`ci.yml:58-59`).

7. **Git / PR conventions — FAIL as written.** They do not contradict
   `CLAUDE.md`; `CLAUDE.md` is strictly Claude-specific and imports `AGENTS.md`
   (`CLAUDE.md:1-16`). The problem is different: the section is new cross-agent
   policy in a PR whose stated only semantic change is task logging. It must be
   acknowledged as intentional or removed.

## D. Structural Integrity

8. **Links resolve — PASS.** Referenced docs exist:
   `docs/architecture/metric-facts-is-current.md`,
   `docs/architecture/data-layer.md`, `docs/architecture/parsing.md`, and
   `docs/tasks/2026-05-13_metric-facts-current-semantics-decision-gate.md`.
   Cross-links in `data-layer.md` and `metric-facts-is-current.md` resolve
   (`docs/architecture/data-layer.md:3-5`,
   `docs/architecture/metric-facts-is-current.md:37-40`).

9. **CLAUDE.md boundary — PASS.** `CLAUDE.md` still imports `@AGENTS.md`
   (`CLAUDE.md:1`). It is limited to Claude-Code memory / mechanically
   Claude-specific rules and explicitly says cross-agent rules belong in
   `AGENTS.md` (`CLAUDE.md:3-16`). I did not find cross-agent rules stranded only
   in `CLAUDE.md`.

## E. Effectiveness

10. **Goal achieved — PASS advisory.** The guardrails are genuinely more
    front-loaded: Docker, definition-of-done, exact verification intent, and the
    seven high-risk invariants are visible before deep data-layer detail
    (`AGENTS.md:9-74`). Moving locked `is_current`, schema-change examples,
    Alembic conventions, write-conflict guidance, fixture alignment, and EDGAR
    gotchas into architecture docs improves the always-loaded signal density.

    I would keep the current amount of inline detail once the blockers above are
    fixed. More extraction would probably hide too much from a fresh agent.

## Required Fixes

1. Replace the enforcement sentence at `AGENTS.md:73-74` with a verified
   statement. Do not claim invariant 6 is purely reviewer-enforced; repo reality
   is mixed DB constraint + nullable gap.
2. Make the command table match `.github/workflows/ci.yml` exactly, including
   `-T`, migration command placement, and the frontend build shell command.
3. Either remove the Git / PR conventions from this restructure or explicitly
   document them as a second intentional policy change and get that accepted.

Second-pass status: all three required fixes are resolved in `AGENTS.md` / the
task log. The only remaining note is the stale pass-bar sentence in the review
prompt file, described at the top of this result.
