# Target & Recovery Dashboard — Guide

A read-only dashboard for **Propone › Booking Management › Targets** (Zameen Development).
It shows how much of each month's target was achieved with real money received, by staff, region, project and unit.

---

## 1. How to open it

| What | How |
|---|---|
| **Live dashboard** | Double-click **`Start Dashboard.bat`** in `D:\Claude Work`. It opens **http://127.0.0.1:8000** in the browser. |
| **Offline copy** | Open **`Target Dashboard - September 2026.html`**. No server, Redshift or internet needed. Filters are switched off and figures are frozen at export time. |
| **Start from PowerShell** | `powershell -ExecutionPolicy Bypass -File "D:\Claude Work\dashboard\start-dashboard.ps1"` |

The live dashboard runs on this PC only. It stays running in a minimised window called **Dashboard :8000**. Closing that window stops it.

---

## 2. Where the numbers come from

- **Source:** Propone data copied into **Amazon Redshift** (schema `propone_zameenpk`). The dashboard only reads, it never changes anything.
- **Delay:** Redshift receives Propone changes in batches, about **35–50 minutes** after they are made. A target edited in Propone appears here once that batch arrives.
- **Refresh:** the dashboard checks Redshift every minute and reloads only when new data has arrived. The page updates itself every 60 seconds.
- **Months** follow Pakistan time. A payment counts in the month it was deposited.
- **Only Installment and Possession money is counted.** Down payment, escalation, adjustment cost, taxes and fees are not shown anywhere.

---

## 3. Filters (top bar)

| Filter | Meaning |
|---|---|
| **Month** | One target month. |
| **Staff** | One or more people. Picking a manager includes **everyone below them**. |
| **City** | Lahore, North (includes Pindi), Multan. |
| **Project / Unit** | One or more projects or units. |
| **Aging** | Current (0–30 days), 30–60, 60–90, 90+ — the age of the installment that was paid, at the start of the month. |

Every filter changes **every** number on the page. The lists narrow each other: picking Lahore shows only Lahore's projects, staff and units.

---

## 4. KPI cards

| Card | Definition |
|---|---|
| **Target assigned** | The target set in Propone for the month (sum of booking targets). |
| **Target achieved** | Installment + Possession money **deposited in the month**, status **Verified** or **Received**, on bookings **with a target above 0**. Propone's own stored figure is shown underneath for comparison. |
| **Pending target** | Target assigned − Target achieved. |
| **Achievement rate** | Target achieved ÷ Target assigned. Green ≥ 90%, blue 60–90%, red < 60%. |
| **Target bookings** | Bookings with a target above 0, and how many of them received money against the target. |
| **Outside targets** | Installment + Possession money received on bookings **with no target**. Not part of Target achieved. |

**Strip under the cards:** Target achieved split into Installment vs Possession, the same money by aging bucket, and **Total received** = Target achieved + Outside targets.

---

## 5. Sections

| Section | What it shows |
|---|---|
| **Trend** | Achievement rate month by month, with target and achieved bars, plus a month-by-month table. |
| **Project performance** | Each project's target as a full bar, achieved filled against it, aging bar and rate. Click a project to filter the page. |
| **Region performance** | The same project figures grouped by city. |
| **Staff performance** | One row per agent against their target. Click a row to open the drill-down. |
| **Toggle: Target only / + Outside target** | On project, staff and hierarchy tables. The second option adds money received outside targets. |
| **Contribution** | Each project's share of Target achieved. |
| **Staff hierarchy** | Tree starting at Arman Yousaf. A manager's row is the total of their whole team. **Details** opens the drill-down. |
| **Money received without a target** | Same figure as the Outside targets card, by staff and by unit, with the payments behind each booking. |
| **Drill-down** | Staff → project → booking → each payment, with installment due date, aging and Propone's figure. |

---

## 6. Rules behind the numbers

- **No double counting.** A booking listed under two staff members' targets is counted once, on one row: the row Propone credited, otherwise the booking owner's row, otherwise the row with the larger target.
- **Assigned stays whole under the Aging filter.** The filter narrows the money received; Propone stores the target as one amount that cannot be split by age.
- **Manual payment link.** Payment 75703 (TID 912594259, booking DTR-5169, Installment 11) is missing its booking link in Redshift and is added by hand in `dashboard\backend\payment_links.json`. The entry switches itself off once Redshift has the real link.
- **Why it differs from Propone's own achieved figure.** Propone sometimes credits down payment, escalation or adjustment money as achievement, and sometimes misses verified installment deposits. This dashboard counts only verified Installment + Possession deposits.

---

## 7. Header status

| Header shows | Meaning |
|---|---|
| 🟢 **Live · updated HH:MM** | Data is current. |
| 🟡 **Data delayed · last confirmed HH:MM** + reason | Redshift could not be reached for more than 5 minutes. The page keeps the last data and retries by itself. |
| 🔴 **Showing saved data from …** | Just started and Redshift is not reachable yet. Live data replaces it automatically. |

Common reasons and fixes:

- **"Redshift is not reachable from this network"** — the PC changed Wi-Fi or lost internet. Stay on the office network; it recovers on its own.
- **"Redshift login has too many open sessions"** — the login `ali_ayub` allows only about 5 connections, shared with other SQL tools. Close other tools using that login.
- **"Redshift is busy; a query took too long"** — the cluster is overloaded; it retries.

---

## 8. Folder layout

```
D:\Claude Work\
├── Start Dashboard.bat                      double-click to run
├── Target Dashboard - September 2026.html   offline copy
├── Target Dashboard Guide.md                this guide
└── dashboard\
    ├── start-dashboard.ps1                  builds the page if needed and starts the server
    ├── backend\                             Python (FastAPI) server, reads Redshift
    │   ├── .env                             Redshift login — keep private
    │   ├── app\                             queries and calculations
    │   ├── payment_links.json               manual payment links
    │   ├── city_names.json                  city names and Pindi → North merge
    │   ├── verify_dashboard.py              checks every figure against Redshift
    │   ├── export_snapshot.py               makes an offline HTML copy
    │   └── .cache\dashboard.log             server log
    └── frontend\                            React page (built into frontend\dist)
```

---

## 9. Useful commands

Run these in `D:\Claude Work\dashboard\backend` while the dashboard is running.

```powershell
# Check every figure against independent SQL in Redshift
.venv\Scripts\python verify_dashboard.py 2026-09-01

# Make a new offline HTML copy for a month (saved in dashboard\exports)
.venv\Scripts\python export_snapshot.py 2026-10-01
```

---

## 10. Going live for others

Running from this PC is fine for personal use, but it depends on this PC being on and on the office network. For a shared live version, ask IT for:

1. A small server in **AWS Ireland (eu-west-1)**, the same region as Redshift.
2. That server's address **approved in Redshift**.
3. A **separate read-only Redshift login** for the dashboard, so it never competes with personal SQL tools.
4. A company address such as `targets.zameen.com` with **company login (SSO)**, because the dashboard shows customer names and payments.

---

## September 2026 at a glance

*As of 7 October 2026, 11:43 PKT. September deposits can still change while payments are verified.*

| Figure | Value |
|---|---|
| Target assigned | 258.1M |
| Target achieved | 136.5M (Installment 130.5M · Possession 6.0M) |
| Achievement rate | 52.9% |
| Pending target | 121.6M |
| Target bookings | 1,043 with target · 330 achieved |
| Outside targets | 94.5M on 118 bookings |
| Total received | 231.0M |
| Propone's own achieved figure | 190.6M |
