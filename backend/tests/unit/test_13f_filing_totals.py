"""The bulk ingest path must write the filing's value totals.

`compute_portfolio_weight` divides a holding's value by
`filing.computed_total_value_thousands or filing.reported_total_value_thousands`.
When both are NULL it returns `None` — no weight, no caveat, silently.

The legacy per-filing `ingest_filing_holdings` wrote both. The modern
ParseRun-backed `ingest_holdings` job — the one T4 pointed the CLI at, and the
one `quarterly_pipeline` uses — wrote neither. So an entirely automated database
produced Oracle's Lens signals in which:

    distinctive_concentration_factor   avg 0.000   (dev, manual path: 0.527)
    distinctive_total                  avg 0.000   (dev: 0.762, max 21.12)
    conviction_position_importance     avg 3.14, max 10   (dev: 11.42, max 30)
    signals with a distinctiveness score > 0:  0 of 1282  (dev: 1965 of 2135)

Distinctiveness is a column on the Watchlist. It was identically zero, and
conviction was systematically understated, with every job green.

This is the third instance of one pattern: the manual path populates something
the automated path does not (see also `enrich_metadata` convergence, and
`accepted_at`, whose fix note lives in `apply_primary_doc_metadata`'s docstring).
"""
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app.models.institutions import Filing13F, InstitutionManager
from app.services.thirteenf_filing_detail import apply_primary_doc_metadata


@pytest.fixture
def manager(db_session):
    m = InstitutionManager(
        cik="0001067983", legal_name="Berkshire Hathaway Inc",
        name_normalized="berkshire-totals", match_status="confirmed",
    )
    db_session.add(m)
    db_session.flush()
    return m


@pytest.fixture
def filing(db_session, manager):
    f = Filing13F(
        manager_id=manager.id, accession_no="0001067983-26-000100",
        form_type="13F-HR", period_of_report=date(2025, 12, 31),
        report_quarter="2025-Q4", parse_status="pending",
        filed_at=datetime(2026, 2, 17, tzinfo=timezone.utc),
    )
    db_session.add(f)
    db_session.flush()
    return f


def _summary(**kw):
    base = dict(
        form_spec_version=None, xml_schema_version=None, report_type="13F HOLDINGS REPORT",
        has_confidential_treatment=False, accepted_at=None,
        other_managers_reporting=None, other_managers_included=None,
        is_amendment=False, amendment_type=None,
        table_entry_total=90, table_value_total=263_095_703_570,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_primary_doc_metadata_records_the_filers_own_totals(db_session, filing):
    """Without these, `compute_portfolio_weight` has no denominator."""
    apply_primary_doc_metadata(db_session, filing, _summary())

    assert filing.reported_total_value_thousands == 263_095_703_570
    assert filing.holdings_count == 90


def test_a_missing_total_never_erases_a_known_one(db_session, filing):
    """Same merge rule as `accepted_at`: a re-parse that reads nothing must not
    wipe what an earlier parse established."""
    filing.reported_total_value_thousands = 263_095_703_570
    filing.holdings_count = 90
    db_session.flush()

    apply_primary_doc_metadata(
        db_session, filing, _summary(table_value_total=None, table_entry_total=None)
    )

    assert filing.reported_total_value_thousands == 263_095_703_570
    assert filing.holdings_count == 90


def test_a_corrected_total_wins_over_a_stale_one(db_session, filing):
    """A non-NULL re-parse is authoritative — a parser fix must propagate."""
    filing.reported_total_value_thousands = 1
    db_session.flush()

    apply_primary_doc_metadata(db_session, filing, _summary(table_value_total=999))

    assert filing.reported_total_value_thousands == 999


def test_the_weight_denominator_exists_after_metadata_is_applied(db_session, filing):
    """The property the whole product depends on, stated once.

    `compute_portfolio_weight` reads
    `computed_total_value_thousands or reported_total_value_thousands`.
    """
    apply_primary_doc_metadata(db_session, filing, _summary())

    denominator = (
        filing.computed_total_value_thousands or filing.reported_total_value_thousands
    )
    assert denominator, "no denominator => portfolio_weight is None => Lens scores 0"
