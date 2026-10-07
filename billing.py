"""Data logic for the Legal Billing Appeal Dashboard.

Everything here is plain pandas so it can be tested without Streamlit:
importing a tracker (CSV / Excel / pasted rows), matching its column headers,
classifying appeal status, splitting each reduced dollar into an outcome, and
generating the illustrative sample data.
"""

from __future__ import annotations

import csv
import io
import math
import random
import re
from datetime import date, datetime, timedelta

import pandas as pd

NA = "Not given"

# Every reduced dollar lands in exactly one of these outcome segments.
SEGMENTS = [
    ("seg_rec", "Recovered", "#2a78d6"),
    ("seg_pend", "Appeal pending", "#1baf7a"),
    ("seg_den", "Denied on appeal", "#eb6834"),
    ("seg_none", "Not appealed", "#a4a9b1"),
]
RATE_COLOR = "#4a3aa7"
STATUSES = ["Recovered", "Partial", "Pending", "Denied", "Not appealed"]
DIMS = {
    "tk": "Timekeeper",
    "client": "Client",
    "portal": "Portal",
    "reason": "Reduction reason",
    "status": "Appeal status",
}

COLUMNS = [
    "inv", "date", "tk", "role", "client", "portal", "reason",
    "billed", "red", "app", "rec", "status", "pct",
    "seg_rec", "seg_pend", "seg_den", "seg_none",
]

# ---------------------------------------------------------------- status rules

_NOT_APPEALED = re.compile(r"not\s*appeal|no appeal|none|n/a|waiv|accept(ed)? reduction")
_PENDING = re.compile(r"pend|open|submit|await|review|progress")
_PARTIAL = re.compile(r"partial")
_DENIED = re.compile(r"den|reject|declin|upheld|lost")
_RECOVERED = re.compile(r"approv|recover|won|paid|grant|reinstat|success|full")


def classify_status(raw: str, app: float, rec: float) -> str:
    """Map a free-text status (or the amounts, when there is none) to one of STATUSES."""
    raw = (raw or "").strip().lower()
    st = ""
    if raw:
        if _NOT_APPEALED.search(raw):
            st = "Not appealed"
        elif _PENDING.search(raw):
            st = "Pending"
        elif _PARTIAL.search(raw):
            st = "Partial"
        elif _DENIED.search(raw):
            st = "Denied"
        elif _RECOVERED.search(raw):
            st = "Recovered"
    if not st:
        if app <= 0:
            st = "Not appealed"
        elif rec <= 0:
            st = "Pending"
        elif rec >= app - 0.005:
            st = "Recovered"
        else:
            st = "Partial"
    # A "recovered" label that the amounts contradict is corrected.
    if st == "Recovered" and app > 0 and rec < app - 0.005:
        st = "Partial" if rec > 0 else "Denied"
    return st


def make_record(inv, billed, red, app=0.0, rec=0.0, status="", tk="", role="",
                client="", portal="", reason="", when=None) -> dict:
    """Build one normalized invoice row, including its outcome split."""
    red = max(0.0, red or 0.0)
    app = max(0.0, app or 0.0)
    rec = max(0.0, rec or 0.0)
    st = classify_status(status, app, rec)
    seg_rec = min(rec, red)
    seg_app = min(max(app, seg_rec), red)
    open_amt = seg_app - seg_rec
    return {
        "inv": str(inv),
        "date": pd.Timestamp(when) if when is not None else pd.NaT,
        "tk": tk or NA,
        "role": role or "",
        "client": client or NA,
        "portal": portal or NA,
        "reason": reason or NA,
        "billed": float(billed),
        "red": red,
        "app": app,
        "rec": rec,
        "status": st,
        "pct": red / billed if billed > 0 else 0.0,
        "seg_rec": seg_rec,
        "seg_pend": open_amt if st == "Pending" else 0.0,
        "seg_den": 0.0 if st == "Pending" else open_amt,
        "seg_none": red - seg_app,
    }


def to_frame(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(records, columns=COLUMNS)
    df["date"] = pd.to_datetime(df["date"])
    return df


# ---------------------------------------------------------------- aggregation

def totals(df: pd.DataFrame) -> dict:
    keys = ["billed", "red", "app", "rec", "seg_rec", "seg_pend", "seg_den", "seg_none"]
    out = {k: float(df[k].sum()) for k in keys}
    out["n"] = int(len(df))
    return out


def ratio(a: float, b: float) -> float:
    return a / b if b > 0 else float("nan")


def group_totals(df: pd.DataFrame, dim: str, top: int = 10, sort_by: str = "red") -> pd.DataFrame:
    """Totals per group, largest first; groups past `top` fold into one 'Other (n)' row."""
    keys = ["billed", "red", "app", "rec", "seg_rec", "seg_pend", "seg_den", "seg_none"]
    g = df.groupby(dim, dropna=False)[keys].sum()
    g["n"] = df.groupby(dim, dropna=False).size()
    if dim == "tk":
        g["role"] = df.groupby(dim)["role"].first()
    g["rate"] = (g["red"] / g["billed"].where(g["billed"] > 0)).fillna(0.0)
    g = g.reset_index().rename(columns={dim: "label"})
    g = g.sort_values([sort_by, "label"], ascending=[False, True])
    if len(g) > top:
        head, rest = g.iloc[: top - 1], g.iloc[top - 1:]
        other = rest[keys + ["n"]].sum()
        other["label"] = f"Other ({len(rest)})"
        other["rate"] = other["red"] / other["billed"] if other["billed"] > 0 else 0.0
        if dim == "tk":
            other["role"] = ""
        g = pd.concat([head, other.to_frame().T], ignore_index=True)
    return g.reset_index(drop=True)


# ---------------------------------------------------------------- import

# For each field: header patterns tried in order (strict first, then loose).
FIELD_RX = [
    ("status", [r"status|outcome|disposition"]),
    ("reason", [r"reason", r"category|reduction type|adjustment type"]),
    ("date", [r"^(invoice|inv|bill|billing) date$|^date$", r"date"]),
    ("role", [r"role|title|classification|level"]),
    ("client", [r"client"]),
    ("portal", [r"portal|platform|e billing|ebilling|vendor|system"]),
    ("inv", [r"^(invoice|inv)( ?(number|num|no|id|#))?$", r"invoice.*(number|no|#|id)"]),
    ("tk", [r"time ?keeper|^tk( name)?$", r"attorney|biller|professional"]),
    ("billed", [r"^(billed|bill|gross|invoice|invoiced|submitted)( (amount|amt|total|fees))?$|^(amount|total) billed$", r"billed"]),
    ("red", [r"^(reduction|reduced|write ?down|adjustment|cut)( (amount|amt))?$|^(amount|total) reduced$", r"reduc|write ?down"]),
    ("app", [r"^(appeal|appealed)( (amount|amt))?$|^(amount|total) appealed$", r"appeal"]),
    ("rec", [r"^(recovery|recovered|reinstated)( (amount|amt))?$|^(amount|total) recovered$", r"recover|reinstat"]),
]
REQUIRED = [("inv", "Invoice Number"), ("billed", "Billed Amount"), ("red", "Reduction Amount")]


def _norm_header(x) -> str:
    x = str(x).lower()
    x = re.sub(r"\(\$\)|\$|usd", " ", x)
    x = re.sub(r"[_\-./]+", " ", x)
    return re.sub(r"\s+", " ", x).strip()


def map_headers(headers: list) -> dict:
    """Return {field: column index}. Percent/rate columns are ignored (they are recalculated)."""
    norm = [_norm_header(h) for h in headers]
    used = {i for i, x in enumerate(norm) if re.search(r"%|pct|percent|\brate\b", x)}
    found = {}
    for field, patterns in FIELD_RX:
        for pat in patterns:
            rx = re.compile(pat)
            hit = next((i for i, x in enumerate(norm) if i not in used and rx.search(x)), None)
            if hit is not None:
                found[field] = hit
                used.add(hit)
                break
    return found


def parse_money(v) -> float:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return float("nan")
    if isinstance(v, (int, float)):
        return abs(float(v))
    s = re.sub(r"[^0-9.\-]", "", str(v))
    if s in ("", "-", "."):
        return float("nan")
    try:
        return abs(float(s))
    except ValueError:
        return float("nan")


def parse_date(v):
    """Accept ISO, US m/d/y (d/m/y when unambiguous), Excel serial numbers, or datetime objects."""
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, (datetime, date, pd.Timestamp)):
        return pd.Timestamp(v).normalize()
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if math.isnan(v):
            return None
        v = str(v)
    s = str(v).strip()
    if not s:
        return None
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    try:
        if m:
            return pd.Timestamp(int(m[1]), int(m[2]), int(m[3]))
        m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$", s)
        if m:
            mo, d, y = int(m[1]), int(m[2]), int(m[3])
            if y < 100:
                y += 2000
            if mo > 12 and d <= 12:
                mo, d = d, mo
            return pd.Timestamp(y, mo, d)
        if re.match(r"^\d{5}(\.\d+)?$", s):  # Excel serial date
            return pd.Timestamp(datetime(1899, 12, 30) + timedelta(days=float(s))).normalize()
        return pd.Timestamp(pd.to_datetime(s)).normalize()
    except (ValueError, OverflowError, TypeError):
        return None


def parse_delimited(text: str) -> list[list[str]]:
    """Parse pasted Excel rows (tab) or CSV (comma / semicolon) into a grid."""
    text = text.lstrip("﻿")
    first = text.split("\n", 1)[0]
    if "\t" in first:
        delim = "\t"
    elif first.count(";") > first.count(","):
        delim = ";"
    else:
        delim = ","
    rows = csv.reader(io.StringIO(text), delimiter=delim)
    return [r for r in rows if any(c.strip() for c in r)]


def import_grid(grid: list[list]) -> dict:
    """Turn a header row + data rows into dashboard records.

    Returns {"df", "skipped", "mapping"} on success or {"error"} on failure.
    """
    if len(grid) < 2:
        return {"error": "Provide at least a header row and one invoice row."}
    headers = [str(h).strip() for h in grid[0]]
    fmap = map_headers(headers)
    missing = [label for key, label in REQUIRED if key not in fmap]
    if missing:
        return {"error": (
            f"No column found for {', '.join(missing)}. The header row reads: "
            f"{', '.join(h for h in headers if h)}. Rename the matching columns and try again."
        )}

    def raw(row, field):
        i = fmap.get(field)
        if i is None or i >= len(row):
            return None
        return row[i]

    def text(row, field):
        v = raw(row, field)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return ""
        return str(v).strip()

    def amount(row, field):
        n = parse_money(raw(row, field))
        return 0.0 if math.isnan(n) else n

    records, skipped = [], 0
    for row in grid[1:]:
        inv = text(row, "inv")
        billed = parse_money(raw(row, "billed"))
        if not inv or math.isnan(billed):
            skipped += 1
            continue
        records.append(make_record(
            inv=inv, billed=billed, red=amount(row, "red"), app=amount(row, "app"),
            rec=amount(row, "rec"), status=text(row, "status"), tk=text(row, "tk"),
            role=text(row, "role"), client=text(row, "client"), portal=text(row, "portal"),
            reason=text(row, "reason"), when=parse_date(raw(row, "date")),
        ))
    if not records:
        return {"error": "No rows had both an invoice number and a numeric billed amount."}
    mapping = {f: headers[i] for f, i in fmap.items()}
    return {"df": to_frame(records), "skipped": skipped, "mapping": mapping}


def import_text(text: str) -> dict:
    return import_grid(parse_delimited(text or ""))


def import_dataframe(raw_df: pd.DataFrame) -> dict:
    grid = [list(raw_df.columns)] + raw_df.astype(object).where(raw_df.notna(), None).values.tolist()
    return import_grid(grid)


def import_file(name: str, data: bytes) -> dict:
    lower = name.lower()
    if lower.endswith((".xlsx", ".xlsm", ".xls")):
        try:
            raw_df = pd.read_excel(io.BytesIO(data), dtype=object)
        except Exception as exc:  # noqa: BLE001 - surface any reader error to the user
            return {"error": f"That workbook could not be read ({exc}). Save it as .xlsx or .csv and try again."}
        return import_dataframe(raw_df)
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return import_text(data.decode(enc))
        except UnicodeDecodeError:
            continue
    return {"error": "That file could not be read. Save it as CSV and try again."}


# ---------------------------------------------------------------- export

EXPORT_HEADERS = [
    "Invoice Number", "Invoice Date", "Timekeeper", "Role", "Client", "Portal",
    "Reduction Reason", "Billed Amount", "Reduction Amount", "Reduction %",
    "Appeal Amount", "Recovery Amount", "Appeal Status",
]


def export_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Filtered rows in the same column layout the importer reads back."""
    blank = lambda s: s.replace(NA, "")  # noqa: E731
    return pd.DataFrame({
        "Invoice Number": df["inv"],
        "Invoice Date": df["date"].dt.date,
        "Timekeeper": blank(df["tk"]),
        "Role": df["role"],
        "Client": blank(df["client"]),
        "Portal": blank(df["portal"]),
        "Reduction Reason": blank(df["reason"]),
        "Billed Amount": df["billed"].round(2),
        "Reduction Amount": df["red"].round(2),
        "Reduction %": (df["pct"] * 100).round(2),
        "Appeal Amount": df["app"].round(2),
        "Recovery Amount": df["rec"].round(2),
        "Appeal Status": df["status"],
    })


def export_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        export_frame(df).to_excel(xw, index=False, sheet_name="Appeals")
        ws = xw.sheets["Appeals"]
        for col, width in zip("ABCDEFGHIJKLM", [16, 13, 20, 18, 24, 15, 22, 14, 16, 12, 14, 15, 15]):
            ws.column_dimensions[col].width = width
        for row in ws.iter_rows(min_row=2, min_col=8, max_col=12):
            for c in row:
                c.number_format = '0.00"%"' if c.column == 10 else '"$"#,##0.00'
    return buf.getvalue()


def template_csv() -> str:
    return ",".join(EXPORT_HEADERS) + "\n" + \
        "INV-1001,2026-01-15,Jane Doe,Associate,Acme Corp,Tymetrix 360,Block billing,12500.00,950.00,,950.00,600.00,Partial\n"


# ---------------------------------------------------------------- sample data

def sample_data() -> pd.DataFrame:
    """Made-up invoices for illustration: 12 months, 8 timekeepers, 18 clients on 18 e-billing portals.

    Same every load.
    """
    rnd = random.Random(20261007).random

    def wpick(pairs):
        x = rnd() * sum(w for _, w in pairs)
        for v, w in pairs:
            x -= w
            if x < 0:
                return v
        return pairs[0][0]

    tks = [
        ("Dana Whitcombe", "Partner", 9000, 52000), ("Marcus Oyelaran", "Partner", 8000, 46000),
        ("Priya Raman", "Senior Associate", 6000, 38000), ("Ethan Kowalczyk", "Associate", 4000, 30000),
        ("Sofia Marchetti", "Associate", 4000, 28000), ("Jordan Blake", "Associate", 3500, 26000),
        ("Lena Fischer", "Paralegal", 1200, 9500), ("Tomas Rivera", "Paralegal", 1200, 8500),
    ]
    # (client, e-billing portal, relative invoice volume): one fictional client per portal
    clients = [
        ("Northgate Mutual", "Tymetrix 360", 9), ("Harborline Insurance", "CounselLink", 8),
        ("Calder Freight Lines", "Legal-X", 7), ("Summit Ridge Health", "Collaborati", 7),
        ("Pinecrest Property Trust", "Serengeti", 6), ("Bayview Casualty", "Quovant", 6),
        ("Ironwood Energy", "Datacert", 5), ("Meridian Rail", "Legal Exchange", 5),
        ("Ashford Retail Group", "Counsel Go", 4), ("Clearwater Logistics", "Legal Bill Review", 4),
        ("Granite Peak Mining", "Stuart Maue", 4), ("Lakeshore Mutual Life", "SIMS", 3),
        ("Redwood Pharma", "Ascent", 3), ("Silverline Telecom", "Bill Track Pro", 3),
        ("Oakmont Construction", "Billing Point", 2), ("Fairhaven Bank", "Case Glide", 2),
        ("Westbrook Hospitality", "Datalytics", 2), ("Crescent Auto Finance", "Legal Solutions", 2),
    ]
    # reason: (min %, max %, chance appealed, win factor)
    reasons = {
        "Block billing": (.06, .18, .88, .65), "Vague narrative": (.04, .14, .92, .78),
        "Administrative task": (.10, .30, .55, .30), "Excessive time": (.05, .20, .80, .45),
        "Rate above approved": (.02, .08, .70, .55), "Duplicate staffing": (.06, .16, .75, .40),
        "Travel time": (.03, .10, .60, .50), "Late time entry": (.08, .24, .40, .25),
    }
    by_role = {
        "Partner": [("Rate above approved", 3), ("Duplicate staffing", 3), ("Block billing", 2), ("Travel time", 2), ("Vague narrative", 1)],
        "Senior Associate": [("Block billing", 3), ("Vague narrative", 3), ("Excessive time", 2), ("Duplicate staffing", 1), ("Travel time", 1)],
        "Associate": [("Block billing", 3), ("Vague narrative", 3), ("Excessive time", 3), ("Late time entry", 1), ("Duplicate staffing", 1)],
        "Paralegal": [("Administrative task", 5), ("Vague narrative", 2), ("Late time entry", 2), ("Excessive time", 1)],
    }
    out, no = [], 204100
    for m in range(12):
        year, month = 2025 + (9 + m) // 12, (9 + m) % 12 + 1
        for _ in range(9 + int(rnd() * 6)):
            name, role, lo, hi = tks[int(rnd() * len(tks))]
            client, portal = wpick([((c, pt), w) for c, pt, w in clients])
            reason = wpick(by_role[role])
            pmin, pmax, p_appeal, win = reasons[reason]
            billed = round(lo + rnd() ** 1.8 * (hi - lo), 2)
            red = round(billed * (pmin + rnd() * (pmax - pmin)), 2)
            app = rec = 0.0
            status = "Not appealed"
            if rnd() < p_appeal:
                app = red if rnd() < .55 else round(red * (.55 + rnd() * .4), 2)
                pend_chance = .9 if m >= 11 else .7 if m >= 10 else .45 if m >= 9 else .25 if m >= 7 else .05
                if rnd() < pend_chance:
                    status = "Pending"
                else:
                    u = rnd()
                    if u < win * .42:
                        rec, status = app, "Recovered"
                    elif u < win * .42 + .42:
                        rec, status = round(app * (.25 + rnd() * .55), 2), "Partial"
                    else:
                        status = "Denied"
            no += 3 + int(rnd() * 40)
            out.append(make_record(
                inv=f"INV-{no}", billed=billed, red=red, app=app, rec=rec, status=status,
                tk=name, role=role, client=client, portal=portal, reason=reason,
                when=date(year, month, 1 + int(rnd() * 27)),
            ))
    return to_frame(out)
