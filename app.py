"""Legal Billing Appeal Dashboard - Streamlit app.

Run locally:   streamlit run app.py
Deploy:        push this repo to GitHub, then create an app at share.streamlit.io pointing to app.py
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import billing as B

st.set_page_config(page_title="Legal Billing Appeal Dashboard", page_icon="⚖️", layout="wide")

ALL = "All"
PERIODS = {
    "all": "All dates",
    "m3": "Latest 3 months",
    "m6": "Latest 6 months",
    "m12": "Latest 12 months",
    "custom": "Custom range",
}
FILTER_DEFAULTS = {
    "f_period": "all", "f_from": None, "f_to": None, "f_tk": ALL, "f_client": ALL,
    "f_portal": ALL, "f_reason": ALL, "f_status": ALL, "f_minpct": 0.0, "f_q": "",
}
STATUS_ICON = {"Recovered": "🔵", "Partial": "◐", "Pending": "🟢", "Denied": "🟠", "Not appealed": "⚪"}

st.markdown(
    """
    <style>
      .block-container {padding-top: 2rem; max-width: 1400px;}
      .kpi-label {font-size: .74rem; letter-spacing: .08em; text-transform: uppercase; color: #687280; font-weight: 600;}
      .kpi-val {font-size: 1.65rem; font-weight: 600; line-height: 1.25; font-variant-numeric: tabular-nums;}
      .kpi-sub {font-size: .82rem; color: #687280;}
      .recon {font-size: .92rem; display: flex; flex-wrap: wrap; gap: 4px 16px; margin-bottom: .25rem;}
      .recon b {font-variant-numeric: tabular-nums;}
      .recon .op {color: #8f98a4; font-family: monospace;}
      .tag {font-size: .7rem; font-weight: 600; letter-spacing: .08em; text-transform: uppercase;
            border: 1px solid #c5cad2; border-radius: 3px; padding: 1px 6px; margin-right: 6px;}
      .sec-title {font-size: 1.15rem; font-weight: 600; margin-bottom: -.4rem;}
      .kpi-box {min-height: 6.4rem;}
      .lg {white-space: nowrap; display: inline-block; margin-right: 14px; font-size: .85rem;}
      .legend-sw {display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------- formatting

def usd0(v: float) -> str:
    return f"${v:,.0f}"


def usd2(v: float) -> str:
    return f"${v:,.2f}"


def usdc(v: float) -> str:
    """Compact dollars: $1.2K, $3.4M."""
    a = abs(v)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"${v / div:,.1f}".rstrip("0").rstrip(".") + suf
    return f"${v:,.0f}"


def pct(v: float, d: int = 1) -> str:
    return "n/a" if v is None or not math.isfinite(v) else f"{v * 100:.{d}f}%"


# ---------------------------------------------------------------- state

def init_state() -> None:
    if "data" not in st.session_state:
        st.session_state.data = B.sample_data()
        st.session_state.source = "sample"
        st.session_state.import_msg = None
    for k, v in FILTER_DEFAULTS.items():
        st.session_state.setdefault(k, v)
    st.session_state.setdefault("group_dim", "reason")


def reset_filters() -> None:
    for k, v in FILTER_DEFAULTS.items():
        st.session_state[k] = v


def use_data(df: pd.DataFrame, source: str) -> None:
    st.session_state.data = df
    st.session_state.source = source
    reset_filters()


def load_uploaded() -> None:
    up = st.session_state.get("upload")
    if up is None:
        st.session_state.import_msg = ("error", "Choose a file first.")
        return
    res = B.import_file(up.name, up.getvalue())
    finish_import(res)


def load_pasted() -> None:
    res = B.import_text(st.session_state.get("paste", ""))
    finish_import(res)


def finish_import(res: dict) -> None:
    if "error" in res:
        st.session_state.import_msg = ("error", res["error"])
        return
    use_data(res["df"], "yours")
    msg = f"Loaded {len(res['df'])} invoices."
    if res["skipped"]:
        msg += f" Skipped {res['skipped']} rows with no invoice number or billed amount."
    msg += " Columns matched: " + ", ".join(f"**{v}**" for v in res["mapping"].values()) + "."
    st.session_state.import_msg = ("success", msg)


def restore_sample() -> None:
    use_data(B.sample_data(), "sample")
    st.session_state.import_msg = ("success", "Sample data restored.")


def toggle_filter(key: str, value: str) -> None:
    st.session_state[key] = ALL if st.session_state.get(key) == value else value


def on_bar_select(chart_key: str, filter_key: str) -> None:
    """Clicking a bar filters the page to that group; clicking it again clears the filter."""
    sel = st.session_state.get(chart_key)
    points = (sel or {}).get("selection", {}).get("points", []) if sel else []
    if not points:
        return
    label = points[0].get("y")
    if label and not str(label).startswith("Other ("):
        toggle_filter(filter_key, label)


init_state()
DATA: pd.DataFrame = st.session_state.data
HAS = {d: bool((DATA[d] != B.NA).any()) for d in ("tk", "client", "portal", "reason")}
HAS["role"] = bool((DATA["role"] != "").any())
HAS["date"] = bool(DATA["date"].notna().any())
if not HAS.get(st.session_state.group_dim, True):
    st.session_state.group_dim = next((d for d in ("reason", "portal", "client") if HAS[d]), "status")


# ---------------------------------------------------------------- sidebar: data + filters

with st.sidebar:
    st.header("Data")
    with st.expander("Load your appeal tracker", expanded=st.session_state.source == "sample"):
        st.caption(
            "Required columns: **Invoice Number**, **Billed Amount**, **Reduction Amount**. "
            "Optional: Timekeeper, Role, Appeal Amount, Recovery Amount, Invoice Date, Client, "
            "Portal, Reduction Reason, Appeal Status. Headers are matched loosely, so most "
            "tracker layouts work as-is. Reduction % is calculated. Without a status column, "
            "an appealed line with no recovery counts as pending."
        )
        st.file_uploader("Excel or CSV file", type=["xlsx", "xlsm", "xls", "csv", "tsv", "txt"], key="upload")
        st.button("Load file", on_click=load_uploaded, type="primary", use_container_width=True)
        st.text_area("…or paste rows copied from Excel (header row included)", key="paste", height=110)
        st.button("Load pasted rows", on_click=load_pasted, use_container_width=True)
        c1, c2 = st.columns(2)
        c1.button("Sample data", on_click=restore_sample, use_container_width=True)
        c2.download_button("Template", B.template_csv(), "appeal_tracker_template.csv", "text/csv",
                           use_container_width=True)
        st.caption("Uploaded data is held only in your browser session and is not saved on the server.")
    if st.session_state.import_msg:
        kind, msg = st.session_state.import_msg
        (st.error if kind == "error" else st.success)(msg)

    st.header("Filters")
    if HAS["date"]:
        st.selectbox("Invoice period", list(PERIODS), format_func=PERIODS.get, key="f_period")
        if st.session_state.f_period == "custom":
            c1, c2 = st.columns(2)
            c1.date_input("From", key="f_from", format="MM/DD/YYYY")
            c2.date_input("To", key="f_to", format="MM/DD/YYYY")

    def options(col: str) -> list[str]:
        return [ALL] + sorted(DATA[col].unique(), key=str.lower)

    for col, key in (("tk", "f_tk"), ("client", "f_client"), ("portal", "f_portal"), ("reason", "f_reason")):
        if HAS[col]:
            opts = options(col)
            if st.session_state[key] not in opts:
                st.session_state[key] = ALL
            st.selectbox(B.DIMS[col], opts, key=key)
    st.selectbox("Appeal status", [ALL] + [s for s in B.STATUSES if (DATA["status"] == s).any()], key="f_status")
    st.number_input("Reduction % at least", min_value=0.0, max_value=100.0, step=1.0, key="f_minpct")
    st.text_input("Invoice number contains", key="f_q", placeholder="Search")
    st.button("Reset filters", on_click=reset_filters, use_container_width=True)


# ---------------------------------------------------------------- filtering

def period_range() -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    p = st.session_state.f_period
    if p == "all" or not HAS["date"]:
        return None, None
    if p == "custom":
        a, b = st.session_state.f_from, st.session_state.f_to
        return (pd.Timestamp(a) if a else None,
                pd.Timestamp(b) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1) if b else None)
    n = int(p[1:])
    latest = DATA["date"].max()
    start = (latest.to_period("M") - (n - 1)).to_timestamp()
    return start, None


def filtered() -> pd.DataFrame:
    df = DATA
    ss = st.session_state
    lo, hi = period_range()
    if lo is not None:
        df = df[df["date"].notna() & (df["date"] >= lo)]
    if hi is not None:
        df = df[df["date"].notna() & (df["date"] <= hi)]
    for col, key in (("tk", "f_tk"), ("client", "f_client"), ("portal", "f_portal"),
                     ("reason", "f_reason"), ("status", "f_status")):
        if ss[key] != ALL:
            df = df[df[col] == ss[key]]
    if ss.f_minpct:
        df = df[df["pct"] * 100 >= ss.f_minpct - 1e-9]
    q = ss.f_q.strip().lower()
    if q:
        df = df[df["inv"].str.lower().str.contains(q, regex=False)]
    return df


ROWS = filtered()
A = B.totals(ROWS)


# ---------------------------------------------------------------- header

dated = DATA["date"].dropna()
span = f", {dated.min():%b %Y} to {dated.max():%b %Y}" if len(dated) else ""
if st.session_state.source == "sample":
    src = (f'<span class="tag">Sample data</span>{len(DATA)} made-up invoices for illustration{span}. '
           "Load your own tracker from the sidebar to replace them.")
else:
    src = f'<span class="tag">Your data</span>{len(DATA)} invoices loaded{span}.'

h1, h2 = st.columns([3, 1], vertical_alignment="bottom")
with h1:
    st.title("Legal Billing Appeal Dashboard")
    st.markdown(src, unsafe_allow_html=True)
with h2:
    d1, d2 = st.columns(2)
    stamp = date.today().isoformat()
    d1.download_button("⬇ Excel", B.export_excel(ROWS), f"appeal_register_{stamp}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True, help="Download the filtered invoices as an Excel workbook")
    d2.download_button("⬇ CSV", B.export_frame(ROWS).to_csv(index=False), f"appeal_register_{stamp}.csv",
                       "text/csv", use_container_width=True, help="Download the filtered invoices as CSV")

# active filter summary
chips = []
ss = st.session_state
if ss.f_period != "all" and HAS["date"]:
    label = PERIODS[ss.f_period]
    if ss.f_period == "custom":
        label += f": {ss.f_from or 'start'} to {ss.f_to or 'latest'}"
    chips.append(label)
for col, key in (("tk", "f_tk"), ("client", "f_client"), ("portal", "f_portal"),
                 ("reason", "f_reason"), ("status", "f_status")):
    if ss[key] != ALL:
        chips.append(f"{B.DIMS[col]}: {ss[key]}")
if ss.f_minpct:
    chips.append(f"Reduction % ≥ {ss.f_minpct:g}")
if ss.f_q.strip():
    chips.append(f'Invoice contains "{ss.f_q.strip()}"')
cap = f"**Showing {len(ROWS)} of {len(DATA)} invoices**"
if chips:
    cap += " · " + " · ".join(f"`{c}`" for c in chips)
st.markdown(cap)


# ---------------------------------------------------------------- KPIs

def section(title: str) -> None:
    st.markdown(f'<div class="sec-title">{title}</div>', unsafe_allow_html=True)


def kpi(col, label: str, value: str, sub: str) -> None:
    with col.container(border=True):
        st.markdown(f'<div class="kpi-box"><div class="kpi-label">{label}</div><div class="kpi-val">{value}</div>'
                    f'<div class="kpi-sub">{sub}</div></div>', unsafe_allow_html=True)


n_tk = ROWS["tk"].nunique()
median = ROWS["pct"].median() if len(ROWS) else float("nan")
k = st.columns(5)
kpi(k[0], "Billed amount", usd0(A["billed"]),
    f"{A['n']} invoice{'s' if A['n'] != 1 else ''}" + (f", {n_tk} timekeeper{'s' if n_tk != 1 else ''}" if HAS["tk"] else ""))
kpi(k[1], "Reduction amount", usd0(A["red"]),
    f"{usd0(A['red'] / A['n'])} average per invoice" if A["n"] else "No invoices")
kpi(k[2], "Reduction %", pct(B.ratio(A["red"], A["billed"])),
    f"Median invoice {pct(median)}" if A["n"] else "No invoices")
kpi(k[3], "Appeal amount", usd0(A["app"]),
    f"{pct(B.ratio(A['app'], A['red']), 0)} of reductions appealed" if A["red"] > 0 else "Nothing reduced")
kpi(k[4], "Recovery amount", usd0(A["rec"]),
    f"{pct(B.ratio(A['rec'], A['app']), 0)} of appealed, {usdc(A['seg_pend'])} pending" if A["app"] > 0 else "Nothing appealed")


# ---------------------------------------------------------------- chart helpers

SEG_KEYS = [s[0] for s in B.SEGMENTS]


def base_layout(fig: go.Figure, height: int, **kw) -> go.Figure:
    layout = dict(height=height, margin=dict(l=8, r=8, t=8, b=8), barmode="stack",
                  showlegend=False, bargap=0.35, hoverlabel=dict(align="left"))
    fig.update_layout(**{**layout, **kw})
    return fig


def seg_hover(label_field: str = "%{y}") -> str:
    return f"<b>{label_field}</b><br>%{{fullData.name}}: %{{x:$,.0f}} (%{{customdata[0]:.0%}} of reduced)<extra></extra>"


def legend_html() -> str:
    return "".join(f'<span class="lg"><span class="legend-sw" style="background:{c}"></span>{n}</span>' for _, n, c in B.SEGMENTS)


def seg_table(g: pd.DataFrame, first: str, total_label: str = "Total") -> pd.DataFrame:
    rows = g.copy()
    tot = B.totals(ROWS)
    total_row = {"label": total_label, **{k: tot[k] for k in SEG_KEYS + ["red", "billed"]}}
    rows = pd.concat([rows, pd.DataFrame([total_row])], ignore_index=True)
    out = pd.DataFrame({first: rows["label"]})
    for key, name, _ in B.SEGMENTS:
        out[name] = rows[key]
    out["Reduced"] = rows["red"]
    out["Billed"] = rows["billed"]
    out["Reduction %"] = (rows["red"] / rows["billed"].where(rows["billed"] > 0)).fillna(0) * 100
    return out


def money_cfg(df: pd.DataFrame) -> dict:
    cfg = {c: st.column_config.NumberColumn(c, format="dollar") for c in df.columns[1:] if c != "Reduction %"}
    cfg["Reduction %"] = st.column_config.NumberColumn("Reduction %", format="%.1f%%")
    return cfg


def show_table(df: pd.DataFrame) -> None:
    st.dataframe(df, hide_index=True, use_container_width=True, column_config=money_cfg(df))


def empty(msg: str = "No invoices match these filters.") -> None:
    st.info(msg)


# ---------------------------------------------------------------- outcome strip

with st.container(border=True):
    section("Where the reduced dollars stand")
    st.caption("Every reduced dollar is either recovered, in a pending appeal, denied on appeal, or was never appealed.")
    net = A["billed"] - A["red"] + A["rec"]
    net_pct = f" ({pct(net / A['billed'])} of billed)" if A["billed"] > 0 else ""
    st.markdown(
        f'<div class="recon"><span>Billed <b>{usd2(A["billed"])}</b></span>'
        f'<span><span class="op">−</span> Reduced <b>{usd2(A["red"])}</b></span>'
        f'<span><span class="op">+</span> Recovered <b>{usd2(A["rec"])}</b></span>'
        f'<span><span class="op">=</span> Net collectible <b>{usd2(net)}{net_pct}</b></span></div>',
        unsafe_allow_html=True,
    )
    if A["red"] > 0:
        fig = go.Figure()
        for key, name, color in B.SEGMENTS:
            v = A[key]
            fig.add_bar(y=[""], x=[v], name=name, orientation="h", marker_color=color,
                        customdata=[[v / A["red"]]],
                        hovertemplate=f"<b>{name}</b><br>%{{x:$,.0f}} · %{{customdata[0]:.1%}} of reductions<extra></extra>")
        base_layout(fig, 70, bargap=0)
        fig.update_xaxes(visible=False, range=[0, A["red"]])
        fig.update_yaxes(visible=False)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        cols = st.columns(4)
        for col, (key, name, color) in zip(cols, B.SEGMENTS):
            col.markdown(f'<span class="legend-sw" style="background:{color}"></span>{name}<br>'
                         f'<b style="font-size:1.05rem">{usd0(A[key])}</b> '
                         f'<span class="kpi-sub">{pct(B.ratio(A[key], A["red"]))}</span>',
                         unsafe_allow_html=True)
    else:
        empty("These invoices have no reductions." if A["n"] else "No invoices match these filters.")


# ---------------------------------------------------------------- monthly + timekeeper

def monthly_chart() -> None:
    section("Reductions by invoice month")
    st.caption("Column height is the total reduced that month.")
    d = ROWS[ROWS["date"].notna()].copy()
    if d.empty:
        empty("These invoices have no invoice dates. Add an Invoice Date column to see the monthly view."
              if len(ROWS) else "No invoices match these filters.")
        return
    d["month"] = d["date"].dt.to_period("M")
    months = pd.period_range(d["month"].min(), d["month"].max(), freq="M")
    g = d.groupby("month")[["billed", "red", "app", "rec"] + SEG_KEYS].sum().reindex(months, fill_value=0)
    g["n"] = d.groupby("month").size().reindex(months, fill_value=0)
    x = [p.to_timestamp() for p in g.index]
    tab_c, tab_t = st.tabs(["Chart", "Table"])
    with tab_c:
        st.markdown(legend_html(), unsafe_allow_html=True)
        fig = go.Figure()
        share = (g[SEG_KEYS].div(g["red"].where(g["red"] > 0), axis=0)).fillna(0)
        for key, name, color in B.SEGMENTS:
            fig.add_bar(
                x=x, y=g[key], name=name, marker_color=color,
                customdata=list(zip(share[key], g["n"], g["red"], g["billed"])),
                hovertemplate=(f"<b>%{{x|%B %Y}}</b> · %{{customdata[1]}} invoices<br>{name}: %{{y:$,.0f}} "
                               "(%{customdata[0]:.0%})<br>%{customdata[2]:$,.0f} reduced of "
                               "%{customdata[3]:$,.0f} billed<extra></extra>"),
            )
        peak = g["red"].idxmax()
        fig.add_annotation(x=peak.to_timestamp(), y=g.loc[peak, "red"], text=usdc(g.loc[peak, "red"]),
                           showarrow=False, yshift=10, font=dict(size=11))
        base_layout(fig, 300, hovermode="closest")
        fig.update_yaxes(tickprefix="$", tickformat="~s", gridcolor="rgba(128,128,128,.2)")
        fig.update_xaxes(tickformat="%b '%y", dtick="M1" if len(x) <= 14 else None)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    with tab_t:
        t = g.reset_index(names="m")
        t["label"] = [p.strftime("%b %Y") for p in t["m"]]
        show_table(seg_table(t, "Month"))


def stack_bars(dim: str, first_head: str, chart_key: str, filter_key: str | None) -> None:
    if ROWS.empty:
        empty()
        return
    g = B.group_totals(ROWS, dim)
    tab_c, tab_t = st.tabs(["Chart", "Table"])
    with tab_c:
        st.markdown(legend_html(), unsafe_allow_html=True)
        labels = list(g["label"])
        fig = go.Figure()
        for key, name, color in B.SEGMENTS:
            share = (g[key] / g["red"].where(g["red"] > 0)).fillna(0)
            fig.add_bar(y=labels, x=g[key], name=name, orientation="h", marker_color=color,
                        customdata=list(zip(share)), hovertemplate=seg_hover())
        rec_share = (g["seg_rec"] / g["red"].where(g["red"] > 0)).fillna(0)
        for lab, red, rs in zip(labels, g["red"], rec_share):
            fig.add_annotation(y=lab, x=red, text=f"<b>{usdc(red)}</b> · {rs:.0%} rec.", showarrow=False,
                               xanchor="left", xshift=6, font=dict(size=11))
        base_layout(fig, 60 + 34 * len(labels), clickmode="event+select")
        fig.update_yaxes(autorange="reversed", automargin=True)
        fig.update_xaxes(visible=False, range=[0, g["red"].max() * 1.32 or 1])
        if filter_key:
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, key=chart_key,
                            on_select=lambda: on_bar_select(chart_key, filter_key), selection_mode="points")
        else:
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    with tab_t:
        show_table(seg_table(g, first_head))


c_left, c_right = st.columns(2)
with c_left, st.container(border=True):
    monthly_chart()
if HAS["tk"]:
    with c_right, st.container(border=True):
        section("Reductions by timekeeper")
        st.caption("Click a bar to filter the page to that timekeeper; click again to clear.")
        stack_bars("tk", "Timekeeper", "tk_chart", "f_tk")


# ---------------------------------------------------------------- group + rate

DIM_FILTER = {"reason": "f_reason", "portal": "f_portal", "client": "f_client", "status": "f_status"}
c_left, c_right = st.columns(2)
with c_left, st.container(border=True):
    dims = [d for d in ("reason", "portal", "client") if HAS[d]]
    if dims:
        st.radio("Group by", dims, key="group_dim", horizontal=True, format_func=lambda d: d.capitalize(),
                 label_visibility="collapsed")
    gd = st.session_state.group_dim
    section("Reductions by " + {"reason": "reason", "portal": "portal", "client": "client",
                                     "status": "appeal status"}[gd])
    st.caption("Shows which reductions are worth appealing. Click a bar to filter.")
    stack_bars(gd, B.DIMS[gd], f"grp_chart_{gd}", DIM_FILTER[gd])

if HAS["tk"]:
    with c_right, st.container(border=True):
        section("Reduction rate by timekeeper")
        st.caption("Reduction amount as a share of the amount billed.")
        if ROWS.empty:
            empty()
        else:
            g = B.group_totals(ROWS, "tk", sort_by="rate")
            overall = B.ratio(A["red"], A["billed"])
            overall = 0.0 if not math.isfinite(overall) else overall
            tab_c, tab_t = st.tabs(["Chart", "Table"])
            with tab_c:
                labels = list(g["label"])
                fig = go.Figure()
                fig.add_bar(
                    y=labels, x=g["rate"], orientation="h", marker_color=B.RATE_COLOR,
                    customdata=list(zip(g["red"], g["billed"], g.get("role", [""] * len(g)))),
                    hovertemplate=("<b>%{y}</b> %{customdata[2]}<br>Reduction rate: %{x:.1%}<br>"
                                   "%{customdata[0]:$,.0f} reduced of %{customdata[1]:$,.0f} billed"
                                   f"<br>All timekeepers in view: {overall:.1%}<extra></extra>"),
                )
                for lab, r, b in zip(labels, g["rate"], g["billed"]):
                    fig.add_annotation(y=lab, x=r, text=f"<b>{r:.1%}</b> of {usdc(b)}", showarrow=False,
                                       xanchor="left", xshift=6, font=dict(size=11))
                fig.add_vline(x=overall, line_width=1, line_dash="dot", line_color="#687280")
                base_layout(fig, 60 + 34 * len(labels), clickmode="event+select")
                fig.update_yaxes(autorange="reversed", automargin=True)
                fig.update_xaxes(visible=False, range=[0, max(g["rate"].max(), overall) * 1.35 or 1])
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, key="rate_chart",
                                on_select=lambda: on_bar_select("rate_chart", "f_tk"), selection_mode="points")
                st.caption(f"The dotted line marks the rate for everything in view, {pct(overall)}.")
            with tab_t:
                t = pd.DataFrame({"Timekeeper": g["label"], "Billed": g["billed"], "Reduced": g["red"],
                                  "Reduction %": g["rate"] * 100})
                t.loc[len(t)] = ["Total", A["billed"], A["red"], overall * 100]
                show_table(t)


# ---------------------------------------------------------------- register

with st.container(border=True):
    section("Invoice register")
    st.caption("Click a column heading to sort. Use the toolbar above the table to search or download.")
    if ROWS.empty:
        empty("No invoices match these filters. Remove a filter in the sidebar to see rows again.")
    else:
        reg = pd.DataFrame({"Invoice #": ROWS["inv"]})
        if HAS["date"]:
            reg["Date"] = ROWS["date"].dt.date
        if HAS["tk"]:
            reg["Timekeeper"] = ROWS["tk"]
            if HAS["role"]:
                reg["Role"] = ROWS["role"]
        if HAS["client"]:
            reg["Client"] = ROWS["client"]
        if HAS["portal"]:
            reg["Portal"] = ROWS["portal"]
        if HAS["reason"]:
            reg["Reason"] = ROWS["reason"]
        reg["Billed"] = ROWS["billed"]
        reg["Reduction"] = ROWS["red"]
        reg["Reduction %"] = ROWS["pct"] * 100
        reg["Appealed"] = ROWS["app"]
        reg["Recovered"] = ROWS["rec"]
        reg["Appeal status"] = ROWS["status"].map(lambda s: f"{STATUS_ICON.get(s, '')} {s}")
        if HAS["date"]:
            reg = reg.sort_values("Date", ascending=False, na_position="last")
        cfg = {c: st.column_config.NumberColumn(c, format="dollar")
               for c in ("Billed", "Reduction", "Appealed", "Recovered")}
        cfg["Date"] = st.column_config.DateColumn("Date", format="MM/DD/YYYY")
        cfg["Reduction %"] = st.column_config.ProgressColumn(
            "Reduction %", format="%.1f%%", min_value=0.0, max_value=max(1.0, float(reg["Reduction %"].max())))
        st.dataframe(reg, hide_index=True, use_container_width=True, column_config=cfg,
                     height=min(36 * (len(reg) + 1) + 4, 480))
        st.markdown((
            f"**Total, {A['n']} invoice{'s' if A['n'] != 1 else ''}:** billed {usd2(A['billed'])} · "
            f"reduced {usd2(A['red'])} ({pct(B.ratio(A['red'], A['billed']))}) · "
            f"appealed {usd2(A['app'])} · recovered {usd2(A['rec'])}"
        ).replace("$", "\\$"))
