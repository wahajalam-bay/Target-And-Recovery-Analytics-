"""Export the dashboard as one self-contained, offline HTML file (a frozen snapshot).

Usage (backend running on :8000):
    .venv\\Scripts\\python export_snapshot.py [YYYY-MM-01]

The file embeds: the dashboard for the month (no filters), filter lists, and every
drill-down level (staff -> project -> booking -> payments). It needs no server, no
Redshift and no network (fonts fall back to the system font when offline).
It contains internal data (staff names, targets, bookings, payments): share with care.
"""
import base64
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "http://127.0.0.1:8000/api"
ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
BUILD = ROOT / ".snapshot-build"
OUT_DIR = ROOT / "exports"


def key(path, params):
    """Same normalisation as snapshotKey() in frontend/src/lib/api.js."""
    pairs = []
    for k, v in params.items():
        for x in (v if isinstance(v, (list, tuple)) else [v]):
            if x is not None and x != "":
                pairs.append((k, str(x)))
    pairs.sort()
    return path + ("?" + "&".join(f"{k}={v}" for k, v in pairs) if pairs else "")


def get(path, params=None):
    q = urllib.parse.urlencode([(k, v) for k, v in (params or {}).items() if v is not None])
    with urllib.request.urlopen(f"{API}{path}{'?' + q if q else ''}", timeout=300) as r:
        return json.load(r)


def collect(month):
    responses = {}
    dash = get("/dashboard", {"month": month} if month else {})
    month = month or dash["meta"]["month"]
    filters = get("/filters", {"month": month})
    for m in (None, month):  # first request has no month, the second adopts the default
        responses[key("/dashboard", {"month": m})] = dash
        responses[key("/filters", {"month": m})] = filters

    staff = set(s["staff_id"] for s in dash["by_staff"])
    def walk(nodes):
        for n in nodes:
            staff.add(n["staff_id"])
            walk(n["children"])
    walk(dash["hierarchy"])

    with ThreadPoolExecutor(max_workers=4) as ex:
        projects = dict(zip(staff, ex.map(lambda s: get("/drill/projects", {"month": month, "staff_id": s}), staff)))
        for s, body in projects.items():
            responses[key("/drill/projects", {"month": month, "staff_id": s})] = body
        pairs = [(s, r["project_id"]) for s, body in projects.items() for r in body["rows"]]
        bookings = dict(zip(pairs, ex.map(lambda sp: get("/drill/bookings", {"month": month, "staff_id": sp[0], "project_id": sp[1]}), pairs)))
        paid = set()
        for (s, p), body in bookings.items():
            responses[key("/drill/bookings", {"month": month, "staff_id": s, "project_id": p})] = body
            paid |= {r["booking_id"] for r in body["rows"] if r.get("received")}
        paid = sorted(paid)
        for b, body in zip(paid, ex.map(lambda b: get("/drill/payments", {"month": month, "booking_id": b}), paid)):
            responses[key("/drill/payments", {"month": month, "booking_id": b})] = body
    print(f"collected {len(responses)} views: {len(staff)} staff, {len(pairs)} staff-project pairs, {len(paid)} bookings with payments")
    return month, dash, responses


def build_frontend():
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    subprocess.run([npm, "run", "build", "--", "--outDir", str(BUILD), "--emptyOutDir", "--base", "./", "--logLevel", "error"],
                   cwd=FRONTEND, check=True)


def inline(html: str, snapshot_json: str) -> str:
    def script(m):
        js = (BUILD / m.group(1).lstrip("./")).read_text(encoding="utf-8").replace("</script", "<\\/script")
        return f'<script type="module">{js}</script>'
    def style(m):
        css = (BUILD / m.group(1).lstrip("./")).read_text(encoding="utf-8")
        return f"<style>{css}</style>"
    html = re.sub(r'<script type="module" crossorigin src="([^"]+)"></script>', script, html)
    html = re.sub(r'<link rel="stylesheet" crossorigin href="([^"]+)">', style, html)
    svg = (FRONTEND / "public" / "favicon.svg").read_bytes()
    html = re.sub(r'<link rel="icon"[^>]*>', f'<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,{base64.b64encode(svg).decode()}" />', html)
    data = f"<script>window.__DASHBOARD_SNAPSHOT__ = {snapshot_json};</script>"
    return html.replace("</title>", "</title>\n    " + data, 1)


def main():
    month = sys.argv[1] if len(sys.argv) > 1 else None
    month, dash, responses = collect(month)
    build_frontend()
    taken = dash["meta"]["refreshed_at"]
    snapshot = {"taken_at": taken, "month": month, "responses": responses}
    blob = json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    html = inline((BUILD / "index.html").read_text(encoding="utf-8"), blob)
    html = html.replace("<title>Target & Recovery Analytics</title>",
                        f"<title>Target & Recovery Analytics · snapshot {month[:7]}</title>")
    OUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.fromisoformat(taken).astimezone(timezone(timedelta(hours=5))).strftime("%Y-%m-%d_%H%M")
    out = OUT_DIR / f"Target-Recovery-Dashboard_{month[:7]}_snapshot_{stamp}.html"
    out.write_text(html, encoding="utf-8")
    left = re.findall(r'(?:src|href)="\./assets/[^"]+"', html)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB); unresolved asset links: {len(left)}")


if __name__ == "__main__":
    main()
