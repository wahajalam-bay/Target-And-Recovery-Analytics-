"""Read-only check: dashboard API vs independent SQL on Propone data in Redshift.

Run with the backend up:  .venv\\Scripts\\python verify_dashboard.py [YYYY-MM-01]

Definitions checked here (recomputed with their own SQL, not the API's code path):
  Target assigned    Propone's staff-level (polaris_targets) and project-level totals.
  Target achieved    Installment + Possession deposited in the month (Verified/Received, PKT month)
                     on bookings that carry an assigned target, one row per booking (ROW_NUMBER).
  Outside targets    the same money on bookings with a 0 target or in no target list.
  Aging              age of the installment paid at the first day of the month: <=30 current,
                     31-60, 61-90, >90 days.
"""
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

from app.categories import INSTALLMENT, POSSESSION, TARGET_RELATED, categorize
from app.db import read_df

API = "http://127.0.0.1:8000/api"
S = "propone_zameenpk.propone_zameenpk__"
MONTH = sys.argv[1] if len(sys.argv) > 1 else "2026-09-01"
results = []
y, mo = int(MONTH[:4]), int(MONTH[5:7])
START = f"{y}-{mo:02d}-01 00:00:00"
END = f"{y + (mo == 12)}-{mo % 12 + 1:02d}-01 00:00:00"
AGING = ("current", "d30_60", "d60_90", "d90_plus")


def api(path, **params):
    q = urllib.parse.urlencode([(k, v) for k, vs in params.items()
                                for v in (vs if isinstance(vs, (list, tuple)) else [vs])])
    with urllib.request.urlopen(f"{API}{path}?{q}", timeout=120) as r:
        return json.load(r)


def check(name, got, expected):
    ok = got == expected
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}: dashboard={got}  expected={expected}")


def rate(h, a):
    return round(100.0 * h / a, 2) if a else None


def bucket(days):
    if days is None or pd.isna(days):
        return "current"
    d = int(days)
    return "current" if d <= 30 else "d30_60" if d <= 60 else "d60_90" if d <= 90 else "d90_plus"


# ---------- independent recomputation ----------
ROWS = read_df(f"""
SELECT bt.id AS bt_id, bt.booking_id, t.user_id, bt.assigned_target AS assigned, bt.project_id,
       p.city_id, b.unit_id, b.assignee_id,
       SUM(bt.assigned_target) OVER (PARTITION BY bt.booking_id) AS booking_assigned,
       ROW_NUMBER() OVER (PARTITION BY bt.booking_id
                          ORDER BY CASE WHEN bt.achieved_amount > 0 THEN 1 ELSE 0 END DESC,
                                   CASE WHEN t.user_id = b.assignee_id THEN 1 ELSE 0 END DESC,
                                   bt.assigned_target DESC, bt.id DESC) AS rn
FROM {S}polaris_bookings_targets bt
JOIN {S}polaris_targets t ON t.id = bt.target_id
JOIN {S}polaris_projects_targets pt ON pt.id = bt.target_project_id
JOIN {S}polaris_bookings b ON b.id = bt.booking_id
JOIN {S}polaris_projects p ON p.id = bt.project_id
WHERE t.tenant_id = 1 AND t.target_date = %s AND t.deleted_at IS NULL
  AND pt.deleted_at IS NULL AND bt.deleted_at IS NULL""", (MONTH,))
for c in ("assigned", "booking_assigned"):
    ROWS[c] = pd.to_numeric(ROWS[c], errors="coerce").fillna(0).astype("int64")
ROWS["targeted"] = ROWS.booking_assigned > 0

# Every I+P allocation deposited in the month, any booking of the tenant, with the installment age.
DEP = read_df(f"""
SELECT bp.booking_id, b.project_id, b.assignee_id, i.name, i.installment_type,
       DATEDIFF(day, DATEADD(hour, 5, i.due_date), %s::timestamp) AS age_days,
       SUM(COALESCE(a.amount, 0) - COALESCE(a.overdue_charges, 0) - COALESCE(a.income_tax, 0)
           - COALESCE(a.sales_tax, 0) - COALESCE(a.cancellation_fee, 0)) AS principal
FROM {S}polaris_bookings_payments bp
JOIN {S}polaris_payments p ON p.id = bp.payment_id
JOIN {S}statuses s ON s.id = p.status_id
JOIN {S}polaris_bookings b ON b.id = bp.booking_id AND b.tenant_id = 1 AND b.deleted_at IS NULL
JOIN {S}polaris_adjusted_installments a ON a.booking_payment_id = bp.id
JOIN {S}polaris_installments i ON i.id = a.installment_id AND i.deleted_at IS NULL
WHERE p.deleted_at IS NULL AND s.name IN ('Verified', 'Received')
  AND p.deposit_date >= DATEADD(hour, -5, %s::timestamp) AND p.deposit_date < DATEADD(hour, -5, %s::timestamp)
GROUP BY 1, 2, 3, 4, 5, 6""", (START, START, END))
DEP["cat"] = [categorize(n, t) for n, t in zip(DEP.name, DEP.installment_type)]
DEP = DEP[DEP.cat.isin(TARGET_RELATED)].reset_index(drop=True)  # clean index: appended rows must never overwrite
DEP["bucket"] = [bucket(d) for d in DEP.age_days]
DEP["principal"] = pd.to_numeric(DEP.principal).round().astype("int64")

# Manually linked payments (payment_links.json), only while Redshift has no link for them.
links = json.loads((Path(__file__).parent / "payment_links.json").read_text(encoding="utf-8"))
for pid, v in links.items():
    if pid.startswith("_"):
        continue
    m = read_df(f"""SELECT b.id AS booking_id, b.project_id, b.assignee_id, p.amount, i.name, i.installment_type,
               DATEDIFF(day, DATEADD(hour, 5, i.due_date), %s::timestamp) AS age_days
        FROM {S}polaris_payments p
        JOIN {S}statuses s ON s.id = p.status_id
        JOIN {S}polaris_bookings b ON b.booking_number = %s AND b.tenant_id = 1
        LEFT JOIN {S}polaris_installments i ON i.booking_id = b.id AND i.name = %s AND i.deleted_at IS NULL
        WHERE p.id = %s AND s.name IN ('Verified', 'Received') AND p.deleted_at IS NULL
          AND p.deposit_date >= DATEADD(hour, -5, %s::timestamp) AND p.deposit_date < DATEADD(hour, -5, %s::timestamp)
          AND p.id NOT IN (SELECT x.payment_id FROM {S}polaris_bookings_payments x WHERE x.payment_id = %s)""",
                (START, v["booking_number"], v.get("installment_name", ""), int(pid), START, END, int(pid)))
    for r in m.itertuples():
        DEP.loc[len(DEP)] = [int(r.booking_id), r.project_id, r.assignee_id, r.name, r.installment_type, r.age_days,
                             int(r.amount), categorize(r.name, r.installment_type), bucket(r.age_days)]
        print(f"INFO  manual link: payment {pid} -> {v['booking_number']} {int(r.amount):,} ({bucket(r.age_days)})")


def ip_by_booking(aging=None, cats=TARGET_RELATED):
    d = DEP[DEP.cat.isin(cats)]
    if aging:
        d = d[d.bucket.isin(aging)]
    return d.groupby("booking_id").principal.sum()


def actual_rows(aging=None):
    """ROWS with `actual` (targeted bookings, on the chosen row) and `outside_zero` (0-target bookings)."""
    ip = ip_by_booking(aging)
    r = ROWS.copy()
    amt = [int(ip.get(b, 0)) if rn == 1 else 0 for b, rn in zip(r.booking_id, r.rn)]
    r["actual"] = [a if t else 0 for a, t in zip(amt, r.targeted)]
    r["outside_zero"] = [0 if t else a for a, t in zip(amt, r.targeted)]
    return r


def untagged(aging=None):
    """I+P on bookings in no target list this month."""
    d = DEP[~DEP.booking_id.isin(set(ROWS.booking_id))]
    if aging:
        d = d[d.bucket.isin(aging)]
    return d


def sql_actual(user_ids=None, project_ids=None, city_ids=None, unit_ids=None, aging=None):
    r = actual_rows(aging)
    if user_ids is not None:
        r = r[r.user_id.isin(user_ids)]
    if project_ids is not None:
        r = r[r.project_id.isin(project_ids)]
    if city_ids is not None:
        r = r[r.city_id.isin(city_ids)]
    if unit_ids is not None:
        r = r[r.unit_id.isin(unit_ids)]
    a, h = int(r.assigned.sum()), int(r.actual.sum())
    return a, h, rate(h, a)


def sql_propone_staff(user_ids=None):
    where = f"AND t.user_id IN ({','.join(str(int(u)) for u in user_ids)})" if user_ids else ""
    df = read_df(f"""SELECT COALESCE(SUM(t.assigned_target_amount), 0) AS assigned,
                            COALESCE(SUM(t.achieved_amount), 0) AS achieved
                     FROM {S}polaris_targets t
                     WHERE t.tenant_id = 1 AND t.target_date = %s AND t.deleted_at IS NULL {where}""", (MONTH,))
    return int(df.assigned[0]), int(df.achieved[0])


def sql_project_assigned(project_ids=None, city_ids=None):
    where = ""
    if project_ids:
        where += f" AND pt.project_id IN ({','.join(str(int(p)) for p in project_ids)})"
    if city_ids:
        where += f" AND p.city_id IN ({','.join(str(int(c)) for c in city_ids)})"
    df = read_df(f"""SELECT COALESCE(SUM(pt.assigned_target), 0) AS assigned
                     FROM {S}polaris_projects_targets pt
                     JOIN {S}polaris_targets t ON t.id = pt.target_id
                     JOIN {S}polaris_projects p ON p.id = pt.project_id
                     WHERE t.tenant_id = 1 AND t.target_date = %s AND t.deleted_at IS NULL
                       AND pt.deleted_at IS NULL {where}""", (MONTH,))
    return int(df.assigned[0])


def subtree(user_id):
    df = read_df(f"""WITH tree AS (SELECT h.user_id, '/' || COALESCE(h.ancestry || '/', '') || h.id || '/' AS path
                                   FROM {S}hierarchies h WHERE h.tenant_id = 1 AND h.deleted_at IS NULL)
                     SELECT d.user_id FROM tree m JOIN tree d ON d.path LIKE m.path || '%%' WHERE m.user_id = %s""",
                 (user_id,))
    return list(df.user_id.astype(int))


def kpi(d):
    k = d["kpis"]
    return k["assigned"], k["achieved"], k["rate"]


def find(nodes, name):
    for n in nodes:
        if n["name"] == name:
            return n
        hit = find(n["children"], name)
        if hit:
            return hit
    return None


print(f"Month {MONTH}\n")
d = api("/dashboard", month=MONTH)
opts = api("/filters", month=MONTH)
staff_ids = {s["name"]: s["id"] for s in opts["staff"]}
R = actual_rows()

# Totals
check("All staff: assigned / achieved (I+P on targeted bookings) / rate", kpi(d), sql_actual())
check("Assigned = Propone polaris_targets", d["kpis"]["assigned"], sql_propone_staff()[0])
check("Propone reference figure = polaris_targets.achieved_amount", d["kpis"]["propone_achieved"], sql_propone_staff()[1])
check("Each booking's deposit is on one row only", int((R[R.rn == 1].groupby("booking_id").size() > 1).sum()), 0)
check("Pending target = assigned - achieved", d["kpis"]["pending"], sql_actual()[0] - sql_actual()[1])

# Outside targets = 0-target bookings in the list + bookings in no list, I+P only
ut = untagged()
zero_amt, unt_amt = int(R.outside_zero.sum()), int(ut.principal.sum())
zero_b = int(R[R.outside_zero > 0].booking_id.nunique())
unt_b = int(ut[ut.principal > 0].booking_id.nunique())
o = d["kpis"]["outside"]
check("Outside targets KPI: I+P on 0-target bookings", (o["zero_bookings"], o["zero_target_related"]), (zero_b, zero_amt))
check("Outside targets KPI: I+P on bookings in no target list", (o["untagged_bookings"], o["untagged_target_related"]), (unt_b, unt_amt))
check("Outside targets KPI total", (o["bookings"], o["target_related"]), (zero_b + unt_b, zero_amt + unt_amt))
check("Total received = achieved + outside", d["kpis"]["received_total"], sql_actual()[1] + zero_amt + unt_amt)
sec = d["outside_target"]
check("Section 'Money received without a target' = Outside targets KPI", (sec["bookings"], sec["target_related"]), (o["bookings"], o["target_related"]))
check("Section rows add up to the section total", sum(r["target_related"] for r in sec["zero_target"]["rows"] + sec["untagged"]["rows"]), sec["target_related"])
check("Section by-staff adds up to the section total", sum(r["total"] for r in sec["by_staff"]), sec["target_related"])

# Installment / Possession split and aging of Target achieved
tg = set(R[(R.rn == 1) & R.targeted].booking_id)
dep_t = DEP[DEP.booking_id.isin(tg)]
check("Split: Installment + Possession = achieved", (d["kpis"]["split"]["installment"], d["kpis"]["split"]["possession"]),
      (int(dep_t[dep_t.cat == INSTALLMENT].principal.sum()), int(dep_t[dep_t.cat == POSSESSION].principal.sum())))
check("Aging buckets of achieved", d["kpis"]["aging"], {k: int(dep_t[dep_t.bucket == k].principal.sum()) for k in AGING})
check("Aging buckets add up to achieved", sum(d["kpis"]["aging"].values()), d["kpis"]["achieved"])
for k in ("d90_plus", "current"):
    dk = api("/dashboard", month=MONTH, aging=[k])
    check(f"Aging filter = {k}: achieved", kpi(dk), sql_actual(aging=[k]))
    utk = untagged([k]); Rk = actual_rows([k])
    check(f"Aging filter = {k}: outside targets", dk["kpis"]["outside"]["target_related"], int(Rk.outside_zero.sum()) + int(utk.principal.sum()))
    check(f"Aging filter = {k}: assigned unchanged", dk["kpis"]["assigned"], d["kpis"]["assigned"])
two_b = api("/dashboard", month=MONTH, aging=["d60_90", "d90_plus"])
check("Aging filter = 60-90 + 90+: achieved", kpi(two_b), sql_actual(aging=["d60_90", "d90_plus"]))

# Bookings
check("Target bookings = bookings with an assigned target", d["kpis"]["bookings_with_target"], int(R[R.targeted].booking_id.nunique()))
check("Bookings with achievement (targeted & money received)", d["kpis"]["bookings_with_achievement"], int(R[R.actual > 0].booking_id.nunique()))
check("Bookings in the list", d["kpis"]["bookings_in_list"], int(R.booking_id.nunique()))

# Manager roll-ups
for name in ["Arman Yousaf", "Abdul Wahab Mian", "Ajlal Haider", "Sadaf Munir", "Muhammad Arif", "Ramsha Ramzan"]:
    node = find(d["hierarchy"], name)
    got = (node["assigned"], node["achieved"], node["rate"]) if node else None
    check(f"Hierarchy row {name}", got, sql_actual(user_ids=subtree(staff_ids[name])))
# Hierarchy 'received' = achieved + 0-target money of the subtree + untagged money of bookings assigned to the subtree
for name in ["Arman Yousaf", "Sadaf Munir"]:
    node = find(d["hierarchy"], name)
    ids = set(subtree(staff_ids[name]))
    exp = sql_actual(user_ids=ids)[1] + int(R[R.user_id.isin(ids)].outside_zero.sum()) + int(ut[ut.assignee_id.isin(ids)].principal.sum())
    check(f"Hierarchy row {name}: received incl. outside", node["received"], exp)

# Multi-select
two = [staff_ids["Sadaf Munir"], staff_ids["Ajlal Haider"]]
check("Staff = Sadaf Munir + Ajlal Haider", kpi(api("/dashboard", month=MONTH, staff_id=two)),
      sql_actual(user_ids=subtree(two[0]) + subtree(two[1])))
overlap = [staff_ids["Abdul Wahab Mian"], staff_ids["Sadaf Munir"], staff_ids["Ramsha Ramzan"]]
check("Staff = Abdul Wahab + Sadaf + Ramsha (overlapping, no double count)",
      kpi(api("/dashboard", month=MONTH, staff_id=overlap)), sql_actual(user_ids=subtree(overlap[0])))
cities = {c["label"]: c["id"] for c in opts["cities"]}
sel = [cities["Lahore"], cities["Multan"]]
dc = api("/dashboard", month=MONTH, city_id=sel)
check("City = Lahore + Multan", kpi(dc), sql_actual(city_ids=sel))
check("City = Lahore + Multan assigned = Propone project targets", dc["kpis"]["assigned"], sql_project_assigned(city_ids=sel))
pcity = read_df(f"SELECT id AS project_id, city_id FROM {S}polaris_projects WHERE tenant_id = 1")
city_projects = set(pcity[pcity.city_id.isin(sel)].project_id.astype(int))
exp_out = int(R[R.city_id.isin(sel)].outside_zero.sum()) + int(ut[ut.project_id.isin(city_projects)].principal.sum())
check("City = Lahore + Multan: outside targets", dc["kpis"]["outside"]["target_related"], exp_out)
projs = [p["id"] for p in opts["projects"][:3]]
check(f"Project = 3 projects {projs}", kpi(api("/dashboard", month=MONTH, project_id=projs)), sql_actual(project_ids=projs))
units = [u["id"] for u in api("/filters", month=MONTH, project_id=projs[0])["units"][:5]]
check("Unit = 5 units", kpi(api("/dashboard", month=MONTH, unit_id=units)), sql_actual(unit_ids=units))
combo = api("/dashboard", month=MONTH, staff_id=two, city_id=sel)["kpis"]
check("Staff (2) x City (2) is a subset of each", combo["assigned"] <= min(
    api("/dashboard", month=MONTH, staff_id=two)["kpis"]["assigned"], dc["kpis"]["assigned"]), True)

# Regions
check("City labels (Pindi merged into North)", sorted(c["label"] for c in opts["cities"]), sorted(["Lahore", "North", "Multan"]))
check("City = North equals projects in North + Pindi (85475 + 85683)",
      kpi(api("/dashboard", month=MONTH, city_id=cities["North"])), sql_actual(city_ids=[85475, 85683]))
check("No numeric city ids in labels", any(ch.isdigit() for c in opts["cities"] for ch in c["label"]), False)

# Hierarchy display
check("Visible hierarchy roots", [n["name"] for n in d["hierarchy"]], ["Arman Yousaf"])
check("Zeeshan / Adil absent from staff filter", sorted({"Zeeshan Khan", "Adil Ahmad Kamal"} & set(staff_ids)), [])

for s in d["by_staff"]:
    if s["has_target"]:
        check(f"Staff {s['name']}", (s["assigned"], s["achieved"], s["rate"]), sql_actual(user_ids=[s["staff_id"]]))
for p in d["by_project"]:
    if p["assigned"] > 0:
        check(f"Project {p['name']}", (p["assigned"], p["achieved"], p["rate"]), sql_actual(project_ids=[p["project_id"]]))
        check(f"Project {p['name']} assigned = Propone project target", p["assigned"], sql_project_assigned(project_ids=[p["project_id"]]))
    exp_o = int(R[R.project_id == p["project_id"]].outside_zero.sum()) + int(ut[ut.project_id == p["project_id"]].principal.sum())
    check(f"Project {p['name']} outside target", p["outside"], exp_o)

# Receivables stored by Propone
stored = read_df(f"""SELECT SUM(t.total_receivable) AS r FROM {S}polaris_targets t
    WHERE t.tenant_id = 1 AND t.target_date = %s AND t.deleted_at IS NULL""", (MONTH,))
check("Receivables summed over staff rows = Propone polaris_targets.total_receivable",
      d["kpis"]["receivables"]["staff_rows_total"], int(stored.r[0]))

print(f"\nINFO  Propone's stored achieved: {sql_propone_staff()[1]:,}   dashboard achieved (I+P on targeted bookings): {d['kpis']['achieved']:,}"
      f"   outside targets: {d['kpis']['outside']['target_related']:,}   total received: {d['kpis']['received_total']:,}")
print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
