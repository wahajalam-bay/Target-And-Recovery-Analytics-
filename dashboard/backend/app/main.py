"""FastAPI backend for the Propone Target & Recovery dashboard (read-only).

Staff, city, project and unit filters accept several values as repeated query
parameters, e.g. /api/dashboard?month=2026-09-01&staff_id=29&staff_id=287.
"""
import base64
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import service as svc
from .config import BACKEND_DIR, settings
from .db import pool

from logging.handlers import RotatingFileHandler

LOG_DIR = BACKEND_DIR / ".cache"
LOG_DIR.mkdir(exist_ok=True)
_fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
_file = RotatingFileHandler(LOG_DIR / "dashboard.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
_file.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger().addHandler(_file)
for _name in ("uvicorn.access", "uvicorn.error"):
    logging.getLogger(_name).addHandler(_file)
log = logging.getLogger("dashboard")


@asynccontextmanager
async def lifespan(app: FastAPI):
    svc.store.start()
    yield
    svc.store.stop()
    pool.close_all()


app = FastAPI(title="Propone Target & Recovery API", version="1.1.0", lifespan=lifespan)


@app.middleware("http")
async def basic_auth(request, call_next):
    """Password-protect the whole dashboard when DASHBOARD_USER / DASHBOARD_PASSWORD are set
    (needed once it is reachable from outside this PC). Credentials are compared in constant time."""
    if settings.dashboard_user:
        header = request.headers.get("authorization", "")
        ok = False
        if header.startswith("Basic "):
            try:
                user, _, pwd = base64.b64decode(header[6:]).decode("utf-8").partition(":")
                ok = secrets.compare_digest(user, settings.dashboard_user) and secrets.compare_digest(pwd, settings.dashboard_password)
            except (ValueError, UnicodeDecodeError):
                ok = False
        if not ok:
            return Response("Sign in to view the dashboard.", status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="Target & Recovery Analytics", charset="UTF-8"'})
    return await call_next(request)


app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                   allow_methods=["GET"], allow_headers=["*"])

MONTH = Query(None, description="YYYY-MM-01 (defaults to the current target month)")


def _ids(name, desc):
    return Query(default=[], alias=name, description=desc)


def _snapshot():
    try:
        return svc.store.snapshot()
    except Exception as e:  # noqa: BLE001
        log.exception("could not load data from Redshift")
        raise HTTPException(status_code=503, detail=f"Could not load data from Redshift: {str(e)[:200]}")


def _filters(snap, month, staff_ids=(), city_ids=(), project_ids=(), unit_ids=(), aging=()) -> svc.Filters:
    try:
        m = date.fromisoformat(month) if month else svc.default_month(snap)
    except ValueError:
        raise HTTPException(status_code=422, detail="month must look like YYYY-MM-01")
    if month and m.day != 1:
        raise HTTPException(status_code=422, detail="month must be the first day of a month (YYYY-MM-01)")
    uniq = lambda xs: tuple(sorted(set(int(x) for x in xs)))  # noqa: E731
    bad = [a for a in aging if a not in svc.AGING]
    if bad:
        raise HTTPException(status_code=422, detail=f"aging must be one of {list(svc.AGING)}")
    ag = tuple(k for k in svc.AGING if k in set(aging))
    if len(ag) == len(svc.AGING):
        ag = ()  # every bucket selected = no restriction
    return svc.Filters(month=m, staff_ids=uniq(staff_ids), city_ids=uniq(city_ids),
                       project_ids=uniq(project_ids), unit_ids=uniq(unit_ids), aging=ag)


def _meta(snap, f):
    return {
        "month": f.month.isoformat() if f.month else None,
        "refreshed_at": (svc.store.checked_at or snap.loaded_at).isoformat(),  # last time the data was confirmed current
        "reloaded_at": snap.loaded_at.isoformat(),
        "data_last_loaded": snap.data_last_loaded.isoformat() if snap.data_last_loaded else None,
        "data_last_changed": snap.data_last_changed.isoformat() if snap.data_last_changed else None,
        "refresh_seconds": settings.refresh_seconds,
        "refresh_error": svc.store.last_error,
        "data_source": svc.store.data_source,  # live | saved (last good copy while Redshift is unreachable)
        "filters": {"staff_id": list(f.staff_ids), "city_id": list(f.city_ids),
                    "project_id": list(f.project_ids), "unit_id": list(f.unit_ids), "aging": list(f.aging)},
    }


@app.get("/api/health")
def health():
    snap = svc.store._snap
    return {"status": "ok", "snapshot_loaded": snap is not None, "data_source": svc.store.data_source,
            "refreshed_at": (svc.store.checked_at or snap.loaded_at).isoformat() if snap else None,
            "failures": svc.store.failures,
            "last_error": svc.store.last_error}


@app.get("/api/filters")
def filters(month: str | None = MONTH,
            staff_id: list[int] = _ids("staff_id", "narrows the other lists"),
            city_id: list[int] = _ids("city_id", "narrows the other lists"),
            project_id: list[int] = _ids("project_id", "narrows the other lists"),
            unit_id: list[int] = _ids("unit_id", "narrows the other lists"),
            aging: list[str] = _ids("aging", "aging buckets: current, d30_60, d60_90, d90_plus")):
    """Option lists cross-filtered by every other selected dimension."""
    snap = _snapshot()
    f = _filters(snap, month, staff_id, city_id, project_id, unit_id, aging)
    return {"meta": _meta(snap, f), **svc.filter_options(snap, f)}


@app.get("/api/dashboard")
def dashboard(month: str | None = MONTH,
              staff_id: list[int] = _ids("staff_id", "users.id; includes everyone below each person"),
              city_id: list[int] = _ids("city_id", "polaris_projects.city_id"),
              project_id: list[int] = _ids("project_id", "polaris_projects.id"),
              unit_id: list[int] = _ids("unit_id", "polaris_units.id"),
              aging: list[str] = _ids("aging", "aging buckets: current, d30_60, d60_90, d90_plus")):
    snap = _snapshot()
    f = _filters(snap, month, staff_id, city_id, project_id, unit_id, aging)
    df = svc.apply_filters(snap, f)
    kpis = svc.kpis(snap, df, f)
    try:
        categories = svc.categories_section(snap, df, f.month)
    except Exception as e:  # noqa: BLE001 - payments are optional; keep the rest of the page
        log.exception("payment categories failed")
        categories = {"rows": [], "groups": {}, "error": str(e)[:200]}
    try:
        outside = svc.outside_target_section(snap, f, df)
    except Exception as e:  # noqa: BLE001
        log.exception("outside-target section failed")
        outside = {"error": str(e)[:200]}
    return {
        "meta": _meta(snap, f),
        "kpis": kpis,
        "by_staff": svc.by_staff(snap, df, f),
        "by_project": svc.by_project(snap, df, f),
        "categories": categories,
        "outside_target": outside,
        "trend": svc.trend(snap, f),
        "hierarchy": svc.hierarchy(snap, df, f, f.staff_ids),
    }


@app.get("/api/drill/projects")
def drill_projects(staff_id: int, month: str | None = MONTH,
                   city_id: list[int] = _ids("city_id", ""), project_id: list[int] = _ids("project_id", ""),
                   unit_id: list[int] = _ids("unit_id", ""), aging: list[str] = _ids("aging", "")):
    snap = _snapshot()
    f = _filters(snap, month, [staff_id], city_id, project_id, unit_id, aging)
    df = svc.apply_filters(snap, f)
    return {"meta": _meta(snap, f), "staff": snap.users.get(staff_id), "rows": svc.drill_projects(snap, df, f)}


@app.get("/api/drill/bookings")
def drill_bookings(staff_id: int, project_id: int, month: str | None = MONTH,
                   city_id: list[int] = _ids("city_id", ""), unit_id: list[int] = _ids("unit_id", ""),
                   aging: list[str] = _ids("aging", "")):
    snap = _snapshot()
    f = _filters(snap, month, [staff_id], city_id, [project_id], unit_id, aging)
    df = svc.apply_filters(snap, f)
    return {"meta": _meta(snap, f), "staff": snap.users.get(staff_id),
            "project": svc.project_name(snap, project_id), "rows": svc.drill_bookings(snap, df, f.month)}


@app.get("/api/drill/payments")
def drill_payments(booking_id: int, month: str | None = MONTH, aging: list[str] = _ids("aging", "")):
    snap = _snapshot()
    f = _filters(snap, month, aging=aging)
    return {"meta": _meta(snap, f), **svc.drill_payments(snap, booking_id, f)}


@app.get("/api/categories/mapping")
def category_mapping():
    return svc.category_mapping()


# ---------- the built frontend, served from the same port (no dev server needed) ----------
DIST = BACKEND_DIR.parent / "frontend" / "dist"
if (DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        file = DIST / path
        if path and file.is_file():
            return FileResponse(file)
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
