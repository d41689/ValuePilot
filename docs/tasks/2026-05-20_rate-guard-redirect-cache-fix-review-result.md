# Re-review result — Rate Guard redirect + cache fix, PR #78

Date: 2026-05-20
Branch reviewed: `claude/rate-guard-redirect-cache-fix`
Re-review of the P1 / P2 remediation raised in
`docs/tasks/2026-05-20_rate-guard-service-review-result-2.md`.
Reviewer: independent re-review (Claude Code).

## Verdict

**暂不批准 / Not approved — narrowly.**

Both vulnerabilities from review #2 are **correctly fixed and empirically
verified** — the production code is safe. Approval is held for **one** item: the
P1 regression test does not actually exercise the fix, so the security boundary
is not protected against a future regression. The fix for that is ~3 lines.

- **P2 (cache concurrency) — fully resolved.** Fix correct, regression test
  effective. No further work.
- **P1 (redirect SSRF) — vulnerability resolved, but its regression test is
  ineffective.** The single blocking item below.

## P1 — redirect bypass

### Fix: correct ✅

`rate-guard/app/gateway.py:48` now builds the default client with
`follow_redirects=False`, with a comment explaining why it must stay that way.
A 3xx now reaches `_request_with_retry` and is returned to the caller as-is
(`gateway.py:131-133`) — which also resolves the internal inconsistency review
#2 noted.

Verified (RECHECK A): a `Gateway` built with the production default
(`client=None`) has `_client.follow_redirects == False`. The redirect-based
allowlist bypass demonstrated in review #2 (PROBE 2) is closed.

### Blocking item: the regression test does not guard the fix ❌

`test_redirect_to_off_allowlist_host_is_not_followed`
(`rate-guard/tests/test_gateway.py`) builds its gateway via the `_gateway()`
helper, which constructs `httpx.Client(transport=httpx.MockTransport(handler))`
**without** passing `follow_redirects` — so it takes httpx's default, `False`.
`Gateway.__init__` only applies its own `follow_redirects=False` default when
`client is None`; here a client is always supplied, so **`gateway.py:48` is
never exercised by this test**.

Consequence: if `gateway.py:48` were reverted to `follow_redirects=True`, this
test would still pass. It does not protect the security fix.

Verified (RECHECK B): the redirect outcome is decided **entirely** by the
client's `follow_redirects` —

| client `follow_redirects` | `fetch()` result | off-host body returned |
|---|---|---|
| `False` (what the test helper uses) | `status=302` | no |
| `True` (a reverted `gateway.py:48`) | `status=200` | **yes — bypassed** |

The gateway has no redirect defence of its own; line 48 is the entire fix, and
the test never touches it.

### Required change (~3 lines)

Add a test that exercises the production default — build the gateway with
`client=None` and assert the boundary:

```python
def test_default_client_does_not_follow_redirects(tmp_path):
    gw = Gateway({"test": _upstream()}, ResponseCache(str(tmp_path)))
    assert gw._client.follow_redirects is False
```

This fails if `gateway.py:48` is ever reverted. The existing
`test_redirect_to_off_allowlist_host_is_not_followed` can stay — it is a valid
test of 3xx pass-through behaviour — but it is not the P1 regression guard and
should not be relied on as one.

## P2 — `ResponseCache.put` concurrency — fully resolved ✅

`rate-guard/app/cache.py` now writes through `tempfile.mkstemp(dir=path.parent,
prefix=f"{key}.", suffix=".tmp")` — a unique temp file per call — then
`os.replace`s it onto the final path. The fd is closed via `os.fdopen(...)` in a
`with` block (no fd leak); an `except BaseException` unlinks the temp on any
failure before re-raising (no temp-file leak). `dir=path.parent` keeps the
rename same-filesystem and atomic. Two threads writing the same key now use
distinct temp files and both `os.replace` onto the same target (last-writer-wins,
both payloads valid) — no crash.

The fix is correct, and the regression test **does** guard it:
`test_concurrent_put_same_key_does_not_crash` (12 threads × 40 same-key puts)
would crash under the old shared-`.tmp` code and asserts zero errors, a readable
entry, and no leaked temp files.

Verified (RECHECK C): 16 threads × 80 concurrent same-key puts → **0 errors, 0
leftover `.tmp` files**, cache still serves a valid entry. (Review #2's PROBE 3
on the old code: 557 / 1280 crashed.)

## Scope / other items

- The diff touches only `gateway.py`, `cache.py`, and their two test files — no
  change to `bucket.py`, `metrics.py`, `config.py`, `main.py`. The PASS verdicts
  for A, B, C, F, G in review #2 are unaffected and still stand.
- Behaviour note for the integration PRs (non-blocking): with
  `follow_redirects=False`, a 3xx from an upstream is now surfaced to the caller
  as a 302/301 response rather than transparently followed. PR 2–4 clients must
  handle that. This is the intended, documented behaviour (`gateway.py:131-133`).
- The review #2 non-blocking items (method allowlist, per-upstream opt-in for
  `POST` caching, the CI step running on the runner host with an unpinned
  Python, `main.py` route tests) remain recorded as follow-ups for later Rate
  Guard PRs — not in scope here.

## Verification run

- `docker run --rm … python:3.11-slim` — `pip install -r requirements-dev.txt &&
  python -m pytest -q` → **18 passed** (16 → 18, the two new regression tests).
- RECHECK A — `Gateway` production default client `follow_redirects` is `False`.
- RECHECK B — redirect outcome is determined solely by the client's
  `follow_redirects`; the P1 regression test's helper fixes it to `False`
  independently of `gateway.py:48`, so the test does not guard the fix.
- RECHECK C — 16 × 80 concurrent same-key `cache.put` → 0 errors, 0 leaked temp
  files, valid entry.

## Required before approval

1. Add a test that asserts the **production** `Gateway` default client has
   `follow_redirects is False` (snippet above), so the P1 fix is genuinely
   protected against regression. Re-run the suite (should be 19 tests).

Once that lands, this is approvable — both vulnerabilities are fixed and the
boundary is then guarded.

## Final re-review (2026-05-20) — 批准 / APPROVED

The one blocking item above is resolved by commit `cc87e82`. **PR #78 is
approved.**

`rate-guard/tests/test_gateway.py` adds `test_default_client_does_not_follow_redirects`:
it builds a `Gateway` with `client=None` — the production path through
`gateway.py:48` — and asserts `gw._client.follow_redirects is False`. Unlike
`test_redirect_to_off_allowlist_host_is_not_followed` (which injects its own
client and never reaches line 48), this test genuinely exercises the fix.

Verified (throwaway container copy, repo untouched):

- Full suite — **19 passed** (18 → 19).
- **Guard-flip check** — with `gateway.py:48` reverted to `follow_redirects=True`,
  `test_default_client_does_not_follow_redirects` **fails** (`assert True is
  False`). The test does what a regression guard must: it goes red the moment
  the fix is undone.

Both blockers from review #2 are now fixed **and** each is protected by a test
that fails if its fix regresses:

- **P1** — `follow_redirects=False` (`gateway.py:48`), guarded by
  `test_default_client_does_not_follow_redirects`.
- **P2** — per-write `tempfile.mkstemp` (`cache.py`), guarded by
  `test_concurrent_put_same_key_does_not_crash`.

`gateway.py` / `cache.py` are unchanged since the versions verified above —
commit `cc87e82` touched only the test and docs — so the earlier P1/P2 fix
verification still stands.

The non-blocking follow-ups recorded in review #2 (method allowlist,
per-upstream opt-in for `POST` caching, the CI step running on the runner host
with an unpinned Python, `main.py` route tests) remain open for later Rate Guard
PRs and do not block PR #78.

**Verdict: 批准 / Approved.**
