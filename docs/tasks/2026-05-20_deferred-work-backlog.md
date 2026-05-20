# 2026-05-20 — Deferred-work backlog + capture rule

## Goal / Acceptance Criteria

- Give the project a single, durable, agent-discoverable home for work that is
  discovered but not done in the change that found it — so follow-ups cannot be
  silently lost.
- Acceptance:
  - `docs/BACKLOG.md` exists as the canonical register, seeded with the real
    open items from PR #64.
  - `AGENTS.md` → Workflow has a "Deferred work" subsection stating the capture
    rule: fix what is in scope, capture the rest, severity gate, where it goes,
    the PR must name what it defers, optional promotion to GitHub Issues.

## Scope

In:
- New `docs/BACKLOG.md`.
- New `### Deferred work` subsection in `AGENTS.md` → Workflow.
- Seed the backlog with the two auth-hardening follow-ups from
  `docs/tasks/2026-05-20_auth-hardening-followups.md`; add a back-pointer there.

Out:
- No GitHub Issues created now — promotion is optional and per-item.
- No tooling to sync the backlog file with GitHub Issues.

## Design decision — why a file, not GitHub Issues, is the primary record

GitHub Issues are good for human triage and assignment, but in an agent-driven
repo they are invisible to an agent's default context: a new session reads repo
files, not the issue tracker, and other agents (Cursor, Aider, Copilot) never
look at Issues. Capture must also work mid-task, offline, and without `gh` auth.
So:

- **Primary (mandatory): `docs/BACKLOG.md`**, in-repo. It appears in PR diffs,
  is grep-able, and every agent sees it by reading the repo.
- **Secondary (optional): GitHub Issues** for long-lived items that need human
  scheduling. The backlog entry carries the issue number; the entry — not the
  issue — is the guarantee against loss.

## Test plan

Docs-only change — no code, no CI. Verification is human review:
- `AGENTS.md` still parses as the `@AGENTS.md` import target.
- `docs/BACKLOG.md` entries each carry date / source / severity / context.

## Notes

- 2026-05-20: User raised the "discovered N problems, can't fix all now" gap and
  proposed GitHub Issues. Agreed on file-primary / Issues-secondary for the
  reasons above.
- Sequenced after PR #65 (the AGENTS.md restructure) so the new subsection slots
  cleanly into the Workflow section that #65 introduced.
