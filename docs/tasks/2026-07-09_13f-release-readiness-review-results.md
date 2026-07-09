# 13F release readiness review results

Date: 2026-07-09
Branch reviewed: `claude/13f-release-readiness`
Base: `main` / `e1c9631`

## Findings

No blocking findings.

I reviewed the release-readiness diff against the three requested prompts:
authority behavior preservation, accepted_at deploy-gate diagnostics, and
runbook / prod-agent safety. I did not find a correctness, rollout, or
operator-safety issue that should block this PR.

## Review notes

### 1. Authority refactor behavior preservation

The new shared `competition_pool()` in
`backend/app/services/thirteenf_filing_detail.py` preserves the old rule
ordering:

1. parsed, non-terminal HR-family RESTATEMENT amendments;
2. admin-`applied` amendments;
3. HR originals, falling back to all originals for NT-only periods;
4. none.

Specific probes:

- Competing restatements still take precedence over an already-applied
  amendment. `competition_pool()` returns `"restatement"` before checking
  `"amendment_owned"`, and `apply_active_filing_policy()` uses that pool for
  Rule 1.
- Non-competing, non-applied amendments still do not displace originals. They
  are excluded from the restatement pool and only admin-`applied` amendments
  own the amendment slot.
- NT-only originals are still handled: `hr_originals or originals` keeps the
  old “HR beats NT, but NT can win when no HR exists” behavior.
- `_pool` is only used in branches that match its kind. The `none` branch still
  demotes stray active rows.
- The amendment predicate is now shared as `is_amendment_filing()` and covers
  both `is_amendment` and `/A` form suffixes, matching the previous authority
  semantics while eliminating drift with the gate.
- `competition_pool()` is computed from the pre-mutation `filings` list, which
  matches the prior code’s behavior. The refactor did not introduce a new
  “mutate then rank stale pool” path.

### 2. accepted_at deploy gate diagnostics

The gate itself fails closed on any `filings_13f.accepted_at IS NULL`
(`verify_accepted_at_populated()`), so `at_risk_groups` is diagnostic only and
cannot accidentally authorize rollout. The diagnostic now calls the same
`competition_pool()` used by the authority, so it no longer approximates
“group has >=2 filings” as “will freeze.”

Specific probes:

- It no longer over-reports original + non-restatement-amendment shapes such as
  the Berkshire rehearsal case: one-member actual pool means no `at_risk_group`.
- It still reports genuine two-member restatement pools with missing
  `accepted_at`.
- It deliberately skips `amendment_owned` pools because an admin decision owns
  that slot and ordering evidence is not required.
- It excludes no-period rows from `at_risk_groups`, but those rows still fail
  the gate through `null_total`.
- TOCTOU risk is bounded by the gate order: exit 0 requires no NULL rows at the
  moment of the check, and any unsafe authority path remains prohibited until
  that exit 0.

### 3. Runbook and prod prompt safety

The runbook and prod prompt match the code paths I checked:

- `docker-compose.prod.yml` starts the api with `alembic upgrade head &&`, so
  the migration-on-prod-start claim is factual.
- `.github/workflows/deploy.yml` deploys only after CI success on `main` and
  does not listen on tags, so the “tag is retrospective” claim is factual.
- The required order is conservative: deploy -> `t1fu_accepted_at_backfill`
  exit 0 -> authority paths -> `t3_attribution_rollout` -> verification -> tag.
- Phase 1 is read-only and explicitly stops for human approval before mutation.
- The prod prompt handles both branches (`filings == 0` and `filings > 0`) and
  forbids proceeding past a non-zero gate without human decision.
- The T3 rollout uses locked JobRun stage execution for ownership changes and
  Oracle's Lens, and the prompt treats exit 2 as a scheduler/worker conflict to
  wait out rather than ignore.
- Rollback language is accurate for this no-migration release: code revert for
  code, derived-data recompute awareness for attribution/change/Lens products,
  and no rollback of authoritative SEC `accepted_at` metadata.

Residual risk: I did not run the prod-host prompt or inspect real prod state.
That is intentionally left as the next gated production step.

---

## Author's follow-up (2026-07-09) — three prompt questions the review did not answer

The verdict above holds: I independently mapped every OLD branch of
`apply_active_filing_policy` onto a NEW `competition_pool` kind and found no
divergence. But three questions the prompts posed were not addressed. I checked
them and landed the results in this PR.

1. **Prompt 2 Q3 — rule 2's ranking.** Unanswered. `_active_filing_rank` falls
   back to `accession_no` when `accepted_at` is NULL, and rule 2 selects the
   owner with a bare `max()` — no missing-evidence guard, no tie guard — while
   the gate deliberately skips `amendment_owned` groups, so nothing warns. This
   is the accession-is-not-a-time-proxy bug that rules 1 and 3 removed.
   **Measured reachability: 0 of 355 real groups** (rule 2 fires only when no
   parsed non-rejected restatement exists; the two real groups with ≥2 `applied`
   amendments hold RESTATEMENTs and route to rule 1, which is guarded). Latent,
   not blocking → recorded in `docs/BACKLOG.md` with the fix sketch.

2. **Prompt 2 Q6 — what stops the pool logic from being re-inlined and drifting
   again?** Unanswered; the answer was "nothing". Added
   `test_pool_selection_is_defined_once_and_shared`: the authority and the gate
   must both call `competition_pool`, and the pool predicates (`hr_originals`,
   `amendment_status == "applied"`) may appear nowhere else. Falsified before
   trusting it — injecting a re-inlined predicate into the authority turns the
   guard red.

3. **Prompt 3 Q5 — `deferred` under rollback.** Unanswered. Pre-T1-FU
   `_TERMINAL_AMENDMENT_STATUSES` is `{applied, rejected, informational}`; it
   lacks `deferred`. After a code revert the old `apply_amendment_policy` treats
   a deferred RESTATEMENT as non-terminal, resets it to `pending_parse`, and the
   old authority auto-applies it — **an amendment an operator explicitly parked
   goes live because of a rollback.** 0 such rows on dev today; prod unknown.
   The checklist's rollback section now names the hazard and gives the
   pre-revert query + remediation.

Also clarified, since the review passed over it: the production scheduler cannot
trip the missing-acceptance rule (its ingest job fills `accepted_at` in Phase 2
before its own Phase 5 sweep); it can only contend for locks, which surfaces as
`t3_attribution_rollout` exit 2. The runbook and prod prompt now say so instead
of vaguely advising a "quiet window", and explicitly forbid stopping the
scheduler.

## Verification

Targeted review test command:

```bash
docker compose exec -T api sh -lc 'DATABASE_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test" pytest -q tests/unit/test_13f_active_filing_authority.py tests/unit/test_13f_amendment_policy.py tests/unit/test_13f_accepted_at_rollout.py'
```

Result:

```text
60 passed in 1.76s
```
