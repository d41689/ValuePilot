import json
import pytest
from datetime import date
from unittest.mock import patch, MagicMock

from app.models.institutions import InstitutionManager
from app.services.thirteenf_admin_dashboard import (
    build_manager_backfill_preview,
    _execute_job,
)


@pytest.fixture
def mock_edgar_client(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.SEC_CONTACT_EMAIL", "test@example.com")
    with patch("app.edgar.client.EdgarClient") as mock:
        yield mock


def test_build_manager_backfill_preview_value_unit_risk(db_session, mock_edgar_client):
    manager = InstitutionManager(
        canonical_name="Test Manager",
        legal_name="Test Manager LLC",
        cik="0000123456",
        status="active",
        match_status="confirmed"
    )
    db_session.add(manager)
    db_session.commit()

    # Mock submissions JSON response
    mock_submissions = {
        "cik": "123456",
        "name": "Test",
        "filings": {
            "recent": {
                "accessionNumber": ["0000000000-22-000001", "0000000000-23-000002"],
                "form": ["13F-HR", "13F-HR"],
                "filingDate": ["2022-11-14", "2023-02-14"],
                "reportDate": ["2022-09-30", "2022-12-31"]
            }
        }
    }
    
    instance = mock_edgar_client.return_value.__enter__.return_value
    instance.get.return_value = json.dumps(mock_submissions).encode("utf-8")

    # Preview with start_quarter before 2023
    preview = build_manager_backfill_preview(db_session, manager.id, start_quarter="2022-Q3")
    
    assert preview["value_unit_risk_warning"] is True
    assert preview["estimated_filing_count"] == 2
    # 1 for submissions + 2 per filing = 5
    assert preview["estimated_request_count"] == 5
    assert preview["estimated_rate_limit_wait_seconds"] == 0.5


def test_build_manager_backfill_preview_warns_for_pre_2023_range_even_without_filings(db_session, mock_edgar_client):
    manager = InstitutionManager(
        canonical_name="No Filings Manager",
        legal_name="No Filings Manager LLC",
        cik="0000123460",
        status="active",
        match_status="confirmed",
    )
    db_session.add(manager)
    db_session.commit()

    mock_submissions = {
        "cik": "123460",
        "name": "No Filings",
        "filings": {
            "recent": {
                "accessionNumber": [],
                "form": [],
                "filingDate": [],
                "reportDate": [],
            }
        },
    }
    instance = mock_edgar_client.return_value.__enter__.return_value
    instance.get.return_value = json.dumps(mock_submissions).encode("utf-8")

    preview = build_manager_backfill_preview(db_session, manager.id, start_quarter="2022-Q4")

    assert preview["estimated_filing_count"] == 0
    assert preview["value_unit_risk_warning"] is True


def test_build_manager_backfill_preview_surfaces_submission_fetch_failure(db_session, mock_edgar_client):
    manager = InstitutionManager(
        canonical_name="Fetch Failure Manager",
        legal_name="Fetch Failure Manager LLC",
        cik="0000123461",
        status="active",
        match_status="confirmed",
    )
    db_session.add(manager)
    db_session.commit()

    instance = mock_edgar_client.return_value.__enter__.return_value
    instance.get.side_effect = RuntimeError("SEC unavailable")

    with pytest.raises(ValueError, match="Unable to fetch SEC submissions"):
        build_manager_backfill_preview(db_session, manager.id, start_quarter="2023-Q1")


def test_build_manager_backfill_preview_no_risk(db_session, mock_edgar_client):
    manager = InstitutionManager(
        canonical_name="Test Manager 2",
        legal_name="Test Manager 2 LLC",
        cik="0000123457",
        status="active",
        match_status="confirmed"
    )
    db_session.add(manager)
    db_session.commit()

    # Mock submissions JSON response
    mock_submissions = {
        "cik": "123457",
        "name": "Test 2",
        "filings": {
            "recent": {
                "accessionNumber": ["0000000000-23-000003"],
                "form": ["13F-HR"],
                "filingDate": ["2023-05-15"],
                "reportDate": ["2023-03-31"]
            }
        }
    }
    
    instance = mock_edgar_client.return_value.__enter__.return_value
    instance.get.return_value = json.dumps(mock_submissions).encode("utf-8")

    preview = build_manager_backfill_preview(db_session, manager.id, start_quarter="2023-Q1")
    
    assert preview["value_unit_risk_warning"] is False
    assert preview["estimated_filing_count"] == 1
    assert preview["estimated_request_count"] == 3


@patch("app.services.thirteenf_admin_dashboard._execute_pipeline_stage_job")
def test_sync_manager_backfill_execution(mock_stage, db_session, mock_edgar_client):
    manager = InstitutionManager(
        canonical_name="Test Manager 3",
        legal_name="Test Manager 3 LLC",
        cik="0000123458",
        status="active",
        match_status="confirmed"
    )
    db_session.add(manager)
    db_session.commit()

    mock_submissions = {
        "cik": "123458",
        "name": "Test 3",
        "filings": {
            "recent": {
                "accessionNumber": ["0000000000-23-000004"],
                "form": ["13F-HR"],
                "filingDate": ["2023-08-14"],
                "reportDate": ["2023-06-30"]
            }
        }
    }
    
    instance = mock_edgar_client.return_value.__enter__.return_value
    instance.get.return_value = json.dumps(mock_submissions).encode("utf-8")

    mock_stage.return_value = {"stage": {"status": "succeeded"}}

    result = _execute_job(
        db_session, 
        job_type="sync_manager_backfill", 
        payload={"manager_id": manager.id, "start_quarter": "2023-Q2"}
    )

    assert result["status"] == "succeeded"
    assert result["filings_inserted"] == 1
    assert result["filings_failed"] == 0
    mock_stage.assert_called_once()


def test_sync_manager_backfill_stage_payload_can_ingest_accession(db_session, mock_edgar_client, monkeypatch):
    manager = InstitutionManager(
        canonical_name="Payload Manager",
        legal_name="Payload Manager LLC",
        cik="0000123459",
        status="active",
        match_status="confirmed",
    )
    db_session.add(manager)
    db_session.commit()

    mock_submissions = {
        "cik": "123459",
        "name": "Payload Manager",
        "filings": {
            "recent": {
                "accessionNumber": ["0000000000-23-000005"],
                "form": ["13F-HR/A"],
                "filingDate": ["2023-11-14"],
                "reportDate": ["2023-09-30"],
            }
        },
    }
    instance = mock_edgar_client.return_value.__enter__.return_value
    instance.get.return_value = json.dumps(mock_submissions).encode("utf-8")

    captured_payloads = []

    def fake_ingest(session, payload):
        captured_payloads.append(payload)
        assert payload["manager_id"] == manager.id
        assert payload["cik"] == manager.cik
        assert payload["form_type"] == "13F-HR/A"
        assert payload["accession_no"] == "0000000000-23-000005"
        return {
            "filing_id": 123,
            "accession_number": payload["accession_no"],
            "report_quarter": "2023-Q3",
            "status": "succeeded",
        }

    monkeypatch.setattr(
        "app.services.thirteenf_filing_detail.ingest_accession_filing_detail",
        fake_ingest,
    )

    result = _execute_job(
        db_session,
        job_type="sync_manager_backfill",
        payload={"manager_id": manager.id, "start_quarter": "2023-Q3"},
    )

    assert result["status"] == "succeeded"
    assert result["filings_inserted"] == 1
    assert len(captured_payloads) == 1
