import json
from datetime import date
from pathlib import Path

import yaml

from app.services.mapping_spec import MappingSpec


SPEC_PATH = Path("docs/metric_facts_mapping_spec.yml")
TAXONOMY_PATH = Path("docs/value_line_field_taxonomy.yml")
FIXTURE_JSON = Path("tests/fixtures/value_line/axs_v1.expected.json")


def load_taxonomy() -> dict:
    with TAXONOMY_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_page_json() -> dict:
    with FIXTURE_JSON.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def test_value_line_taxonomy_covers_core_sections_and_mappings():
    taxonomy = load_taxonomy()

    assert taxonomy["page_json_sections"]["header"]["fact_nature"] == "snapshot"
    assert taxonomy["page_json_sections"]["ratings"]["fact_nature"] == "opinion"
    assert taxonomy["page_json_sections"]["target_price_18m"]["fact_nature"] == "opinion"
    assert taxonomy["page_json_sections"]["annual_financials"]["fact_nature"] == "mixed"
    assert taxonomy["page_json_sections"]["earnings_per_share"]["fact_nature"] == "mixed"
    assert taxonomy["page_json_sections"]["total_return"]["fact_nature"] == "snapshot"
    assert taxonomy["page_json_sections"]["narrative"]["fact_nature"] == "opinion"

    mapping_semantics = taxonomy["mapping_semantics"]
    assert mapping_semantics["mkt.price.as_of"]["fact_nature"] == "snapshot"
    assert mapping_semantics["rating.timeliness.as_of"]["fact_nature"] == "opinion"
    assert mapping_semantics["target.price_18m.mid"]["fact_nature"] == "opinion"
    assert mapping_semantics["analyst.commentary.as_of"]["fact_nature"] == "opinion"
    assert mapping_semantics["analyst.commentary.as_of"]["storage_role"] == "evidence_only"
    assert mapping_semantics["company.business_description.as_of"]["storage_role"] == "evidence_only"
    assert mapping_semantics["rating.timeliness.event"]["storage_role"] == "evidence_only"
    assert mapping_semantics["rating.safety.event"]["storage_role"] == "evidence_only"
    assert mapping_semantics["rating.technical.event"]["storage_role"] == "evidence_only"
    assert mapping_semantics["is.net_income.fy"]["fact_nature_rule"] == "context_or_annual_meta"
    assert mapping_semantics["per_share.eps.q"]["fact_nature_rule"] == "context_only"

    evidence_reads = taxonomy["evidence_reads"]
    assert evidence_reads["company.business_description.as_of"] == {
        "source": "metric_extractions",
        "metric_key": "company.business_description",
        "period_type": "AS_OF",
        "extraction_field_key": "business_description",
        "value_mode": "raw_text",
        "period_end_source": "document_report_date",
    }
    assert evidence_reads["analyst.commentary.as_of"]["extraction_field_key"] == "analyst_commentary"
    assert evidence_reads["rating.timeliness.event"]["value_mode"] == "rating_event"
    assert evidence_reads["rating.timeliness.event"]["metric_key"] == "rating.timeliness_change"
    assert evidence_reads["rating.safety.event"]["value_mode"] == "rating_event"
    assert evidence_reads["rating.technical.event"]["value_mode"] == "rating_event"


def test_mapping_spec_uses_taxonomy_semantics_for_generated_facts():
    spec = MappingSpec.load(SPEC_PATH)
    page_json = load_page_json()

    facts, _, _ = spec.generate_facts(page_json)
    by_key = {(f["metric_key"], f.get("period_type"), f.get("period_end_date")): f for f in facts}

    price = by_key[("mkt.price", "AS_OF", date(2026, 1, 9))]
    assert price["value_json"]["fact_nature"] == "snapshot"

    timeliness = by_key[("rating.timeliness", "AS_OF", date(2026, 1, 9))]
    assert timeliness["value_json"]["fact_nature"] == "opinion"
    assert ("rating.timeliness_change", "EVENT", date(2026, 1, 9)) not in by_key
    assert ("rating.safety_change", "EVENT", date(2026, 1, 9)) not in by_key
    assert ("rating.technical_change", "EVENT", date(2026, 1, 9)) not in by_key

    target_mid = by_key[("target.price_18m.mid", "TARGET_HORIZON", date(2026, 1, 9))]
    assert target_mid["value_json"]["fact_nature"] == "opinion"

    assert ("analyst.commentary", "AS_OF", date(2026, 1, 9)) not in by_key

    net_income_actual = by_key[("is.net_income", "FY", date(2024, 12, 31))]
    assert net_income_actual["value_json"]["fact_nature"] == "actual"

    net_income_estimate = by_key[("is.net_income", "FY", date(2025, 12, 31))]
    assert net_income_estimate["value_json"]["fact_nature"] == "estimate"
