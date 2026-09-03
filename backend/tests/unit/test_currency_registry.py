from app.core.currencies import (
    ISO_4217_ACTIVE_CODES,
    ISO_4217_REGISTRY_VERSION,
    normalize_iso4217_currency,
)


def test_current_iso4217_registry_normalizes_known_monetary_codes():
    assert ISO_4217_REGISTRY_VERSION == "six-list-one-2026-09-03"
    assert {"USD", "CAD", "DKK", "EUR", "TWD", "XAU"} <= ISO_4217_ACTIVE_CODES
    assert normalize_iso4217_currency(" cad ") == "CAD"
    assert normalize_iso4217_currency("usd") == "USD"


def test_currency_normalization_rejects_unknown_historic_and_non_monetary_codes():
    assert normalize_iso4217_currency("ZZZ") is None
    assert normalize_iso4217_currency("BGN") is None
    assert normalize_iso4217_currency("XTS") is None
    assert normalize_iso4217_currency("XXX") is None
