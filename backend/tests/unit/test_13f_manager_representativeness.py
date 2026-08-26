"""P0 contract for reviewed 13F manager representativeness metadata."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.models.institutions import (
    InstitutionManager,
    InstitutionManagerRepresentativenessReview,
)
from app.services.edgar_ingestion import seed_confirmed_managers
from app.services.oracles_lens.constants import (
    CONSENSUS_LENS_VERSION,
    DISTINCTIVE_LENS_VERSION,
    MANAGER_TAXONOMY_VERSION,
    REPRESENTATIVENESS_POLICY_VERSION,
    SCORE_VERSION,
)
from app.services.oracles_lens.representativeness import (
    REPRESENTATIVENESS_FACTORS,
    classify_reviewed_style,
    resolve_manager_representativeness,
)


SEED_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "app"
    / "services"
    / "seed_data"
    / "confirmed_managers.json"
)


def test_lens_and_classification_versions_are_independent_and_pinned():
    assert SCORE_VERSION == "v1.1"
    assert CONSENSUS_LENS_VERSION == "consensus-v1.1"
    assert DISTINCTIVE_LENS_VERSION == "distinctive-v1.1"
    assert MANAGER_TAXONOMY_VERSION == "manager-taxonomy-v2.0"
    assert REPRESENTATIVENESS_POLICY_VERSION == "13f-representativeness-v1.0"


def test_reviewed_style_policy_is_exhaustive_and_conservative():
    assert classify_reviewed_style("value_deep").classification == "faithful"
    assert classify_reviewed_style("value_concentrated").classification == "faithful"
    assert classify_reviewed_style("quality_compounder").classification == "faithful"
    assert classify_reviewed_style("activist").classification == "partial"
    assert classify_reviewed_style("growth_long_short").classification == "partial"
    assert classify_reviewed_style("special_situations").classification == "partial"
    assert classify_reviewed_style("multi_strategy_macro").classification == "partial"
    assert classify_reviewed_style("endowment_passive").classification == "unrepresentative"
    assert classify_reviewed_style("unknown").classification == "unknown"
    assert REPRESENTATIVENESS_FACTORS == {
        "faithful": Decimal("1.00"),
        "partial": Decimal("0.70"),
        "unrepresentative": Decimal("0.20"),
        "unknown": Decimal("0.50"),
    }


def test_seeded_universe_has_reviewed_representativeness_projection(db_session):
    seed_confirmed_managers(db_session)
    db_session.flush()

    managers = (
        db_session.query(InstitutionManager)
        .filter(InstitutionManager.cik.in_([entry["cik"] for entry in json.loads(SEED_PATH.read_text())]))
        .all()
    )
    assert len(managers) >= 80
    assert all(
        manager.representativeness_policy_version == REPRESENTATIVENESS_POLICY_VERSION
        for manager in managers
    )
    assert all(manager.representativeness_reviewed_at is not None for manager in managers)
    assert all(manager.representativeness_reviewer == "valuepilot-po-review-2026-07-20" for manager in managers)
    assert all(manager.representativeness_rationale for manager in managers)
    assert {manager.thirteenf_representativeness for manager in managers} == {
        "faithful",
        "partial",
        "unrepresentative",
    }

    reviews = (
        db_session.query(InstitutionManagerRepresentativenessReview)
        .filter(
            InstitutionManagerRepresentativenessReview.manager_id.in_(
                [manager.id for manager in managers]
            )
        )
        .all()
    )
    assert len(reviews) == len(managers)
    review_by_manager = {review.manager_id: review for review in reviews}
    for manager in managers:
        review = review_by_manager[manager.id]
        assert review.classification == manager.thirteenf_representativeness
        assert review.policy_version == manager.representativeness_policy_version
        assert review.reviewer == manager.representativeness_reviewer
        assert review.effective_at == manager.representativeness_reviewed_at
        assert review.rationale == manager.representativeness_rationale

    # One immutable decision per manager+policy version: startup re-seeding is
    # idempotent and never rewrites history into duplicate events.
    seed_confirmed_managers(db_session)
    db_session.flush()
    assert (
        db_session.query(InstitutionManagerRepresentativenessReview)
        .filter(
            InstitutionManagerRepresentativenessReview.manager_id.in_(
                [manager.id for manager in managers]
            )
        )
        .count()
        == len(managers)
    )


def test_unreviewed_manager_resolves_unknown_without_silent_penalty_rollout():
    manager = InstitutionManager(
        canonical_name="Unreviewed",
        legal_name="Unreviewed",
        manager_type="long_term_fundamental",
        style_primary="unknown",
        capital_structure="unknown",
    )
    resolution = resolve_manager_representativeness(manager)

    assert resolution.classification == "unknown"
    assert resolution.policy_version is None
    assert resolution.factor == Decimal("1.00")
    assert resolution.scoring_applied is False
    assert resolution.source == "unreviewed_compatibility"


def test_reviewed_projection_applies_versioned_factor():
    manager = InstitutionManager(
        canonical_name="Reviewed macro",
        legal_name="Reviewed macro",
        manager_type="multi_strategy",
        style_primary="multi_strategy_macro",
        capital_structure="standard_lp",
        thirteenf_representativeness="partial",
        representativeness_policy_version=REPRESENTATIVENESS_POLICY_VERSION,
        representativeness_reviewer="human-reviewer",
        representativeness_reviewed_at=datetime.now(timezone.utc),
        representativeness_rationale="Only the long US-listed equity sleeve is visible.",
    )
    resolution = resolve_manager_representativeness(manager)

    assert resolution.classification == "partial"
    assert resolution.factor == Decimal("0.70")
    assert resolution.scoring_applied is True
    assert resolution.source == "reviewed_projection"
    assert resolution.reviewed_at == manager.representativeness_reviewed_at
