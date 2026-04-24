"""Unit tests for 13F ingestion parsers."""
import textwrap
from datetime import date

import pytest

from app.edgar.parsers.form_idx import parse_form_idx, quarter_to_year_qtr, form_idx_url
from app.edgar.parsers.infotable import parse_infotable, compute_total_value, _fingerprint
from app.dataroma.parsers.managers import parse_managers
from app.dataroma.parsers.holdings import parse_holdings


# ---------------------------------------------------------------------------
# form_idx
# ---------------------------------------------------------------------------

FORM_IDX_SAMPLE = textwrap.dedent("""\
    Description:           Master Index of EDGAR Dissemination Feed by Form Type
    Last Data Received:    March 31, 2024

    Form Type   Company Name                                                  CIK         Date Filed  File Name
    ------------------------------------------------------------------------------------------------------------------------
    13F-HR      BERKSHIRE HATHAWAY INC                                        1067983     2024-02-14  edgar/data/1067983/0001067983-24-000006.txt
    10-K        SOME OTHER CORP                                                9999999     2024-01-10  edgar/data/9999999/0009999999-24-000001.txt
    13F-HR/A    PAULSON & CO. INC.                                             1035055     2024-02-15  edgar/data/1035055/0001035055-24-000001.txt
""").encode()


def test_parse_form_idx_filters_13f():
    records = parse_form_idx(FORM_IDX_SAMPLE)
    assert len(records) == 2
    assert records[0].company_name == "BERKSHIRE HATHAWAY INC"
    assert records[0].form_type == "13F-HR"
    assert records[0].cik == "0001067983"
    assert records[0].filed_at == date(2024, 2, 14)
    assert records[0].accession_no == "0001067983-24-000006"
    assert records[1].form_type == "13F-HR/A"


def test_parse_form_idx_skips_non_13f():
    records = parse_form_idx(FORM_IDX_SAMPLE)
    ciks = {r.cik for r in records}
    assert "0009999999" not in ciks


def test_quarter_to_year_qtr():
    assert quarter_to_year_qtr("2025-Q1") == (2025, 1)
    assert quarter_to_year_qtr("2024-Q4") == (2024, 4)
    with pytest.raises(ValueError):
        quarter_to_year_qtr("2025Q1")


def test_form_idx_url():
    assert form_idx_url(2024, 1) == (
        "https://www.sec.gov/Archives/edgar/full-index/2024/QTR1/form.idx"
    )


# ---------------------------------------------------------------------------
# infotable
# ---------------------------------------------------------------------------

INFOTABLE_SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip>
    <value>8000000</value>
    <sshPrnamt>50000000</sshPrnamt>
    <sshPrnamtType>SH</sshPrnamtType>
    <putCall></putCall>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
      <Sole>50000000</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>
  <infoTable>
    <nameOfIssuer>MICROSOFT CORP</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>594918104</cusip>
    <value>3000000</value>
    <sshPrnamt>10000000</sshPrnamt>
    <sshPrnamtType>SH</sshPrnamtType>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
      <Sole>10000000</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>
</informationTable>"""


def test_parse_infotable_count():
    rows = parse_infotable(INFOTABLE_SAMPLE)
    assert len(rows) == 2


def test_parse_infotable_fields():
    rows = parse_infotable(INFOTABLE_SAMPLE)
    apple = rows[0]
    assert apple.cusip == "037833100"
    assert apple.issuer_name == "APPLE INC"
    assert apple.value_thousands == 8_000_000
    assert apple.shares == 50_000_000
    assert apple.share_type == "SH"
    assert apple.investment_discretion == "SOLE"
    assert apple.voting_sole == 50_000_000
    assert apple.voting_shared == 0
    assert apple.voting_none == 0


def test_parse_infotable_fingerprint_stable():
    rows1 = parse_infotable(INFOTABLE_SAMPLE)
    rows2 = parse_infotable(INFOTABLE_SAMPLE)
    assert rows1[0].row_fingerprint == rows2[0].row_fingerprint


def test_parse_infotable_fingerprint_differs():
    rows = parse_infotable(INFOTABLE_SAMPLE)
    assert rows[0].row_fingerprint != rows[1].row_fingerprint


def test_compute_total_value():
    rows = parse_infotable(INFOTABLE_SAMPLE)
    assert compute_total_value(rows) == 11_000_000


# ---------------------------------------------------------------------------
# Dataroma managers parser
# ---------------------------------------------------------------------------

MANAGERS_HTML = b"""
<html><body>
<table>
  <tr>
    <td><a href="/m/holdings.php?m=BRK">Berkshire Hathaway (Warren Buffett)</a></td>
  </tr>
  <tr>
    <td><a href="/m/holdings.php?m=GSAM">Goldman Sachs Asset Management</a></td>
  </tr>
  <tr>
    <td><a href="/m/holdings.php?m=BRK">Berkshire Hathaway duplicate</a></td>
  </tr>
  <tr>
    <td><a href="/other/page">Not a manager link</a></td>
  </tr>
</table>
</body></html>
"""


def test_parse_managers_basic():
    managers = parse_managers(MANAGERS_HTML)
    codes = [m.dataroma_code for m in managers]
    assert "BRK" in codes
    assert "GSAM" in codes


def test_parse_managers_dedup():
    managers = parse_managers(MANAGERS_HTML)
    codes = [m.dataroma_code for m in managers]
    assert codes.count("BRK") == 1


def test_parse_managers_excludes_non_manager_links():
    managers = parse_managers(MANAGERS_HTML)
    codes = [m.dataroma_code for m in managers]
    # 'Not a manager link' should not appear
    assert len(codes) == 2


# ---------------------------------------------------------------------------
# Dataroma holdings parser
# ---------------------------------------------------------------------------

HOLDINGS_HTML = b"""
<html><body>
<table>
  <tr><th>Stock</th><th>%</th></tr>
  <tr>
    <td class="stock"><a href="/m/stock.php?sym=AAPL">AAPL<span> - Apple Inc.</span></a></td>
    <td>10.5%</td>
  </tr>
  <tr>
    <td class="stock"><a href="/m/stock.php?sym=MSFT">MSFT<span> - Microsoft Corp</span></a></td>
    <td>8.2%</td>
  </tr>
  <tr>
    <td class="stock"><a href="/m/stock.php?sym=AAPL">AAPL<span> - Apple duplicate</span></a></td>
    <td>0.1%</td>
  </tr>
</table>
</body></html>
"""


def test_parse_holdings_basic():
    holdings = parse_holdings(HOLDINGS_HTML)
    tickers = [h.ticker for h in holdings]
    assert "AAPL" in tickers
    assert "MSFT" in tickers


def test_parse_holdings_dedup():
    holdings = parse_holdings(HOLDINGS_HTML)
    tickers = [h.ticker for h in holdings]
    assert tickers.count("AAPL") == 1


def test_parse_holdings_issuer_name():
    holdings = parse_holdings(HOLDINGS_HTML)
    aapl = next(h for h in holdings if h.ticker == "AAPL")
    assert aapl.issuer_name == "Apple Inc."
