from scripts.audit_metric_taxonomy_coverage import build_taxonomy_matcher, classify_metric_key


def test_taxonomy_matcher_covers_static_and_dynamic_keys():
    matcher = build_taxonomy_matcher()

    assert classify_metric_key("is.net_income", matcher).covered is True
    assert classify_metric_key("mkt.price", matcher).covered is True
    assert classify_metric_key("rates.sales.cagr_10y", matcher).covered is True
    assert classify_metric_key("rates.cash_flow.cagr_est", matcher).covered is True
    assert classify_metric_key("owners_earnings_per_share", matcher).covered is True
    assert classify_metric_key("owners_earnings_per_share_normalized", matcher).covered is True


def test_taxonomy_matcher_excludes_evidence_only_and_legacy_keys():
    matcher = build_taxonomy_matcher()

    commentary = classify_metric_key("analyst.commentary", matcher)
    legacy = classify_metric_key("earnings_per_share", matcher)

    assert commentary.covered is False
    assert commentary.reason == "not_in_taxonomy_v1"

    assert legacy.covered is False
    assert legacy.reason == "not_in_taxonomy_v1"
