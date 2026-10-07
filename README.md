# Legal Billing Appeal Dashboard

A Streamlit web app for tracking e-billing reductions and appeal recoveries across
U.S. e-billing portals. The built-in sample data covers 18 portals: Tymetrix 360, CounselLink,
Legal-X, Collaborati, Serengeti, Quovant, Datacert, Legal Exchange, Counsel Go, Legal Bill Review,
Stuart Maue, SIMS, Ascent, Bill Track Pro, Billing Point, Case Glide, Datalytics and Legal Solutions.

![sections](https://img.shields.io/badge/built%20with-Streamlit-ff4b4b)

## What it shows

| Section | What it answers |
|---|---|
| **KPI tiles** | Billed, reduced, reduction %, appealed, recovered (with median reduction %, % appealed, $ pending) |
| **Where the reduced dollars stand** | Billed − Reduced + Recovered = Net collectible, and a strip splitting every reduced dollar into Recovered / Appeal pending / Denied / Not appealed |
| **Reductions by invoice month** | Stacked monthly columns by appeal outcome |
| **Reductions by timekeeper** | Stacked bars — **click a bar to filter the whole page** to that timekeeper |
| **Reductions by reason / portal / client** | Shows which reduction types are worth appealing (click to filter) |
| **Reduction rate by timekeeper** | Reduced ÷ billed per timekeeper vs. the overall rate |
| **Invoice register** | Sortable, searchable table of every invoice |

Every chart has a **Table** tab with the same numbers. Filtered rows download as **Excel** or **CSV**.

## Loading your own tracker

Use the sidebar → *Load your appeal tracker*: upload an **.xlsx / .csv** or paste rows straight from Excel.

* **Required columns:** `Invoice Number`, `Billed Amount`, `Reduction Amount`
* **Optional:** `Invoice Date`, `Timekeeper`, `Role`, `Client`, `Portal`, `Reduction Reason`,
  `Appeal Amount`, `Recovery Amount`, `Appeal Status`

Headers are matched loosely (`Inv #`, `Write-down`, `Amount Appealed`, `E-Billing Portal`… all work).
Reduction % is always recalculated. Free-text statuses are classified automatically
("Approved", "Under review", "Rejected", "Accepted reduction"…). With no status column,
the amounts decide: appealed but nothing recovered = Pending, partly recovered = Partial.
Click **Template** in the sidebar for a ready-made CSV header row.

Uploaded data lives only in your browser session; nothing is stored on the server.

## Run locally (Windows 11)

```powershell
cd Legal-Billing-Appeal-Dashboard
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

The app opens at http://localhost:8501.

## Publish publicly on Streamlit Community Cloud (free)

1. Make sure this repository is on GitHub (it can be public or private).
2. Go to **https://share.streamlit.io** and sign in with GitHub.
3. Click **Create app → Deploy a public app from GitHub**.
4. Fill in:
   * **Repository:** `vineet6183-hash/Legal-Billing-Appeal-Dashboard`
   * **Branch:** the branch you want live (e.g. `main`)
   * **Main file path:** `app.py`
   * **App URL:** pick a subdomain, e.g. `legal-billing-appeals`
5. Click **Deploy**. The first build takes 2–3 minutes; after that, every push to the branch redeploys automatically.

> ⚠️ A public app URL can be opened by anyone. The app ships with made-up sample data, and
> uploads stay in each visitor's own session — but don't commit real client billing data to the repo.

## Project layout

```
app.py                 Streamlit UI (filters, KPIs, charts, register, downloads)
billing.py             Data logic: import, header matching, status rules, outcome split, sample data
tests/test_app.py      pytest suite (import rules + full app render via Streamlit AppTest)
requirements.txt       Dependencies for Streamlit Cloud
.streamlit/config.toml Theme
```

Run the tests with `pip install pytest && pytest`.
