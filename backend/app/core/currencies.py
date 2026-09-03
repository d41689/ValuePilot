from __future__ import annotations

from typing import Any


# Deterministic snapshot of the ISO 4217 Maintenance Agency's List One
# (current currency, fund, and precious-metal codes), retrieved from SIX on
# 2026-09-03. Runtime behavior must not depend on network or host locale data.
# Source: https://www.six-group.com/dam/download/financial-information/data-center/iso-currrency/lists/list-one.xml
ISO_4217_REGISTRY_VERSION = "six-list-one-2026-09-03"
ISO_4217_ACTIVE_CODES = frozenset(
    """
    AED AFN ALL AMD AOA ARS AUD AWG AZN BAM BBD BDT BHD BIF BMD BND BOB BOV
    BRL BSD BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUP
    CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF
    GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR
    KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT
    MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN
    PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE
    SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX
    USD USN UYI UYU UYW UZS VED VES VND VUV WST XAD XAF XAG XAU XBA XBB XBC
    XBD XCD XCG XDR XOF XPD XPF XPT XSU XTS XUA XXX YER ZAR ZMW ZWG
    """.split()
)
_NON_MONETARY_SPECIAL_PURPOSE_CODES = frozenset({"XTS", "XXX"})


def normalize_iso4217_currency(value: Any) -> str | None:
    """Return a current monetary ISO 4217 code or fail closed with ``None``.

    ISO reserves XTS for testing and XXX for transactions with no currency;
    neither can authorize price or valuation arithmetic.
    """

    normalized = str(value or "").strip().upper()
    if normalized in _NON_MONETARY_SPECIAL_PURPOSE_CODES:
        return None
    return normalized if normalized in ISO_4217_ACTIVE_CODES else None
