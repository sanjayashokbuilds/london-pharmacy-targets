import pandas as pd
import pytest

from targets.build import build
from targets.classify import norm_name, segment
from targets.columns import ColumnError, detect_columns

HEADERS = ["YEAR_MONTH", "CONTRACTOR_CODE", "CONTRACTOR_NAME", "ADDRESS_1", "ADDRESS_2", "POST_CODE",
           "ICB_CODE", "ICB_NAME", "HWB_NAME", "NUMBER_OF_ITEMS", "NUMBER_OF_ITEMS_EPS"]


def test_detects_standard_columns():
    c = detect_columns(HEADERS)
    assert c["code"] == "CONTRACTOR_CODE"
    assert c["name"] == "CONTRACTOR_NAME"
    assert c["items"] == "NUMBER_OF_ITEMS"  # preferred over the EPS sub-count
    assert c["icb"] == "ICB_NAME"
    assert c["address"] == ["ADDRESS_1", "ADDRESS_2"]


def test_ambiguous_items_column_stops_with_message():
    with pytest.raises(ColumnError) as e:
        detect_columns(["CONTRACTOR_CODE", "CONTRACTOR_NAME", "POST_CODE", "ITEMS_PAPER", "ITEMS_EPS"])
    assert "--items-col" in str(e.value)


def test_override_resolves_ambiguity():
    c = detect_columns(["CONTRACTOR_CODE", "CONTRACTOR_NAME", "POST_CODE", "ITEMS_PAPER", "ITEMS_EPS"],
                       {"items": "ITEMS_EPS"})
    assert c["items"] == "ITEMS_EPS"


def test_name_normalising_groups_same_owner():
    assert norm_name("J.R. Smith (Chemists) Limited t/a Smiths") == norm_name("J R SMITH CHEMISTS LTD")
    assert norm_name("A & B Pharmacy Ltd") == "A AND B PHARMACY"
    assert norm_name("Allen's Pharmacy") == "ALLENS PHARMACY"


def test_segments():
    assert [segment(n) for n in (1, 3, 10, 400)] == ["single", "small group", "mid group", "large multiple"]


def _fake_month(tmp_path, month, rows):
    df = pd.DataFrame(rows, columns=["CONTRACTOR_CODE", "CONTRACTOR_NAME", "ADDRESS_1", "POST_CODE",
                                     "ICB_NAME", "NUMBER_OF_ITEMS"])
    path = tmp_path / f"dispensing_data_{month}.csv"
    df.to_csv(path, index=False)
    return month, path


def test_end_to_end(tmp_path):
    big_chain = [(f"FB{i:03d}", "Big Chain Pharmacy Ltd", "1 High St", "M1 1AA", "NHS Greater Manchester ICB", "9000")
                 for i in range(60)]
    big_chain.append(("FL001", "BIG CHAIN PHARMACY LIMITED", "2 Strand", "WC2N 5AA", "NHS North Central London ICB", "9999"))
    rows = big_chain + [
        ("FA001", "Patel Chemists Ltd", "10 Mile End Rd", "E1 4AA", "NHS North East London ICB", "6,000"),
        ("FA002", "Patel Chemists Limited", "5 Bow Rd", "E3 2AA", "NHS North East London ICB", "5000"),
        ("FC001", "Corner Pharmacy", "1 Corner", "SW1A 1AA", "NHS North West London ICB", "8000"),
        ("FS001", "Signature Pharmacy Ltd", "3 Road", "N1 1AA", "NHS North Central London ICB", "20000"),
        ("FX001", "Leeds Chemist", "1 Leeds Rd", "LS1 1AA", "NHS West Yorkshire ICB", "50000"),
    ]
    june = _fake_month(tmp_path, "202606", rows)
    may_rows = [r[:5] + ("4000",) if r[0] == "FA001" else r for r in rows]
    may = _fake_month(tmp_path, "202605", may_rows)

    owners, pharmacies, _ = build([june, may])
    by = owners.set_index("name_norm")

    assert "LEEDS CHEMIST" not in by.index                     # not London
    assert by.loc["PATEL CHEMISTS", "london_branches"] == 2    # two spellings, one owner
    assert by.loc["PATEL CHEMISTS", "london_avg_monthly_items"] == 10000  # (6000+4000)/2 + 5000
    assert by.loc["PATEL CHEMISTS", "segment"] == "small group"
    assert by.loc["BIG CHAIN PHARMACY", "segment"] == "large multiple"
    assert bool(by.loc["SIGNATURE PHARMACY", "possible_existing_customer"])
    assert by.loc["CORNER PHARMACY", "segment"] == "single"


LONG_COLS = ["YEAR_MONTH", "ICB_NAME", "PHARMACY_ACCOUNT_TYPE", "CONTRACTOR_CODE", "CONTRACTOR_NAME",
             "ADDRESS_1", "POSTCODE", "CONTENT_GROUP", "CONTENT", "VALUE"]


def _long_rows(code, name, icb, items, kind="Community Pharmacy"):
    base = ["202606", icb, kind, code, name, "1 Rd", "E1 1AA"]
    return [base + ["Forms", "Number of forms", str(items // 2)],
            base + ["Items", "Number of items", f"{items:,}"],
            base + ["Advanced services", "Pharmacy First consultations", "40"]]


def test_long_format_picks_items_and_drops_appliance(tmp_path):
    rows = (_long_rows("FA1", "Patel Chemists Ltd", "NHS North East London ICB", 6000)
            + _long_rows("FA2", "Patel Chemists Ltd", "NHS North East London ICB", 4000)
            + _long_rows("AP1", "Stoma Supplies Ltd", "NHS North East London ICB", 9000, "Appliance Contractor"))
    path = tmp_path / "dispensing_data_202606.csv"
    pd.DataFrame(rows, columns=LONG_COLS).to_csv(path, index=False)

    owners, _, _ = build([("202606", path)])
    by = owners.set_index("name_norm")
    assert by.loc["PATEL CHEMISTS", "london_avg_monthly_items"] == 10000
    assert "STOMA SUPPLIES" not in by.index


def test_long_format_ambiguous_lists_measures(tmp_path):
    base = ["202606", "NHS North East London ICB", "Community Pharmacy", "FA1", "X Ltd", "1 Rd", "E1 1AA"]
    rows = [base + ["Items", "Items dispensed - EPS", "10"], base + ["Items", "Items dispensed - paper", "5"]]
    path = tmp_path / "dispensing_data_202606.csv"
    pd.DataFrame(rows, columns=LONG_COLS).to_csv(path, index=False)
    with pytest.raises(ColumnError) as e:
        build([("202606", path)])
    assert "Items dispensed - EPS: 10" in str(e.value)
    owners, _, _ = build([("202606", path)], items_content="Items dispensed - EPS")
    assert owners.iloc[0]["london_avg_monthly_items"] == 10


def test_real_nhs_labels_pick_plain_items(tmp_path):
    base = ["202606", "NHS North East London ICB", "Community Pharmacy", "FA1", "X Ltd", "1 Rd", "E1 1AA"]
    rows = [base + ["Prescription Count", "Items", "900"],
            base + ["Prescription Count", "Items processed via Electronic Prescription Service (EPS)", "850"],
            base + ["Prescription Count", "Forms", "400"]]
    path = tmp_path / "dispensing_data_202606.csv"
    pd.DataFrame(rows, columns=LONG_COLS).to_csv(path, index=False)
    owners, _, _ = build([("202606", path)])
    assert owners.iloc[0]["london_avg_monthly_items"] == 900


def test_spacing_and_apostrophes_group_together(tmp_path):
    rows = [("FG1", "Greenlight Pharmacy", "a", "E1 1AA", "NHS North East London ICB", "100"),
            ("FG2", "Green Light Pharmacy", "a", "E2 1AA", "NHS North East London ICB", "100"),
            ("FL1", "Allen's Pharmacy", "a", "E3 1AA", "NHS North East London ICB", "100"),
            ("FL2", "Allens Pharmacy", "a", "E4 1AA", "NHS North East London ICB", "100"),
            ("FW1", "www.quick-meds.com", "a", "E5 1AA", "NHS North East London ICB", "500")]
    owners, _, _ = build([_fake_month(tmp_path, "202606", rows)])
    assert len(owners) == 3
    assert owners["london_branches"].tolist().count(2) == 2
    assert owners.loc[owners["owner_name"] == "www.quick-meds.com", "likely_online_or_hub"].item()


class _FakeCH:
    def __init__(self, items):
        self.items = items


def test_companies_house_match_rules(monkeypatch):
    from targets.companies_house import CompaniesHouse
    ch = CompaniesHouse("k", pause=0)
    def fake(items):
        monkeypatch.setattr(ch, "_get", lambda path, params=None: {"items": items})
    fake([{"title": "SINCLAIRS LIMITED", "company_status": "dissolved"}])
    assert ch.match("SINCLAIRS")[0] is None                      # dissolved twin ignored
    fake([{"title": "WELLCARE PHARMACY (LONDON) LIMITED", "company_status": "active"}])
    assert ch.match("WELLCARE PHARMACY")[1] == "prefix"
    fake([{"title": "WELLCARE PHARMACY (LONDON) LIMITED", "company_status": "active"},
          {"title": "WELLCARE PHARMACY KENT LIMITED", "company_status": "active"}])
    assert ch.match("WELLCARE PHARMACY")[0] is None              # two candidates: don't guess
