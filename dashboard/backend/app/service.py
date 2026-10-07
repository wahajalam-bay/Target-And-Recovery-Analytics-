"""Snapshot of Propone target data plus the aggregations behind every endpoint.

A background thread reloads the snapshot from Redshift every REFRESH_SECONDS
(only while someone has used the dashboard recently), so API calls are served
from memory and the browser's 60-second polling never waits on Redshift.
"""
import json
import logging
import pickle
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from . import categories as cat
from . import queries as Q
from .cache import TTLCache
from .config import BACKEND_DIR, settings
from .db import pool, read_df

log = logging.getLogger("dashboard.service")

PKT = timezone(timedelta(hours=5))  # Propone stores UTC; business months are Pakistan time
SAVED_DIR = BACKEND_DIR / ".cache"
SAVED_PATH = SAVED_DIR / "last_snapshot.pkl"
SNAPSHOT_VERSION = 5  # bump whenever the facts columns or mappings change
FULL_RELOAD_SECONDS = 1800  # safety: full reload at least every 30 min even if nothing changed
STALE_AFTER_SECONDS = 300   # only warn when data could not be confirmed fresh for 5 minutes
MONEY_COLS = ["assigned", "achieved", "due_amount", "overdue_amount", "total_receivable",
              "rcv_current", "rcv_30_60", "rcv_60_90", "rcv_90_plus",
              "ach_current", "ach_30_60", "ach_60_90", "ach_90_plus"]


@dataclass
class Snapshot:
    facts: pd.DataFrame
    tree: pd.DataFrame        # hierarchy_id, user_id, report_to_id, path, ids(list)
    users: dict
    projects: pd.DataFrame
    units: pd.DataFrame
    manual_raw: pd.DataFrame  # manually linked payments (payment_links.json), raw allocation shape
    loaded_at: datetime
    data_last_loaded: datetime | None
    data_last_changed: datetime | None
    load_seconds: float


class Store:
    def __init__(self):
        self._snap: Snapshot | None = None
        self._lock = threading.Lock()
        self._last_access = time.time()
        self._error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.cache = TTLCache()
        self.payment_months: set[date] = set()
        self.data_source: str = "none"  # none | saved | live
        self._signature = None            # source-table signature of the data on screen
        self._last_full = 0.0             # time of the last full reload
        self._last_success = time.time()  # last time the data was confirmed current (reload or check)
        self.checked_at: datetime | None = None
        self.failures = 0                 # consecutive failed attempts

    # ---------- loading ----------
    def _load(self) -> Snapshot:
        t0 = time.time()
        tenant = (settings.tenant_id,)
        jobs = {
            "facts": (Q.TARGET_FACTS, tenant),
            "tree": (Q.HIERARCHY, tenant),
            "users": (Q.USERS, tenant),
            "projects": (Q.PROJECTS, tenant),
            "units": (Q.UNITS, tenant),
            "fresh": (Q.FRESHNESS, ()),
            "headers": (Q.TARGET_HEADERS, tenant),
            "deposits": (Q.TARGET_DEPOSITS, tenant),
        }
        with ThreadPoolExecutor(max_workers=max(1, settings.pool_size - 1)) as ex:  # one connection stays free for requests
            futures = {k: ex.submit(read_df, sql, p) for k, (sql, p) in jobs.items()}
            res = {k: f.result() for k, f in futures.items()}

        facts = res["facts"]
        facts["target_month"] = pd.to_datetime(facts["target_month"]).dt.date
        for c in MONEY_COLS:
            facts[c] = pd.to_numeric(facts[c], errors="coerce").fillna(0).astype("int64")
        for c in ["user_id", "project_id", "booking_id", "target_id", "project_target_id", "booking_target_id"]:
            facts[c] = facts[c].astype("int64")
        facts["unit_id"] = pd.to_numeric(facts["unit_id"], errors="coerce").astype("Int64")
        facts["city_id"] = pd.to_numeric(facts["city_id"], errors="coerce").astype("Int64")
        # Region merge (city_names.json "_merge"): e.g. Pindi rows carry North's id, so every
        # filter, card and chart treats them as one region. Rows are only relabelled, never duplicated.
        merge = _city_merge()
        if merge:
            facts["city_id"] = facts["city_id"].map(lambda c: merge.get(int(c), int(c)) if pd.notna(c) else c).astype("Int64")
        projects = res["projects"].copy()
        projects["city_id"] = pd.to_numeric(projects["city_id"], errors="coerce").astype("Int64")
        if merge:
            projects["city_id"] = projects["city_id"].map(lambda c: merge.get(int(c), int(c)) if pd.notna(c) else c).astype("Int64")

        tree = res["tree"].copy()
        tree["hierarchy_id"] = tree["hierarchy_id"].astype("int64")
        tree["user_id"] = tree["user_id"].astype("int64")
        tree["report_to_id"] = pd.to_numeric(tree["report_to_id"], errors="coerce").astype("Int64")
        # Same path as the verified SQL: '/' || COALESCE(ancestry || '/', '') || id || '/'
        tree["path"] = [
            "/" + (f"{a}/" if isinstance(a, str) and a.strip() else "") + f"{hid}/"
            for a, hid in zip(tree["ancestry"], tree["hierarchy_id"])]
        tree["ids"] = tree["path"].map(lambda p: [int(x) for x in p.strip("/").split("/") if x])
        tree = tree.drop_duplicates("user_id")

        mismatched = _inconsistent_targets(facts, res["headers"])
        if mismatched:
            raise InconsistentSnapshot(mismatched)

        # Target Achieved = actual Installment + Possession deposits (after the consistency check,
        # which compares Propone's own stored figures).
        manual_raw = _load_manual_raw(facts)
        facts = actual_achievement(facts, res["deposits"], manual_raw)

        users = {int(r.user_id): r.name for r in res["users"].itertuples()}
        fresh = res["fresh"].iloc[0] if len(res["fresh"]) else None
        return Snapshot(
            facts=facts, tree=tree, users=users, projects=projects, units=res["units"], manual_raw=manual_raw,
            loaded_at=datetime.now(timezone.utc),
            data_last_loaded=_ts(fresh["last_loaded"]) if fresh is not None else None,
            data_last_changed=_ts(fresh["last_changed"]) if fresh is not None else None,
            load_seconds=round(time.time() - t0, 2),
        )

    def _source_signature(self):
        df = read_df(Q.SOURCE_SIGNATURE)
        return tuple(sorted((r.tbl, str(r.last_loaded), int(r.n)) for r in df.itertuples()))

    def _mark_success(self):
        self._last_success = time.time()
        self.checked_at = datetime.now(timezone.utc)
        self.failures = 0
        self._error = None

    def refresh(self, force: bool = False):
        """One refresh cycle. A small signature query first; the heavy reload runs only when a source
        table changed in Redshift (or every FULL_RELOAD_SECONDS as a safety net)."""
        sig = self._source_signature()
        unchanged = (not force and self._snap is not None and self.data_source == "live"
                     and sig == self._signature and time.time() - self._last_full < FULL_RELOAD_SECONDS)
        if unchanged:
            # Same data as on screen: keep caches warm, load any newly viewed month, nothing else.
            for key in [k for k in list(self.cache._data) if k and k[0] in ("payments", "untagged")]:
                self.cache.touch(key)
            for m in [m for m in self.payment_months if ("payments", m) not in self.cache._data]:
                self.cache.put(("payments", m), _load_payment_lines(m, self._snap.manual_raw))
                self.cache.put(("untagged", m), _load_untagged_lines(m, self._snap.manual_raw))
            self._mark_success()
            pool.close_all()
            log.debug("source unchanged; reload skipped")
            return
        self._full_refresh()
        self._signature = sig
        self._last_full = time.time()

    def _full_refresh(self):
        snap = self._load()  # raises InconsistentSnapshot while Redshift is mid-reload
        # Pre-load payments for the months people are looking at, so no request waits.
        months_to_warm = set(self.payment_months) | {default_month(snap)}
        warm = {m: _load_payment_lines(m, snap.manual_raw) for m in months_to_warm if m}
        warm_untagged = {m: _load_untagged_lines(m, snap.manual_raw) for m in months_to_warm if m}
        with self._lock:
            self._snap = snap
            self.data_source = "live"
        self._mark_success()
        for m, lines in warm.items():
            self.cache.put(("payments", m), lines)
        for m, lines in warm_untagged.items():
            self.cache.put(("untagged", m), lines)
        log.info("snapshot refreshed: %s fact rows in %.2fs, payments warmed for %s",
                 len(snap.facts), snap.load_seconds, sorted(str(m) for m in warm))
        self._save_to_disk(snap, warm, warm_untagged)
        pool.close_all()  # hold no Redshift sessions between refreshes

    # ---------- last-good copy on disk ----------
    # The dashboard opens instantly from this copy (even with Redshift unreachable) while the
    # background thread tries to get live data. Nothing here changes any figure: it is the
    # exact result of the last successful live load.
    def _save_to_disk(self, snap, payments, untagged):
        try:
            SAVED_DIR.mkdir(exist_ok=True)
            tmp = SAVED_PATH.with_suffix(".tmp")
            with open(tmp, "wb") as fh:
                pickle.dump({"version": SNAPSHOT_VERSION, "snapshot": snap, "payments": payments, "untagged": untagged}, fh)
            tmp.replace(SAVED_PATH)
        except Exception:  # noqa: BLE001 - a failed save must never break serving
            log.exception("could not save snapshot to disk")

    def _load_from_disk(self) -> bool:
        if not SAVED_PATH.exists():
            return False
        try:
            with open(SAVED_PATH, "rb") as fh:
                saved = pickle.load(fh)
            if saved.get("version") != SNAPSHOT_VERSION:
                log.info("saved snapshot is an older version; waiting for live data instead")
                return False
            snap = saved["snapshot"]
            with self._lock:
                self._snap = snap
                self.data_source = "saved"
                self._last_success = 0.0  # saved copy: never "recent" until live data arrives
            for m, lines in saved.get("payments", {}).items():
                self.cache.put(("payments", m), lines)
                self.payment_months.add(m)
            for m, lines in saved.get("untagged", {}).items():
                self.cache.put(("untagged", m), lines)
            log.info("serving saved snapshot from %s (loaded %s) until live data arrives",
                     SAVED_PATH.name, snap.loaded_at.isoformat())
            return True
        except Exception:  # noqa: BLE001
            log.exception("saved snapshot unreadable; ignoring it")
            return False

    def snapshot(self) -> Snapshot:
        self._last_access = time.time()
        if self._snap is None:
            with self._lock:
                if self._snap is None:
                    # Very first start with nothing saved: one live attempt (fails fast if the
                    # cluster is unreachable; InconsistentSnapshot is retried by the loop).
                    self._snap = self._load()
                    self.data_source = "live"
        return self._snap

    @staticmethod
    def failure_reason(e: Exception) -> str:
        """Plain-language reason for the header (the technical text goes to the log)."""
        if isinstance(e, InconsistentSnapshot):
            return "Propone data is being reloaded into Redshift"
        msg = str(e)
        if "connection time out" in msg or "10060" in msg or "10061" in msg or "10065" in msg:
            return "Redshift is not reachable from this network"
        if "too many connections" in msg:
            return "Redshift login has too many open sessions"
        if "57014" in msg or "cancelled" in msg or "timed out" in msg or "abort query" in msg:
            return "Redshift is busy; a query took too long"
        return "Redshift refresh failed"

    def handle_failure(self, e: Exception) -> float:
        """Record a failed cycle; returns seconds until the next attempt. The header only shows a
        warning once the data on screen could not be confirmed current for STALE_AFTER_SECONDS,
        so a single slow query never turns the banner red."""
        self.failures += 1
        stale = self._snap is None or time.time() - self._last_success > STALE_AFTER_SECONDS
        reason = self.failure_reason(e)
        self._error = reason if stale else None
        log.warning("refresh attempt %s failed (%s: %s); %s", self.failures, reason, str(e)[:160],
                    "showing delayed-data notice" if stale else "data still recent, no notice")
        pool.close_all()
        return 15 if isinstance(e, InconsistentSnapshot) else min(settings.refresh_seconds, 30)

    def _loop(self):
        wait = 0.5  # try live data straight away at startup
        while not self._stop.wait(wait):
            wait = settings.refresh_seconds
            if time.time() - self._last_access > 300:  # nobody watching: stay idle
                continue
            try:
                self.refresh()
            except Exception as e:  # noqa: BLE001 - keep serving the last good snapshot
                wait = self.handle_failure(e)

    def start(self):
        self._load_from_disk()
        self._thread = threading.Thread(target=self._loop, name="snapshot-refresh", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    @property
    def last_error(self):
        return self._error


class InconsistentSnapshot(Exception):
    """Booking-level rows do not add up to Propone's staff-level totals (load in progress)."""


def _inconsistent_targets(facts: pd.DataFrame, headers: pd.DataFrame) -> int:
    """Number of staff targets whose booking-level sums differ from polaris_targets."""
    h = headers.copy()
    h["target_id"] = h["target_id"].astype("int64")
    for c in ("assigned", "achieved"):
        h[c] = pd.to_numeric(h[c], errors="coerce").fillna(0).astype("int64")
    sums = facts.groupby("target_id")[["assigned", "achieved"]].sum()
    j = h.set_index("target_id").join(sums, rsuffix="_rows").fillna(0)
    bad = (j.assigned != j.assigned_rows) | (j.achieved != j.achieved_rows)
    return int(bad.sum())


# ---------- Target Achieved from actual deposits ----------
def _manual_links() -> dict:
    """backend/payment_links.json: {payment_id: {booking_number, installment_name, source}}."""
    path = BACKEND_DIR / "payment_links.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {int(k): v for k, v in data.items() if not str(k).startswith("_")}
    except (OSError, ValueError):
        return {}


def _load_manual_raw(facts: pd.DataFrame) -> pd.DataFrame:
    """Manually linked payments in the same raw shape as PAYMENT_ALLOCATIONS / UNTAGGED_PAYMENTS
    (one full allocation to the named installment), with target_month and in_target flags.
    A link is dropped automatically as soon as Redshift has a real booking link for the payment."""
    frames = []
    for pid, v in _manual_links().items():
        try:
            if int(read_df(Q.MANUAL_PAYMENT_LINKED, (pid,)).n[0]):
                continue  # Redshift now has the real link: the manual one is ignored
            pay = read_df(Q.MANUAL_PAYMENT, (pid, settings.tenant_id))
            bk = read_df(Q.MANUAL_BOOKING, (str(v["booking_number"]), settings.tenant_id))
            if pay.empty or bk.empty:
                log.warning("manual payment link %s: payment or booking %s not found / not verified", pid, v.get("booking_number"))
                continue
            inst = read_df(Q.MANUAL_INSTALLMENT, (int(bk.booking_id[0]), str(v.get("installment_name") or "")))
            row = pay.head(1).reset_index(drop=True).join(bk.head(1).reset_index(drop=True))
            if inst.empty:
                for c in ("installment_id", "installment_name", "installment_type", "installment_due_date"):
                    row[c] = None
            else:
                row = row.join(inst.head(1).reset_index(drop=True))
        except Exception:  # noqa: BLE001 - a bad manual entry must not stop the dashboard
            log.exception("manual payment link %s could not be read", pid)
            continue
        frames.append(row)
    if not frames:
        return pd.DataFrame()
    raw = pd.concat(frames, ignore_index=True)
    raw["payment_amount"] = pd.to_numeric(raw["payment_amount"], errors="coerce").fillna(0)
    raw["booking_id"] = raw["booking_id"].astype("int64")
    raw["booking_payment_id"] = -raw["payment_id"].astype("int64")  # synthetic, never clashes with real ids
    raw["allocation_id"] = [(-int(p) if pd.notna(i) else None) for p, i in zip(raw.payment_id, raw.installment_id)]
    raw["allocated_amount"] = [(a if pd.notna(i) else 0) for a, i in zip(raw.payment_amount, raw.installment_id)]
    for c in ("late_charges", "income_tax", "sales_tax", "cancellation_fee"):
        raw[c] = 0
    raw["target_month"] = (pd.to_datetime(raw["deposit_date_utc"], utc=True).dt.tz_convert("Asia/Karachi")
                           .dt.tz_localize(None).dt.to_period("M").dt.to_timestamp().dt.date)
    in_list = set(zip(facts.target_month, facts.booking_id))
    raw["in_target"] = [(m, b) in in_list for m, b in zip(raw.target_month, raw.booking_id)]
    log.info("manual payment links in use: %s", list(raw.payment_id))
    return raw


def _manual_for(manual_raw, month, in_target: bool, columns) -> pd.DataFrame:
    if manual_raw is None or not len(manual_raw):
        return pd.DataFrame(columns=columns)
    m = manual_raw[(manual_raw.target_month == month) & (manual_raw.in_target == in_target)]
    return m[[c for c in columns if c in m.columns]]


def actual_achievement(facts: pd.DataFrame, deposits: pd.DataFrame, manual_raw: pd.DataFrame) -> pd.DataFrame:
    """Target Achieved from actual money: Installment + Possession deposited in the month.

    Propone's stored figure moves to `propone_achieved`. Per month and booking the deposits are
    split by category (ip_installment / ip_possession) and by aging bucket (ip_current ...), and
    put on ONE target row, so a booking in two staff targets is never counted twice:
      1. the row Propone credited (propone_achieved > 0), else
      2. the row of the booking's own assignee (polaris_bookings.assignee_id), else
      3. the row with the largest assigned target (then the newest row).
    `targeted` = the booking carries an assigned target (> 0) this month. Only targeted bookings'
    deposits are `achieved`; deposits on bookings in the list with a 0 target are `outside_ip`
    (shown with the money received outside targets, never inside Target Achieved)."""
    facts = facts.copy()
    facts["propone_achieved"] = facts["achieved"].astype("int64")
    cols = ["target_month", "booking_id", "installment_name", "installment_type", "installment_due_date", "amount"]
    dep = deposits.copy()
    if len(dep):
        dep["amount"] = pd.to_numeric(dep["principal"], errors="coerce").fillna(0)
        dep = dep[cols]
    else:
        dep = pd.DataFrame(columns=cols)
    if manual_raw is not None and len(manual_raw):
        mr = manual_raw[manual_raw.in_target & manual_raw.installment_id.notna()].copy()
        if len(mr):
            mr["amount"] = mr["payment_amount"]
            dep = pd.concat([dep, mr[cols]], ignore_index=True)
    ip_cols = ["ip_total", "ip_installment", "ip_possession", *IP_COLS.values()]
    if len(dep):
        dep["target_month"] = pd.to_datetime(dep["target_month"]).dt.date
        dep["booking_id"] = dep["booking_id"].astype("int64")
        dep["category"] = [cat.categorize(n, t) for n, t in zip(dep.installment_name, dep.installment_type)]
        dep = dep[dep.category.isin(cat.TARGET_RELATED)].copy()
    if len(dep):
        dep["aging"] = [aging_bucket(d) for d in _age_days(pd.to_datetime(dep.target_month), dep.installment_due_date)]
        g = dep.groupby(["target_month", "booking_id"])
        agg = pd.DataFrame({"ip_total": g.amount.sum()})
        for c, name in (("Installment", "ip_installment"), ("Possession", "ip_possession")):
            agg[name] = dep[dep.category == c].groupby(["target_month", "booking_id"]).amount.sum()
        for k, col in IP_COLS.items():
            agg[col] = dep[dep.aging == k].groupby(["target_month", "booking_id"]).amount.sum()
        agg = agg.fillna(0).round().astype("int64")
    else:
        agg = pd.DataFrame(columns=ip_cols)

    key = pd.MultiIndex.from_arrays([facts.target_month, facts.booking_id])
    per_booking_assigned = facts.groupby(["target_month", "booking_id"]).assigned.sum()
    facts["targeted"] = (per_booking_assigned.reindex(key).values > 0)
    owner = facts.booking_assignee_id.fillna(-1).astype("int64")
    ranked = facts.assign(_cred=(facts.propone_achieved > 0).astype(int),
                          _own=(facts.user_id == owner).astype(int)).sort_values(
        ["_cred", "_own", "assigned", "booking_target_id"], ascending=False)
    chosen = ranked.drop_duplicates(["target_month", "booking_id"])
    facts["credited_row"] = False
    facts.loc[chosen.index, "credited_row"] = True
    ckey = pd.MultiIndex.from_arrays([chosen.target_month, chosen.booking_id])
    for col in ip_cols:
        facts[col] = 0
        if len(agg):
            facts.loc[chosen.index, col] = agg[col].reindex(ckey).fillna(0).astype("int64").values
        facts[col] = facts[col].astype("int64")
    facts["achieved"] = facts.ip_total.where(facts.targeted, 0).astype("int64")
    facts["outside_ip"] = facts.ip_total.where(~facts.targeted, 0).astype("int64")
    lost = (int(agg.ip_total.sum()) if len(agg) else 0) - int(facts.ip_total.sum())
    if lost:
        log.warning("%s of deposits could not be placed on a target row", lost)
    return facts


store = Store()


def _text(v):
    """Plain string or None for optional text fields (customer name)."""
    return None if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "" else str(v).strip()


def _ts(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v):
        return None
    ts = pd.Timestamp(v)
    return (ts.tz_localize("UTC") if ts.tzinfo is None else ts).to_pydatetime()


# ---------- filtering ----------
# Aging buckets (age of an installment at the first day of the target month, Pakistan time):
# Current = due this month or up to 30 days overdue, then 30-60, 60-90 and 90+ days.
# Propone's own receivable buckets use the same boundaries (measured when the target was created).
AGING = ("current", "d30_60", "d60_90", "d90_plus")
AGING_LABELS = {"current": "Current (0–30 days)", "d30_60": "30–60 days", "d60_90": "60–90 days", "d90_plus": "90+ days"}
IP_COLS = {"current": "ip_current", "d30_60": "ip_30_60", "d60_90": "ip_60_90", "d90_plus": "ip_90_plus"}
RCV_COLS = {"current": "rcv_current", "d30_60": "rcv_30_60", "d60_90": "rcv_60_90", "d90_plus": "rcv_90_plus"}


def aging_bucket(days) -> str:
    if days is None or pd.isna(days):
        return "current"
    d = int(days)
    return "current" if d <= 30 else "d30_60" if d <= 60 else "d60_90" if d <= 90 else "d90_plus"


def _age_days(month_start, due_utc) -> pd.Series:
    """Days between an installment's due date (stored as UTC of Pakistan midnight) and the month start."""
    due = (pd.to_datetime(due_utc, errors="coerce", utc=True) + pd.Timedelta(hours=5)).dt.tz_localize(None).dt.normalize()
    return (pd.to_datetime(month_start) - due).dt.days


@dataclass
class Filters:
    """Month is single; staff, city, project, unit and aging accept several values each."""
    month: date | None = None
    staff_ids: tuple = ()
    city_ids: tuple = ()
    project_ids: tuple = ()
    unit_ids: tuple = ()
    aging: tuple = ()


def months(snap: Snapshot) -> list[date]:
    return sorted(snap.facts["target_month"].unique())


def default_month(snap: Snapshot) -> date | None:
    ms = months(snap)
    today = datetime.now(PKT).date().replace(day=1)
    return today if today in ms else (ms[-1] if ms else None)


def subtree_users(snap: Snapshot, staff_ids) -> set[int]:
    """Everyone at or below any of the given people (verified path-prefix logic)."""
    users: set[int] = set()
    for staff_id in staff_ids:
        row = snap.tree[snap.tree.user_id == staff_id]
        users.add(int(staff_id))
        if not row.empty:
            root = row.iloc[0].path
            users |= set(snap.tree.loc[snap.tree.path.str.startswith(root), "user_id"].astype(int))
    return users


def apply_filters(snap: Snapshot, f: Filters, include_month=True) -> pd.DataFrame:
    """Row filter on the booking-target facts. Each fact row is kept at most once, so
    overlapping selections (a manager and someone in their team) never double count.
    An aging selection keeps every row but counts only the deposits on installments in the
    chosen buckets (the assigned target itself cannot be split by age)."""
    df = snap.facts
    m = pd.Series(True, index=df.index)
    if include_month and f.month:
        m &= df.target_month == f.month
    if f.staff_ids:
        m &= df.user_id.isin(subtree_users(snap, f.staff_ids))
    if f.city_ids:
        m &= df.city_id.isin(f.city_ids)
    if f.project_ids:
        m &= df.project_id.isin(f.project_ids)
    if f.unit_ids:
        m &= df.unit_id.isin(f.unit_ids)
    out = df[m]
    if f.aging:
        out = out.copy()
        sel = sum(out[IP_COLS[k]] for k in f.aging if k in IP_COLS)
        for k, col in IP_COLS.items():
            if k not in f.aging:
                out[col] = 0
        out["ip_total"] = sel.astype("int64")
        out["achieved"] = sel.where(out.targeted, 0).astype("int64")
        out["outside_ip"] = sel.where(~out.targeted, 0).astype("int64")
    return out


def hidden_ancestors(snap: Snapshot) -> set[int]:
    """Hierarchy ids above the configured display root (e.g. Zeeshan Khan and Adil Ahmad Kamal
    above Arman Yousaf). They stay in every calculation but are not shown."""
    row = snap.tree[snap.tree.user_id == settings.hierarchy_root_user_id]
    return set(row.iloc[0].ids[:-1]) if len(row) else set()


# ---------- helpers ----------
def _rate(achieved, assigned):
    return round(100.0 * achieved / assigned, 2) if assigned else None


def _money(df: pd.DataFrame) -> dict:
    a, h = int(df.assigned.sum()), int(df.achieved.sum())
    return {"assigned": a, "achieved": h, "pending": a - h, "rate": _rate(h, a)}


def _receivables(df: pd.DataFrame) -> dict:
    """Receivables are repeated on every staff row of a shared booking: count once per booking+month.
    `staff_rows_total` is the plain sum over staff rows, which is how Propone's stored
    polaris_targets / polaris_projects_targets.total_receivable add up."""
    one = df.drop_duplicates(["target_month", "booking_id"])
    return {
        "total": int(one.total_receivable.sum()),
        "staff_rows_total": int(df.total_receivable.sum()),
        "shared_bookings": int(df.groupby("booking_id").user_id.nunique().gt(1).sum()) if len(df) else 0,
        "current": int(one.rcv_current.sum()), "d30_60": int(one.rcv_30_60.sum()),
        "d60_90": int(one.rcv_60_90.sum()), "d90_plus": int(one.rcv_90_plus.sum()),
    }


def booking_counts(df: pd.DataFrame) -> dict:
    """Bookings that carry an assigned target this month (each booking once, even when two staff
    share it), how many of them have an achievement, and the whole target list for reference."""
    per_booking = df.groupby("booking_id").agg(assigned=("assigned", "sum"), achieved=("achieved", "sum"))
    targeted = per_booking[per_booking.assigned > 0]
    return {
        "bookings": int(len(targeted)),
        "bookings_with_target": int(len(targeted)),
        "bookings_with_achievement": int((targeted.achieved > 0).sum()),
        "bookings_in_list": int(len(per_booking)),
        "units": int(df.loc[df.targeted, "unit_id"].nunique()),
    }


def project_name(snap, pid):
    r = snap.projects[snap.projects.project_id == pid]
    return r.iloc[0].project_name if len(r) else f"Project {pid}"


def _unit_labels(snap: Snapshot) -> dict:
    u = snap.units
    return {int(r.unit_id): (r.unit_number or r.unit_name or f"Unit {r.unit_id}") for r in u.itertuples()}


def _city_names() -> dict:
    """Optional backend/city_names.json ({"85572": "Lahore"}); Propone has no readable city table."""
    path = BACKEND_DIR / "city_names.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): v for k, v in data.items() if not k.startswith("_")}
    except (OSError, ValueError):
        return {}


def _city_merge() -> dict:
    """{from_city_id: to_city_id} from city_names.json "_merge" (e.g. Pindi -> North)."""
    path = BACKEND_DIR / "city_names.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8")).get("_merge", {})
        return {int(k): int(v) for k, v in raw.items()}
    except (OSError, ValueError):
        return {}


def city_label(city_id) -> str:
    """Display name only; numeric city ids are never shown to users."""
    return _city_names().get(str(city_id)) or "Other city"


# ---------- outside-target money (Installment + Possession only) ----------
def _ip_lines(lines: pd.DataFrame, f: Filters) -> pd.DataFrame:
    """Installment + Possession allocation lines, narrowed to the selected aging buckets."""
    if not len(lines):
        return lines
    out = lines[lines.category.isin(cat.TARGET_RELATED)]
    if f.aging:
        out = out[out.aging.isin(f.aging)]
    return out


def _untagged_filtered(snap: Snapshot, f: Filters) -> pd.DataFrame:
    """I+P deposited this month on bookings in NO staff target, under the current filters
    (staff = the booking's assignee and everyone below the selected people)."""
    if not f.month:
        return pd.DataFrame()
    u = _ip_lines(untagged_lines(f.month), f)
    if not len(u):
        return u
    pcity = dict(zip(snap.projects.project_id, snap.projects.city_id))
    m = pd.Series(True, index=u.index)
    if f.staff_ids:
        m &= u.assignee_id.isin(subtree_users(snap, f.staff_ids))
    if f.city_ids:
        m &= u.project_id.map(pcity).isin(f.city_ids)
    if f.project_ids:
        m &= u.project_id.isin(f.project_ids)
    if f.unit_ids:
        m &= u.unit_id.isin(f.unit_ids)
    return u[m]


def _outside_parts(snap: Snapshot, f: Filters, df: pd.DataFrame):
    """(zero-target rows of the facts, untagged I+P lines) = everything received without a target."""
    zero = df[(~df.targeted) & (df.outside_ip > 0)] if len(df) else df
    return zero, _untagged_filtered(snap, f)


def _by_key(zero: pd.DataFrame, u: pd.DataFrame, zero_key: str, u_key: str) -> pd.Series:
    """Outside-target I+P summed per user / project: zero-target rows plus untagged lines."""
    a = zero.groupby(zero_key).outside_ip.sum() if len(zero) else pd.Series(dtype="int64")
    b = u.dropna(subset=[u_key]).groupby(u_key).amount.sum() if len(u) else pd.Series(dtype="int64")
    b.index = b.index.astype("int64")
    return a.add(b, fill_value=0).astype("int64")


def received_split(snap: Snapshot, df: pd.DataFrame, f: Filters) -> dict:
    """Target Achieved split into Installment vs Possession, from the same deposit lines.
    Restricted to the credited rows in scope, so it adds up to the KPI exactly."""
    empty = {"installment": 0, "possession": 0, "total": 0, "payments": 0}
    if not f.month or not len(df):
        return empty
    ids = set(df.loc[df.targeted & df.credited_row, "booking_id"])
    lines = _ip_lines(payment_lines(f.month), f)
    lines = lines[lines.booking_id.isin(ids)] if len(lines) else lines
    if not len(lines):
        return empty
    return {"installment": int(lines[lines.category == cat.INSTALLMENT].amount.sum()),
            "possession": int(lines[lines.category == cat.POSSESSION].amount.sum()),
            "total": int(lines.amount.sum()), "payments": int(lines.payment_id.nunique())}


def aging_of(df: pd.DataFrame, only_targeted=True) -> dict:
    d = df[df.targeted] if only_targeted and len(df) else df
    return {k: int(d[col].sum()) if len(d) else 0 for k, col in IP_COLS.items()}


def kpis(snap: Snapshot, df: pd.DataFrame, f: Filters) -> dict:
    base = {**_money(df), **booking_counts(df)}
    zero, u = _outside_parts(snap, f, df)
    zero_amt = int(zero.outside_ip.sum()) if len(zero) else 0
    unt_amt = int(u.amount.sum()) if len(u) else 0
    zero_b = int(zero.booking_id.nunique()) if len(zero) else 0
    unt_b = int(u.booking_id.nunique()) if len(u) else 0
    # Untagged money that no staff row can carry: booking without an assignee, or an assignee
    # outside the staff hierarchy. Reported so the hierarchy total can be reconciled to the KPI.
    in_tree = set(snap.tree.user_id.astype(int))
    unplaced = int(u[u.assignee_id.isna() | ~u.assignee_id.fillna(-1).astype("int64").isin(in_tree)].amount.sum()) if len(u) else 0
    return {
        **base,
        "staff": int(df.user_id.nunique()), "projects": int(df.project_id.nunique()),
        "propone_achieved": int(df.propone_achieved.sum()) if len(df) else 0,
        "receivables": _receivables(df),
        "outside": {"bookings": zero_b + unt_b, "target_related": zero_amt + unt_amt,
                    "zero_bookings": zero_b, "zero_target_related": zero_amt,
                    "untagged_bookings": unt_b, "untagged_target_related": unt_amt,
                    "unplaced": unplaced},
        "received_total": base["achieved"] + zero_amt + unt_amt,
        "aging": aging_of(df),
        "split": received_split(snap, df, f),
    }


# ---------- sections ----------
def _without(f: Filters, dim: str) -> Filters:
    """The same filters with one dimension cleared: each option list is narrowed by the
    OTHER selected dimensions, so the user can still add more values of its own kind."""
    return Filters(month=f.month,
                   staff_ids=() if dim == "staff" else f.staff_ids,
                   city_ids=() if dim == "city" else f.city_ids,
                   project_ids=() if dim == "project" else f.project_ids,
                   unit_ids=() if dim == "unit" else f.unit_ids,
                   aging=f.aging)


def filter_options(snap: Snapshot, f: Filters) -> dict:
    """Cross-filtered option lists: choosing a project narrows staff, cities and units to the
    ones that have target rows for it (and so on for every dimension). Values already selected
    stay in their own list so they can be deselected. Uses the same verified row filter as the
    figures themselves (apply_filters), so options and numbers always agree."""
    hidden = hidden_ancestors(snap)
    labels = _unit_labels(snap)
    pnames = dict(zip(snap.projects.project_id, snap.projects.project_name))

    # Staff: people (or managers whose team) with target rows in the narrowed data.
    staff_df = apply_filters(snap, _without(f, "staff"))
    staff_with_targets = set(staff_df.user_id.unique()) | set(f.staff_ids)
    nodes = []
    for r in snap.tree.sort_values("path").itertuples():
        if r.hierarchy_id in hidden:
            continue
        below = snap.tree.loc[snap.tree.path.str.startswith(r.path), "user_id"]
        if any(u in staff_with_targets for u in below):
            nodes.append({"id": int(r.user_id), "name": snap.users.get(int(r.user_id), f"User {r.user_id}"),
                          "level": len([i for i in r.ids if i not in hidden]),
                          "has_target": int(r.user_id) in set(staff_df.user_id.unique())})

    # Projects and cities.
    proj_ids = set(apply_filters(snap, _without(f, "project")).project_id.unique()) | set(f.project_ids)
    projects = snap.projects[snap.projects.project_id.isin(proj_ids)].sort_values("project_name")
    city_df = apply_filters(snap, _without(f, "city"))
    city_ids = set(int(c) for c in city_df.city_id.dropna().unique()) | set(f.city_ids)
    cities = []
    for cid, g in snap.projects[snap.projects.city_id.isin(city_ids)].groupby("city_id"):
        cities.append({"id": int(cid), "label": city_label(int(cid)), "projects": sorted(g.project_name)})

    # Units.
    unit_df = apply_filters(snap, _without(f, "unit"))
    units = unit_df.dropna(subset=["unit_id"]).drop_duplicates("unit_id")[["unit_id", "project_id"]]
    if f.unit_ids:
        extra = snap.facts[snap.facts.unit_id.isin(f.unit_ids) & ~snap.facts.unit_id.isin(units.unit_id)]
        units = pd.concat([units, extra.drop_duplicates("unit_id")[["unit_id", "project_id"]]])

    return {
        "months": [m.isoformat() for m in months(snap)],
        "aging": [{"id": k, "label": AGING_LABELS[k]} for k in AGING],
        "staff": nodes,
        "cities": sorted(cities, key=lambda c: -len(c["projects"])),
        "projects": [{"id": int(p.project_id), "name": p.project_name, "city_id": int(p.city_id)}
                     for p in projects.itertuples()],
        "units": sorted(({"id": int(u.unit_id), "label": labels.get(int(u.unit_id), f"Unit {u.unit_id}"),
                          "project": pnames.get(int(u.project_id), "")} for u in units.itertuples()),
                        key=lambda x: (x["project"], x["label"])),
    }


def hierarchy(snap: Snapshot, df: pd.DataFrame, f: Filters, staff_ids=()) -> list[dict]:
    """Expandable staff tree. A manager's total = sum over everyone below (verified path logic).
    Totals are computed on the full tree; only the display starts at the configured root.
    Each node also carries `outside` (I+P received without a target: zero-target bookings of the
    person plus untagged bookings they are assignee of) and `received` = achieved + outside."""
    cols = {"assigned": ("assigned", "sum"), "achieved": ("achieved", "sum"), "outside": ("outside_ip", "sum")}
    cols.update({k: (col, "sum") for k, col in IP_COLS.items()})
    per_user = df.groupby("user_id").agg(**cols) if len(df) else pd.DataFrame(columns=list(cols))
    zero, u = _outside_parts(snap, f, df)
    unt_by_user = (u.dropna(subset=["assignee_id"]).groupby("assignee_id").amount.sum() if len(u) else pd.Series(dtype="int64"))
    unt_by_user.index = unt_by_user.index.astype("int64")
    for uid, amt in unt_by_user.items():
        if uid not in per_user.index:
            per_user.loc[uid] = 0
        per_user.loc[uid, "outside"] += int(amt)
    per_user = per_user.fillna(0).astype("int64")
    bookings_by_user = df[df.targeted].groupby("user_id").booking_id.agg(lambda s: set(s)) if len(df) else pd.Series(dtype=object)
    tree = snap.tree.set_index("hierarchy_id")
    by_user = snap.tree.set_index("user_id")
    totals: dict[int, dict] = {}
    for uid, row in per_user.iterrows():
        uid = int(uid)
        ids = by_user.loc[uid, "ids"] if uid in by_user.index else []
        if not ids:  # has a target but no hierarchy row: show at root level
            ids = [-uid]
        for hid in ids:
            t = totals.setdefault(hid, {"assigned": 0, "achieved": 0, "outside": 0, "bookings": set(), "staff": set(),
                                        "aging": {k: 0 for k in AGING}})
            t["assigned"] += int(row.assigned)
            t["achieved"] += int(row.achieved)
            t["outside"] += int(row.outside)
            for k in AGING:
                t["aging"][k] += int(row[k])
            t["bookings"] |= bookings_by_user.get(uid, set())
            t["staff"].add(uid)

    def node(hid):
        uid = -hid if hid < 0 else int(tree.loc[hid, "user_id"])
        t = totals[hid]
        own = per_user.loc[uid] if uid in per_user.index else None
        received = t["achieved"] + t["outside"]
        return {
            "key": str(hid), "staff_id": uid, "name": snap.users.get(uid, f"User {uid}"),
            "assigned": t["assigned"], "achieved": t["achieved"], "pending": t["assigned"] - t["achieved"],
            "rate": _rate(t["achieved"], t["assigned"]),
            "outside": t["outside"], "received": received, "rate_received": _rate(received, t["assigned"]),
            "aging": t["aging"], "bookings": len(t["bookings"]),
            "team_size": len(t["staff"] - {uid}),
            "has_own_target": own is not None and int(own.assigned) > 0,
            "own_assigned": int(own.assigned) if own is not None else 0,
            "own_achieved": int(own.achieved) if own is not None else 0,
            "children": [],
        }

    nodes = {hid: node(hid) for hid in totals}
    hidden = hidden_ancestors(snap)
    roots = []
    for hid, n in nodes.items():
        parent = None
        if hid > 0:
            ids = tree.loc[hid, "ids"]
            parent = ids[-2] if len(ids) > 1 else None
        if parent is not None and parent in nodes:
            nodes[parent]["children"].append(n)
        if hid not in hidden and (parent is None or parent not in nodes or parent in hidden):
            roots.append(n)  # display root: first visible level (Arman Yousaf and any other branch)
    for n in nodes.values():
        n["children"].sort(key=lambda c: (-c["assigned"], -c["received"]))
    if staff_ids:
        # Show each selected person's branch once; skip people already inside another selected branch.
        chosen = {hid for hid, n in nodes.items() if n["staff_id"] in set(staff_ids)}
        tops = [nodes[h] for h in chosen
                if h < 0 or not any(a in chosen for a in tree.loc[h, "ids"][:-1])]
        return sorted(tops, key=lambda c: -c["assigned"])
    return sorted(roots, key=lambda c: -c["assigned"])


def by_staff(snap, df, f: Filters):
    """One row per person with target rows (plus people who only received money outside targets,
    flagged has_target=False so the default view can hide them)."""
    managers = dict(zip(snap.tree.user_id, snap.tree.report_to_id))
    cols = {"assigned": ("assigned", "sum"), "achieved": ("achieved", "sum"), "outside": ("outside_ip", "sum"),
            "bookings": ("booking_id", "nunique"), "projects": ("project_id", "nunique")}
    cols.update({k: (col, "sum") for k, col in IP_COLS.items()})
    g = df.groupby("user_id").agg(**cols) if len(df) else pd.DataFrame(columns=list(cols))
    tb = df[df.targeted].groupby("user_id").booking_id.nunique() if len(df) else pd.Series(dtype="int64")
    zero, u = _outside_parts(snap, f, df)
    unt = (u.dropna(subset=["assignee_id"]).groupby("assignee_id").amount.sum() if len(u) else pd.Series(dtype="int64"))
    unt.index = unt.index.astype("int64")
    for uid, amt in unt.items():
        if uid not in g.index:
            g.loc[uid] = 0
        g.loc[uid, "outside"] += int(amt)
    out = []
    for uid, r in g.iterrows():
        uid = int(uid)
        mgr = managers.get(uid)
        received = int(r.achieved + r.outside)
        out.append({"staff_id": uid, "name": snap.users.get(uid, f"User {uid}"),
                    "manager": snap.users.get(int(mgr)) if mgr is not None and not pd.isna(mgr) else None,
                    "assigned": int(r.assigned), "achieved": int(r.achieved),
                    "pending": int(r.assigned - r.achieved), "rate": _rate(r.achieved, r.assigned),
                    "outside": int(r.outside), "received": received, "rate_received": _rate(received, r.assigned),
                    "aging": {k: int(r[k]) for k in AGING},
                    "bookings": int(tb.get(uid, 0)), "projects": int(r.projects),
                    "has_target": int(r.assigned) > 0})
    return sorted(out, key=lambda x: (-x["assigned"], -x["received"]))


def by_project(snap, df, f: Filters):
    zero, u = _outside_parts(snap, f, df)
    outside = _by_key(zero, u, "project_id", "project_id")
    seen = set(int(p) for p in df.project_id.unique()) if len(df) else set()
    out = []
    for pid, g in df.groupby("project_id"):
        m = _money(g)
        o = int(outside.get(int(pid), 0))
        out.append({"project_id": int(pid), "name": project_name(snap, pid), **m,
                    "outside": o, "received": m["achieved"] + o, "rate_received": _rate(m["achieved"] + o, m["assigned"]),
                    "aging": aging_of(g),
                    "bookings": int(g.loc[g.targeted, "booking_id"].nunique()), "units": int(g.loc[g.targeted, "unit_id"].nunique()),
                    "staff": int(g.user_id.nunique()), "receivables": _receivables(g)["total"]})
    for pid, o in outside.items():  # projects with outside-target money only
        if int(pid) not in seen and o > 0:
            out.append({"project_id": int(pid), "name": project_name(snap, int(pid)), "assigned": 0, "achieved": 0, "pending": 0,
                        "rate": None, "outside": int(o), "received": int(o), "rate_received": None,
                        "aging": {k: 0 for k in AGING}, "bookings": 0, "units": 0, "staff": 0, "receivables": 0})
    return sorted(out, key=lambda x: (-x["assigned"], -x["received"]))


def trend(snap, f: Filters):
    df = apply_filters(snap, f, include_month=False)
    out = []
    for m, g in df.groupby("target_month"):
        out.append({"month": m.isoformat(), **_money(g), "bookings": int(g.booking_id.nunique())})
    return sorted(out, key=lambda x: x["month"])


# ---------- payments ----------
def _month_window_utc(month: date):
    start = datetime(month.year, month.month, 1, tzinfo=PKT)
    end = datetime(month.year + (month.month == 12), month.month % 12 + 1, 1, tzinfo=PKT)
    to_utc = lambda d: d.astimezone(timezone.utc).replace(tzinfo=None)  # noqa: E731
    return to_utc(start), to_utc(end)


def _current_manual():
    snap = store._snap
    return snap.manual_raw if snap is not None else None


def _load_payment_lines(month: date, manual_raw=None) -> pd.DataFrame:
    start, end = _month_window_utc(month)
    raw = read_df(Q.PAYMENT_ALLOCATIONS, (start, end, settings.tenant_id, month))
    extra = _manual_for(manual_raw, month, True, list(raw.columns))
    if len(extra):
        raw = pd.concat([raw, extra], ignore_index=True)
    return explode_components(raw)


def _load_untagged_lines(month: date, manual_raw=None) -> pd.DataFrame:
    start, end = _month_window_utc(month)
    raw = read_df(Q.UNTAGGED_PAYMENTS, (settings.tenant_id, start, end, settings.tenant_id, month))
    extra = _manual_for(manual_raw, month, False, list(raw.columns))
    if len(extra):
        raw = pd.concat([raw, extra], ignore_index=True)
    return explode_components(raw)


def _cached_lines(kind: str, month: date, loader) -> pd.DataFrame:
    """Serve payment lines from the cache; the background refresh keeps them current. Redshift is
    only queried from a request for a month nobody has viewed yet, and never while the last
    refresh failed (the saved copy is served, or an empty frame if that month was never saved)."""
    store.payment_months.add(month)
    key = (kind, month)
    if store.data_source != "live" or store.last_error:
        hit = store.cache._data.get(key)
        if hit:
            return hit[1]
    return store.cache.get_or_load(key, settings.refresh_seconds * 3, loader)


def untagged_lines(month: date) -> pd.DataFrame:
    """Payments deposited in the month on bookings that are in no staff target for that month."""
    return _cached_lines("untagged", month, lambda: _load_untagged_lines(month, _current_manual()))


def payment_lines(month: date) -> pd.DataFrame:
    """Payment allocation lines for one month, one row per category component.
    Kept fresh by the background refresh; loaded on demand the first time a month is viewed."""
    return _cached_lines("payments", month, lambda: _load_payment_lines(month, _current_manual()))


BOOKING_EXTRAS = ["booking_number", "project_id", "unit_id", "assignee_id", "booking_status", "customer"]


def explode_components(raw: pd.DataFrame) -> pd.DataFrame:
    extras = [c for c in BOOKING_EXTRAS if c in raw.columns]  # present for the untagged query
    cols = ["booking_id", "booking_payment_id", "payment_amount", "payment_id", "payment_reference", "deposit_date",
            "payment_status", "installment_id", "installment_name", "installment_type", "installment_due_date",
            *extras, "raw_value", "category", "component", "amount", "age_days", "aging"]
    if raw.empty:
        return pd.DataFrame(columns=cols)
    for c in ["payment_amount", "allocated_amount", "late_charges", "income_tax", "sales_tax", "cancellation_fee"]:
        raw[c] = pd.to_numeric(raw[c], errors="coerce").fillna(0)
    raw["deposit_date"] = (pd.to_datetime(raw["deposit_date_utc"], errors="coerce", utc=True)
                           .dt.tz_convert("Asia/Karachi").dt.strftime("%Y-%m-%d"))
    base = ["booking_id", "booking_payment_id", "payment_amount", "payment_id", "payment_reference", "deposit_date",
            "payment_status", "installment_id", "installment_name", "installment_type", "installment_due_date", *extras]
    lines = []
    alloc = raw[raw.allocation_id.notna()]
    for r in alloc.itertuples(index=False):
        b = {k: getattr(r, k) for k in base}
        late, it, st, cf = r.late_charges, r.income_tax, r.sales_tax, r.cancellation_fee
        principal = r.allocated_amount - late - it - st - cf
        if principal:
            lines.append({**b, "raw_value": r.installment_name, "component": "installment",
                          "category": cat.categorize(r.installment_name, r.installment_type), "amount": principal})
        for amt, raw_v, category, comp in [(late, cat.LATE_RAW, cat.LATE_PAYMENT, "late_charges"),
                                            (it, cat.INCOME_TAX_RAW, cat.TAX_236K, "income_tax"),
                                            (st, cat.SALES_TAX_RAW, cat.TAX_PRA, "sales_tax"),
                                            (cf, cat.CANCELLATION_RAW, cat.CANCELLATION, "cancellation_fee")]:
            if amt:
                lines.append({**b, "raw_value": raw_v, "category": category, "component": comp, "amount": amt})
    # Part of a payment not allocated to any installment.
    per_bp = raw.groupby("booking_payment_id").agg(
        allocated=("allocated_amount", "sum"), payment_type=("payment_type", "first"),
        **{k: (k, "first") for k in base if k != "booking_payment_id"}).reset_index()
    for r in per_bp.itertuples(index=False):
        rest = r.payment_amount - r.allocated
        if rest > 0:
            b = {k: getattr(r, k) for k in base}
            b.update(installment_id=None, installment_name=None, installment_type=None, installment_due_date=None)
            transfer = pd.notna(r.payment_type) and int(r.payment_type) == 3 and r.allocated == 0
            lines.append({**b, "raw_value": cat.TRANSFER_RAW if transfer else cat.UNALLOCATED_RAW,
                          "category": cat.TRANSFER_FEE if transfer else cat.UNALLOCATED,
                          "component": "unallocated", "amount": rest})
    out = pd.DataFrame(lines, columns=cols)
    out["amount"] = out["amount"].astype("int64")
    # Aging of the installment paid, at the first day of the deposit month (the target month).
    month_start = pd.to_datetime(out["deposit_date"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    out["age_days"] = _age_days(month_start, out["installment_due_date"]) if len(out) else pd.Series(dtype="float")
    out["aging"] = [aging_bucket(d) if pd.notna(d) else None for d in out["age_days"]]
    over = per_bp[per_bp.allocated > per_bp.payment_amount]
    if len(over):  # allocations larger than the payment itself: surfaced, never hidden
        log.warning("%s payments allocated above their amount (%s): %s", len(over),
                    int((over.allocated - over.payment_amount).sum()), list(over.booking_payment_id)[:10])
    return out


def paid_total(lines: pd.DataFrame) -> int:
    """Actual money paid (each payment once), to reconcile against the category split."""
    return int(lines.drop_duplicates("booking_payment_id").payment_amount.sum()) if len(lines) else 0


def categories_section(snap, df: pd.DataFrame, month: date | None):
    """Payments deposited in the month, split into target-related (Installment, Possession)
    and other collections. The target-related total equals Target Achieved for the same filters."""
    achieved = int(df.achieved.sum()) if len(df) else 0
    empty = {"rows": [], "groups": {}, "payments_total": 0, "achieved_total": achieved,
             "bookings_with_payments": 0}
    if not month or df.empty:
        return empty
    lines = payment_lines(month)
    lines = lines[lines.booking_id.isin(set(df.booking_id))]
    if lines.empty:
        return empty
    total = int(lines.amount.sum())
    rows = []
    for c, g in lines.groupby("category"):
        raw = (g.groupby("raw_value").agg(amount=("amount", "sum"), lines=("amount", "size"))
               .sort_values("amount", ascending=False))
        rows.append({"category": c, "group": cat.group_of(c), "amount": int(g.amount.sum()),
                     "payments": int(g.payment_id.nunique()), "bookings": int(g.booking_id.nunique()),
                     "share": round(100.0 * g.amount.sum() / total, 2) if total else 0,
                     "raw_values": [{"raw_value": str(k), "amount": int(v.amount), "lines": int(v.lines)}
                                    for k, v in raw.head(12).iterrows()],
                     "raw_value_count": int(len(raw))})
    rows.sort(key=lambda r: cat.CATEGORY_ORDER.index(r["category"]) if r["category"] in cat.CATEGORY_ORDER else 99)
    groups = {}
    for key in ("target", "other"):
        g = lines[lines.category.map(cat.group_of) == key]
        groups[key] = {"amount": int(g.amount.sum()), "payments": int(g.payment_id.nunique()),
                       "bookings": int(g.booking_id.nunique()),
                       "share": round(100.0 * g.amount.sum() / total, 2) if total else 0}
    return {"rows": rows, "groups": groups, "payments_total": total, "achieved_total": achieved,
            "paid_total": paid_total(lines), "allocation_gap": total - paid_total(lines),
            "bookings_with_payments": int(lines.booking_id.nunique()),
            "basis": "Payments deposited in the month (PKT) with status Verified/Received, "
                     "split by polaris_adjusted_installments"}


# ---------- money received without a target ----------
def _line_dicts(g: pd.DataFrame) -> list[dict]:
    return [{"deposit_date": r.deposit_date, "payment_reference": None if pd.isna(r.payment_reference) else str(r.payment_reference),
             "status": r.payment_status, "raw_value": r.raw_value, "category": r.category,
             "group": cat.group_of(r.category), "amount": int(r.amount),
             "installment_due_date": None if pd.isna(r.installment_due_date) else str(pd.Timestamp(r.installment_due_date).date()),
             "aging": r.aging, "aging_label": AGING_LABELS.get(r.aging)}
            for r in g.sort_values(["deposit_date", "payment_id"]).itertuples()]


def _split(g: pd.DataFrame) -> dict:
    t = g.category.map(cat.group_of) == "target" if len(g) else pd.Series(dtype=bool)
    return {"target_related": int(g[t].amount.sum()) if len(g) else 0,
            "other": int(g[~t].amount.sum()) if len(g) else 0,
            "total": int(g.amount.sum()) if len(g) else 0}


def outside_target_section(snap: Snapshot, f: Filters, df: pd.DataFrame) -> dict:
    """Installment + Possession received without an assigned target, kept apart from Target Achieved.

    zero_target: bookings IN the month's target list whose assigned target is 0 ("Added in Target").
    untagged:    bookings in NO staff target that month ("Not Added in Target"); attributed to the
                 booking's assignee (polaris_bookings.assignee_id), or "Unassigned".
    The totals here are exactly the Outside targets KPI.
    """
    empty_part = {"bookings": 0, "payments": 0, "target_related": 0, "rows": []}
    if not f.month:
        return {"zero_target": dict(empty_part), "untagged": dict(empty_part), "by_staff": [],
                "bookings": 0, "target_related": 0, "payments": 0}
    labels = _unit_labels(snap)
    pnames = dict(zip(snap.projects.project_id, snap.projects.project_name))
    zero, u = _outside_parts(snap, f, df)
    staff_rows: dict = {}

    def bucket(uid):
        key = int(uid) if uid is not None else None
        return staff_rows.setdefault(key, {"staff_id": key, "name": snap.users.get(key, "Unassigned") if key is not None else "Unassigned",
                                           "zero_target": 0, "untagged": 0})

    pay = _ip_lines(payment_lines(f.month), f) if len(zero) else pd.DataFrame()
    zero_rows = []
    for bid, g in zero.groupby("booking_id"):
        first = g.iloc[0]
        for r in g.itertuples():
            bucket(r.user_id)["zero_target"] += int(r.outside_ip)
        lines = pay[pay.booking_id == bid] if len(pay) else pay
        zero_rows.append({
            "booking_id": int(bid), "booking_number": str(first.booking_number),
            "customer": _text(getattr(first, "customer", None)),
            "unit": labels.get(int(first.unit_id), "") if pd.notna(first.unit_id) else "",
            "project": pnames.get(int(first.project_id), ""),
            "staff": ", ".join(sorted({snap.users.get(int(x), f"User {x}") for x in g.user_id})),
            "target_related": int(g.outside_ip.sum()), "propone_achieved": int(g.propone_achieved.sum()),
            "aging": {k: int(g[col].sum()) for k, col in IP_COLS.items()},
            "payments": int(lines.payment_id.nunique()) if len(lines) else 0,
            "lines": _line_dicts(lines) if len(lines) else []})
    zero_rows.sort(key=lambda r: -r["target_related"])

    untagged_rows = []
    for bid, g in (u.groupby("booking_id") if len(u) else []):
        first = g.iloc[0]
        assignee = int(first.assignee_id) if pd.notna(first.assignee_id) else None
        bucket(assignee)["untagged"] += int(g.amount.sum())
        untagged_rows.append({
            "booking_id": int(bid), "booking_number": str(first.booking_number),
            "customer": _text(getattr(first, "customer", None)),
            "unit": labels.get(int(first.unit_id), "") if pd.notna(first.unit_id) else "",
            "project": pnames.get(int(first.project_id), "") if pd.notna(first.project_id) else "",
            "staff": snap.users.get(assignee, f"User {assignee}") if assignee is not None else "Unassigned",
            "booking_status": first.booking_status, "target_related": int(g.amount.sum()),
            "aging": {k: int(g[g.aging == k].amount.sum()) for k in AGING},
            "payments": int(g.payment_id.nunique()), "lines": _line_dicts(g)})
    untagged_rows.sort(key=lambda r: -r["target_related"])

    by_staff = [dict(v, total=v["zero_target"] + v["untagged"]) for v in staff_rows.values()]
    by_staff = sorted([r for r in by_staff if r["total"]], key=lambda r: -r["total"])
    zt = {"bookings": len(zero_rows), "target_related": sum(r["target_related"] for r in zero_rows),
          "propone_achieved": sum(r["propone_achieved"] for r in zero_rows),
          "payments": sum(r["payments"] for r in zero_rows), "rows": zero_rows}
    ut = {"bookings": len(untagged_rows), "target_related": sum(r["target_related"] for r in untagged_rows),
          "payments": int(u.payment_id.nunique()) if len(u) else 0, "rows": untagged_rows}
    return {"zero_target": zt, "untagged": ut, "by_staff": by_staff,
            "bookings": zt["bookings"] + ut["bookings"], "target_related": zt["target_related"] + ut["target_related"],
            "payments": zt["payments"] + ut["payments"],
            "aging": {k: sum(r["aging"][k] for r in zero_rows + untagged_rows) for k in AGING}}


# ---------- drill-down ----------
def drill_projects(snap, df, f: Filters):
    rows = by_project(snap, df, f)
    for r in rows:
        g = df[df.project_id == r["project_id"]]
        rb = _receivables(g) if len(g) else {"current": 0, "d30_60": 0, "d60_90": 0, "d90_plus": 0}
        if f.aging:
            rb = {k: (v if k in f.aging else 0) for k, v in rb.items()}
        r["receivable_buckets"] = rb
        r["propone_achieved"] = int(g.propone_achieved.sum()) if len(g) else 0
    return rows


def drill_bookings(snap, df, month):
    """Booking rows of one staff member and project: targeted bookings and, after them, bookings
    in the list with a 0 target (their money is `outside`, never `achieved`)."""
    labels = _unit_labels(snap)
    rows = []
    for r in df.sort_values(["targeted", "assigned"], ascending=False).itertuples():
        rows.append({
            "booking_target_id": int(r.booking_target_id), "booking_id": int(r.booking_id),
            "booking_number": str(r.booking_number), "project": project_name(snap, r.project_id),
            "unit": labels.get(int(r.unit_id), "") if pd.notna(r.unit_id) else "",
            "customer": _text(getattr(r, "customer", None)),
            "staff": snap.users.get(int(r.user_id), f"User {r.user_id}"), "staff_id": int(r.user_id),
            "targeted": bool(r.targeted), "credited_row": bool(r.credited_row),
            "assigned": int(r.assigned), "achieved": int(r.achieved), "outside": int(r.outside_ip),
            "received": int(r.ip_total), "pending": int(r.assigned - r.achieved),
            "propone_achieved": int(r.propone_achieved),
            "rate": _rate(r.achieved, r.assigned), "due_amount": int(r.due_amount),
            "overdue_amount": int(r.overdue_amount), "total_receivable": int(r.total_receivable),
            "receivable_buckets": {k: int(getattr(r, col)) for k, col in RCV_COLS.items()},
            "aging": {k: int(getattr(r, col)) for k, col in IP_COLS.items()},
        })
    return rows


def drill_payments(snap, booking_id: int, f: Filters):
    """Installment + Possession allocation lines of one booking in the month (aging filter applied)."""
    month = f.month
    lines = _ip_lines(payment_lines(month), f)
    lines = lines[lines.booking_id == booking_id].sort_values(["deposit_date", "payment_id"])
    tgt = snap.facts[(snap.facts.booking_id == booking_id) & (snap.facts.target_month == month)]
    rows = [{
        "payment_id": int(r.payment_id), "payment_reference": None if pd.isna(r.payment_reference) else str(r.payment_reference),
        "deposit_date": r.deposit_date, "status": r.payment_status,
        "installment": None if pd.isna(r.installment_name) else r.installment_name,
        "installment_due_date": None if pd.isna(r.installment_due_date) else str(pd.Timestamp(r.installment_due_date).date()),
        "aging": r.aging, "aging_label": AGING_LABELS.get(r.aging),
        "raw_value": r.raw_value, "category": r.category, "group": cat.group_of(r.category),
        "component": r.component, "amount": int(r.amount),
    } for r in lines.itertuples()]
    return {"booking_id": booking_id,
            "booking_number": str(tgt.booking_number.iloc[0]) if len(tgt) else None,
            "targeted": bool(tgt.targeted.any()) if len(tgt) else False,
            "target_achieved": int(tgt.achieved.sum()), "target_assigned": int(tgt.assigned.sum()),
            "outside": int(tgt.outside_ip.sum()), "received": int(lines.amount.sum()) if len(lines) else 0,
            "propone_achieved": int(tgt.propone_achieved.sum()),
            "aging": {k: int(lines[lines.aging == k].amount.sum()) if len(lines) else 0 for k in AGING},
            "lines": rows}


def category_mapping():
    def load():
        df = read_df(Q.INSTALLMENT_NAMES, (settings.tenant_id,))
        df["category"] = [cat.categorize(n, t) for n, t in zip(df.installment_name, df.installment_type)]
        return df
    df = store.cache.get_or_load(("mapping",), 600, load)
    summary = df.groupby("category").n.sum().to_dict()
    rows = [{"raw_value": r.installment_name,
             "installment_type": None if pd.isna(r.installment_type) else int(r.installment_type),
             "category": r.category, "group": cat.group_of(r.category), "installments": int(r.n)}
            for r in df.sort_values(["category", "n"], ascending=[True, False]).itertuples()]
    components = [{"raw_value": v, "category": c, "group": cat.group_of(c)} for v, c in [
        (cat.LATE_RAW, cat.LATE_PAYMENT), (cat.INCOME_TAX_RAW, cat.TAX_236K), (cat.SALES_TAX_RAW, cat.TAX_PRA),
        (cat.CANCELLATION_RAW, cat.CANCELLATION), (cat.TRANSFER_RAW, cat.TRANSFER_FEE),
        (cat.UNALLOCATED_RAW, cat.UNALLOCATED)]]
    return {"summary": {k: int(v) for k, v in summary.items()}, "installment_names": rows,
            "allocation_components": components}
