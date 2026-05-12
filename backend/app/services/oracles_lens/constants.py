"""Oracle's Lens scoring constants (MVP4-01).

Typed Python module per MVP4 decision gate D5 (TL revision): heuristic
constants live in code so the deploy / migration audit trail is
automatic, not in a DB table whose own per-row versioning would
duplicate the audit problem we want to solve.

Only the score version label is stable in MVP4-01. The plan §7.2
manager-type / position-weight constant tables are intentionally
deferred to MVP4-11 (manager_type taxonomy reconciliation) because
their key set spans three currently-inconsistent vocabularies (admin
enum, behavior-derived profile, plan §7.2 weight keys). Adding them
here would freeze a vocabulary the reconciliation task is supposed to
pick.
"""
from __future__ import annotations

# Bumped when the scoring formula changes in a way that should produce
# a parallel column of scores instead of overwriting the existing ones.
# Used in oracles_lens_signals.score_version and in the JobRun lock_key
# (`oracles_lens_score:{period}:{score_version}`) so a v1.0 production
# run and a v1.1 shadow run can proceed concurrently.
SCORE_VERSION: str = "v1.0"
