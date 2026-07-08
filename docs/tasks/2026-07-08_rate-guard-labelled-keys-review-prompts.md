# Review prompt — PR #106 (Rate Guard labelled accepted keys)

PR: https://github.com/d41689/ValuePilot/pull/106 (branch
`claude/rate-guard-labelled-keys`, off `main`, **not yet merged**)
Task: [`2026-07-08_rate-guard-labelled-keys.md`](./2026-07-08_rate-guard-labelled-keys.md)

## What changed (one focused diff)

Rate Guard's public surface is gated by a shared Bearer key (prior hardening in
PR #104, reviewed in
[`2026-07-07_rate-guard-public-auth-review-results.md`](./2026-07-07_rate-guard-public-auth-review-results.md)
— treat those findings as already CLOSED). This PR only generalizes **which env
vars are accepted keys**: instead of two fixed slots (`RATE_GUARD_API_KEY` +
`RATE_GUARD_API_KEY_PREVIOUS`), `configured_api_keys()` now accepts
`RATE_GUARD_API_KEY` **plus any `RATE_GUARD_API_KEY_<LABEL>`** env var, so each
caller gets a self-documenting, independently-revocable key
(`RATE_GUARD_API_KEY_DEVELOPMENT` for a remote dev box, `_PREVIOUS` for rotation).

```python
# rate-guard/app/auth.py
_PRIMARY_KEY_ENV = "RATE_GUARD_API_KEY"
_KEY_ENV_PREFIX = "RATE_GUARD_API_KEY_"

def configured_api_keys() -> tuple[str, ...]:
    keys = []
    for name, value in os.environ.items():
        if name == _PRIMARY_KEY_ENV or name.startswith(_KEY_ENV_PREFIX):
            stripped = value.strip()
            if stripped:
                keys.append(stripped)
    return tuple(sorted(keys))

def is_authorized(auth_header):        # unchanged from PR #104
    keys = configured_api_keys()
    if not keys: return True           # opt-in default (CI/internal)
    if not auth_header: return False
    provided = auth_header.encode("latin-1", "replace")
    matched = False
    for key in keys:                   # non-early-exit, constant-time per key
        if hmac.compare_digest(provided, f"Bearer {key}".encode("latin-1")):
            matched = True
    return matched
```

Client side is unchanged: each caller still sends one `RATE_GUARD_API_KEY`;
multi-key acceptance is server-only.

## The prompt

```
You are a senior security engineer reviewing PR #106 of ValuePilot. The change
generalizes how the Rate Guard egress proxy decides which Bearer keys are valid
for its PUBLIC endpoint (https://rate-guard.richmom.vip). Your job is to decide
whether this generalization introduces any new way to (a) authorize a request
that should be rejected, or (b) reject/deny one that should pass, or (c) weaken
the existing fail-closed / constant-time / non-ASCII protections.

Repository: https://github.com/d41689/ValuePilot
Branch under review: claude/rate-guard-labelled-keys (PR #106), not yet merged.
Read first:
  - rate-guard/app/auth.py (configured_api_keys, is_authorized, enforce_auth_config)
  - rate-guard/app/main.py (the middleware + the startup guard call)
  - rate-guard/tests/test_auth.py (the new/changed tests)
  - docs/tasks/2026-07-07_rate-guard-public-auth-review-results.md (prior review —
    its findings are CLOSED; do not re-litigate, but do check this PR didn't
    regress any of them)
  - docs/architecture/rate-guard-public-exposure.md (env-var contract + rollout)

Only RATE_GUARD_API_KEY and RATE_GUARD_API_KEY_<LABEL> vars are meant to be keys;
RATE_GUARD_REQUIRE_AUTH is a flag, not a key. Auth is opt-in (no keys → allowed,
for CI/internal); RATE_GUARD_REQUIRE_AUTH=1 makes an empty key set a hard
startup failure (fail-closed) on the exposed instance.

Scrutinize, most-severe first:

  1. OVER-BROAD MATCHING. `name.startswith("RATE_GUARD_API_KEY_")` treats EVERY
     such env var as an accepted key. Enumerate ways this becomes a footgun:
     could a non-key config var ever be named under this prefix and silently
     become a valid credential? Is there a var in the repo/deploy today that
     collides (grep RATE_GUARD_API_KEY across the repo, compose, ci.yml,
     .env*.example, deploy.yml)? Should the code instead use an allow-list of
     known labels, or a stricter pattern? Weigh convenience vs. the "any matching
     var is a credential" blast radius. Confirm `RATE_GUARD_API_KEY` (exact) is
     matched by the `==` branch and that near-misses (`RATE_GUARD_API_KEYS`,
     `RATE_GUARD_API_KEY` without trailing underscore, `RATE_GUARD_API_KEY_`
     with an empty label) behave sanely.

  2. FAIL-OPEN / FAIL-CLOSED PRESERVED. Verify the generalization did not change
     the security posture: no matching var → configured_api_keys() == () → auth
     DISABLED (is_authorized True). With RATE_GUARD_REQUIRE_AUTH=1 and no key,
     enforce_auth_config() must still raise at startup. Does an empty-label or
     whitespace-only labelled var (RATE_GUARD_API_KEY_FOO="   ") correctly count
     as "no key", so it can't accidentally satisfy the fail-closed guard while
     being unusable?

  3. COMPARISON SAFETY UNCHANGED. is_authorized still compares on latin-1 bytes
     via hmac.compare_digest (the PR #104 fix for the non-ASCII-header 500).
     Confirm the multi-key loop is non-early-exit so timing does not reveal which
     key matched, and that iterating a variable NUMBER of keys is an acceptable
     (count-only) side channel. Any input that makes the loop raise instead of
     returning False?

  4. SORTED SECRETS. configured_api_keys() returns tuple(sorted(keys)). Any
     concern sorting secret values (it's internal-only; order isn't exposed)?
     Confirm sorting can't drop/dedupe-collapse two identical keys in a way that
     matters, and doesn't affect correctness.

  5. PER-REQUEST ENV SCAN. is_authorized reads os.environ live each request and
     now iterates all of os.environ. Correctness (no mutation-during-iteration)
     and any DoS-relevant cost with a large environment? Is "live" still the
     intended rotation semantic?

  6. NO CALLER REGRESSION. The client (backend/app/rate_guard/client.py) still
     sends a single RATE_GUARD_API_KEY. Confirm no caller needs a change and that
     an existing deployment with only RATE_GUARD_API_KEY set is unaffected;
     _PREVIOUS still works (matches the prefix) so rotation is intact.

  7. ROLLOUT GAP. The task doc claims a gap-proof rollout: rename host
     RATE_GUARD_API_KEY_PREVIOUS → RATE_GUARD_API_KEY_DEVELOPMENT, ship code,
     and the old running container keeps _PREVIOUS in its baked env until the
     deploy recreates it. Is that reasoning sound — is there any window where the
     remote key is rejected? (Consider: what if a deploy recreates rate-guard
     with the NEW env but OLD image, or vice-versa.)

  8. TEST ADEQUACY. test_auth.py adds "labelled slots all accepted" and "the
     require flag is not a key". What's missing? Candidates: a whitespace-only
     labelled key is ignored; RATE_GUARD_API_KEY exact still works alongside a
     labelled one; a near-miss var name is NOT treated as a key; empty key set +
     REQUIRE_AUTH still raises after the refactor.

For each finding: severity P0 (block merge) / P1 (fix before merge or fast-
follow) / P2 / NIT, a concrete input or repro, and a specific fix. If the change
is clean, say so explicitly and list what you verified. You may verify at runtime
in python:3.11-slim against the real ASGI app (set SEC_CONTACT_EMAIL +
RATE_GUARD_CACHE_DIR to import app.main).
```

## How to consume
Collect findings into `2026-07-08_rate-guard-labelled-keys-review-results.md`.
Because the PR is **not yet merged**, a P0/P1 is fixed on the branch before
merge. Re-run the gate after any fix:
```
docker run --rm -v "$PWD/rate-guard:/code" -w /code python:3.11-slim \
  sh -c "pip install -q -r requirements-dev.txt && pytest -q"
```
