# Backlog — deferred work

Problems discovered but not yet fixed. The capture rule is in
`AGENTS.md` → Workflow → "Deferred work". Each entry stays until the work is
actually done — remove it in the same PR that resolves it.

Severity: **high** = data-loss / security / production risk; should not sit here
long — escalate to the user. **medium / low** = ordinary follow-up.

## Open

### Refresh tokens have no revocation / reuse detection
- **Found:** 2026-05-20, PR #64 (refresh-token flow)
- **Severity:** medium
- **Problem:** Access and refresh tokens are stateless JWTs. A stolen refresh
  token is usable for up to 7 days unless the account is disabled — there is no
  reuse detection, no rotation blacklist, and no revocation list.
- **Context:** `docs/tasks/2026-05-20_auth-hardening-followups.md` (item 1)
- **Issue:** —

### Interceptor-level tests for `frontend/lib/api/client.ts`
- **Found:** 2026-05-20, PR #64 (refresh-token flow)
- **Severity:** low
- **Problem:** The response interceptor's single-flight / retry / recursion
  behaviour has no unit test; only the pure helpers in `authSession.js` are
  covered.
- **Context:** `docs/tasks/2026-05-20_auth-hardening-followups.md` (item 2)
- **Issue:** —
