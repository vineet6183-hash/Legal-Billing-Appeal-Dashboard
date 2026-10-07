import io
import os
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import billing as B  # noqa: E402


def test_sample_data_shape_and_outcome_split():
    df = B.sample_data()
    assert 108 <= len(df) <= 168
    assert df["portal"].nunique() == 18
    # every reduced dollar lands in exactly one outcome segment
    seg = df[["seg_rec", "seg_pend", "seg_den", "seg_none"]].sum(axis=1)
    assert (seg - df["red"]).abs().max() < 1e-6
    assert set(df["status"]) <= set(B.STATUSES)


@pytest.mark.parametrize("raw,app,rec,expected", [
    ("Approved", 100, 100, "Recovered"),
    ("Approved", 100, 40, "Partial"),     # label contradicted by amounts
    ("Recovered", 100, 0, "Denied"),
    ("Under review", 100, 0, "Pending"),
    ("Rejected", 100, 0, "Denied"),
    ("Accepted reduction", 0, 0, "Not appealed"),
    ("", 0, 0, "Not appealed"),
    ("", 100, 0, "Pending"),
    ("", 100, 60, "Partial"),
    ("", 100, 100, "Recovered"),
])
def test_classify_status(raw, app, rec, expected):
    assert B.classify_status(raw, app, rec) == expected


def test_import_pasted_excel_rows_with_loose_headers():
    text = (
        "Inv #\tInvoice Date\tTimekeeper Name\tBilled Amount ($)\tWrite-down\tReduction %\tAmount Appealed\t"
        "Recovered\tAppeal Status\tE-Billing Portal\n"
        "INV-1\t01/15/2026\tJane Doe\t$12,500.00\t$950.00\t7.6%\t950\t600\tPartial\tTymetrix 360\n"
        "INV-2\t2026-02-03\tJohn Roe\t8,000\t400\t5%\t\t\t\tCounselLink\n"
        "\t\t\t\t\t\t\t\t\t\n"
        "INV-3\t46080\tJane Doe\tn/a\t1\t\t\t\t\t\n"
    )
    res = B.import_text(text)
    assert "error" not in res, res
    df = res["df"]
    assert list(df["inv"]) == ["INV-1", "INV-2"]
    assert res["skipped"] == 1
    assert df.loc[0, "billed"] == 12500 and df.loc[0, "red"] == 950
    assert df.loc[0, "status"] == "Partial"
    assert df.loc[1, "status"] == "Not appealed"
    assert df.loc[0, "date"] == pd.Timestamp(2026, 1, 15)
    assert df.loc[1, "portal"] == "CounselLink"
    assert res["mapping"]["red"] == "Write-down"


def test_import_reports_missing_columns():
    res = B.import_text("Invoice Number,Amount\nA,1\n")
    assert "Billed Amount" in res["error"] and "Reduction Amount" in res["error"]


def test_excel_round_trip():
    df = B.sample_data()
    xlsx = B.export_excel(df)
    res = B.import_file("tracker.xlsx", xlsx)
    assert "error" not in res, res
    back = res["df"]
    assert len(back) == len(df)
    assert back["red"].sum() == pytest.approx(df["red"].sum())
    assert (back["status"].values == df["status"].values).all()


def test_csv_round_trip_and_template():
    df = B.sample_data()
    csv_text = B.export_frame(df).to_csv(index=False)
    res = B.import_file("tracker.csv", csv_text.encode())
    assert len(res["df"]) == len(df)
    assert "error" not in B.import_text(B.template_csv())


def test_group_totals_folds_other():
    df = B.sample_data()
    g = B.group_totals(df, "reason", top=4)
    assert len(g) == 4 and g.iloc[-1]["label"].startswith("Other (")
    assert g["red"].sum() == pytest.approx(df["red"].sum())


def test_app_renders_and_filters():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=60).run()
    assert not at.exception, at.exception
    assert at.title[0].value == "Legal Billing Appeal Dashboard"
    total = len(at.session_state["data"])
    assert f"Showing {total} of {total} invoices" in " ".join(m.value for m in at.markdown)

    at.selectbox(key="f_tk").select("Lena Fischer").run()
    assert not at.exception, at.exception
    shown = " ".join(m.value for m in at.markdown)
    assert "Timekeeper: Lena Fischer" in shown

    at.selectbox(key="f_period").select("m3").run()
    at.radio(key="group_dim").set_value("portal").run()
    assert not at.exception, at.exception

    at.button[-1].click()  # any button; app must stay stable
    at.run()
    assert not at.exception, at.exception


def test_app_loads_pasted_rows():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=60).run()
    at.text_area(key="paste").input(
        "Invoice Number,Billed Amount,Reduction Amount\nA-1,1000,100\nA-2,2000,0\n").run()
    load = next(b for b in at.button if b.label == "Load pasted rows")
    load.click().run()
    assert not at.exception, at.exception
    assert at.session_state["source"] == "yours"
    assert len(at.session_state["data"]) == 2
