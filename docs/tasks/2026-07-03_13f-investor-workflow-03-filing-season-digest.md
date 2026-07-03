# Task: 13F investor workflow 03 — filing-season digest & in-app awareness

**Created:** 2026-07-03 · **Origin:** PO review `2026-07-03_13f-po-review-value-investor.md` (§3 gap #3)
**Status:** DRAFT (next-iteration package)

## Goal / Acceptance Criteria

The four ~2-week windows after the quarterly 13F deadlines (Feb / May / Aug / Nov 14) are the highest-value periods of the 13F year — that is when the habit loop forms. Ops alerting exists (Discord) but the investor-facing surface has zero awareness of filing season.

- **Filing-season state helper (backend):** pure function returning `{in_season, deadline_date, days_since_deadline, quarter}` from the existing deadline logic (`calculate_official_filing_deadline` in `thirteenf_filing_detail.py`) — no new config.
- **Daily digest (backend):** during a window, a scheduled job (existing scheduler/JobRun pattern) computes "what newly became visible since yesterday" for **featured managers**: filings ingested (manager, quarter, holdings count) + their top new positions (reuse ticket 02's aggregation, per-manager slice). Persist as a `notification_events` row per user-visible digest day (reuse the existing v0.1 notifications tables — **no new schema**).
- **In-app surface (frontend):**
  - During a window: a dismissible filing-season banner on Oracle's Lens + Watchlist ("13F filing season — N of 86 featured managers have reported for Q2"), linking to
  - a **digest panel** (section on Oracle's Lens or `/13f/digest`): day-by-day list of newly reported featured managers with new-position highlights, each linking to the manager page (ticket 01).
- Coverage honesty: the banner shows reported/total count; digest rows carry the standard caveat badges; no email/push in V1.

## Scope

**In:** season helper + digest job + `notification_events` writes + banner/panel UI.
**Out:** email/push delivery; per-user "follow manager" targeting (BACKLOG — V1 digest is featured-managers only); non-13F notification surfaces.

## Files to change (indicative)

- `backend/app/services/thirteenf_filing_season.py` [NEW — pure helpers + digest builder]
- scheduler wiring (same pattern as `thirteenf_scheduler.py` daily-sync poll)
- `backend/tests/unit/test_13f_filing_season.py` [NEW — window math incl. weekend-adjusted deadlines; digest idempotency (one event per day)]
- Frontend: season banner component + digest panel; nav badge during season

## Test plan (Docker)

```bash
docker compose exec -T api pytest -q tests/unit/test_13f_filing_season.py
docker compose exec -T api pytest -q          # full backend at closing gate
# frontend lint/test/build per canonical CI
```

PO acceptance: freeze clock inside a window on seeded dev data → banner appears with correct reported-count; digest lists yesterday's newly ingested featured filings; outside the window both surfaces are absent.
