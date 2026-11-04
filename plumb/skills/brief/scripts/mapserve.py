"""The understanding map and Plumb's local page server. Used through plumb.py (standard library only).

  areas   show the outline and saved areas, or save areas (--set)
  map     write the map page
  open    show the map or a briefing, through the local server when it can start
  serve   run the local server (open starts it; it stops after 30 idle minutes)

Everything is stored under $PLUMB_HOME (default ~/.plumb). Nothing is written inside the project.
"""

import datetime as dt
import html
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

P = None  # the plumb module; set by plumb.py before any function here runs

VERSION = 1
DEPTHS = ("contract", "shape", "every line")  # depth 1, 2, 3; 0 means nothing needed
DEFAULT_DEPTH = 2
AREA_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,60}")
STORE_NAME = re.compile(r"[A-Za-z0-9._-]{1,140}")
BRIEF_ID = re.compile(r"[A-Za-z0-9._-]{1,100}")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "target", ".cache"}
MAX_FILES = 40000
MAX_COUNT_BYTES = 2_000_000
RECENT_DAYS = 7
NEVER_DAYS = 30
DEFAULT_PORT = 7341
IDLE_SECONDS = 30 * 60


def now():
    return dt.datetime.now().astimezone()


def stamp(t=None):
    return (t or now()).strftime("%Y-%m-%d %H:%M")


def parse_stamp(s):
    try:
        return dt.datetime.strptime(str(s)[:16], "%Y-%m-%d %H:%M").astimezone()
    except ValueError:
        return None


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, path)


def git(args, cwd, timeout=30):
    """git's stdout, or None if git isn't there or the folder isn't a repository."""
    try:
        r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def ts(value):
    """An aware datetime from an ISO string, or None."""
    t = P.parse_ts(value)
    return (t if t.tzinfo else t.astimezone()) if t else None


_lock = threading.Lock()  # the server writes from several threads


# --- areas ---------------------------------------------------------------------

def norm_prefix(p):
    return str(p).strip().strip("/").replace("\\", "/")


def validate_areas(a):
    errors = []
    if not isinstance(a, dict) or not isinstance(a.get("areas"), list):
        return ["areas: expected {\"areas\": [...]}"]
    areas = a["areas"]
    if not 1 <= len(areas) <= 30:
        errors.append("areas: give 1 to 30 areas")
    seen, prefixes = set(), {}
    for i, ar in enumerate(areas):
        w = f"areas[{i}]"
        if not isinstance(ar, dict):
            errors.append(f"{w}: expected an object")
            continue
        aid = ar.get("id")
        if not isinstance(aid, str) or not AREA_ID.fullmatch(aid):
            errors.append(f"{w}.id: lowercase letters, digits, dot, dash or underscore")
        elif aid in seen:
            errors.append(f"{w}.id: {aid!r} is used twice")
        seen.add(aid)
        if not isinstance(ar.get("name"), str) or not ar["name"].strip():
            errors.append(f"{w}.name: missing")
        paths = ar.get("paths")
        if not isinstance(paths, list) or not paths:
            errors.append(f"{w}.paths: give at least one folder or file, relative to the project")
            paths = []
        for p in paths:
            q = norm_prefix(p) if isinstance(p, str) else ""
            if not q or q.startswith("..") or "/../" in f"/{q}/" or Path(str(p)).is_absolute():
                errors.append(f"{w}.paths: {p!r} must be a folder or file inside the project")
            elif q in prefixes:
                errors.append(f"{w}.paths: {q!r} is already in area {prefixes[q]!r}")
            else:
                prefixes[q] = aid
        need = ar.get("need")
        if not isinstance(need, int) or isinstance(need, bool) or not 0 <= need <= 3:
            errors.append(f"{w}.need: 0 (nothing), 1 (contract), 2 (shape) or 3 (every line)")
        elif need > 0 and not (isinstance(ar.get("why"), str) and ar["why"].strip()):
            errors.append(f"{w}.why: say why it needs that depth, in one clause (\"it moves money\")")
    return errors


def load_areas(store):
    a = read_json(Path(store) / "areas.json", None)
    if not a or validate_areas(a):
        return None
    return a


def area_lookup(areas):
    """file path → area id, by the longest folder or file prefix."""
    table = sorted(((norm_prefix(p), ar["id"]) for ar in areas for p in ar["paths"]), key=lambda x: -len(x[0]))

    def find(rel):
        rel = norm_prefix(rel)
        for prefix, aid in table:
            if rel == prefix or rel.startswith(prefix + "/"):
                return aid
        return None
    return find


# --- the project's files ---------------------------------------------------------

def repo_files(root):
    out = git(["ls-files", "-co", "--exclude-standard", "-z"], root)
    if out is not None:
        files = [f for f in out.split("\0") if f]
    else:
        files = []
        for d, dirs, names in os.walk(root):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")]
            rel = os.path.relpath(d, root)
            files += [n if rel == "." else f"{rel}/{n}" for n in names]
            if len(files) > MAX_FILES:
                break
    return [f.replace(os.sep, "/") for f in files[:MAX_FILES]]


def line_counts(root, files, store):
    """Lines per text file, cached by size and modification time."""
    cache_path = Path(store) / "cache" / "lines.json"
    cache = read_json(cache_path, {})
    out, fresh = {}, {}
    for rel in files:
        p = Path(root) / rel
        try:
            st = p.stat()
        except OSError:
            continue
        if not p.is_file():
            continue
        key = [st.st_size, int(st.st_mtime)]
        hit = cache.get(rel)
        if hit and hit[:2] == key:
            n = hit[2]
        elif st.st_size > MAX_COUNT_BYTES:
            n = 0
        else:
            try:
                data = p.read_bytes()
            except OSError:
                continue
            n = 0 if b"\0" in data[:8192] else data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
        out[rel] = n
        fresh[rel] = key + [n]
    if fresh != cache:
        try:
            write_json(cache_path, fresh)
        except OSError:
            pass
    return out


def git_commits(root, days):
    """[(time, [files])] for commits in the last `days` days."""
    out = git(["log", f"--since={days} days ago", "--name-only", "--format=%x00%cI"], root)
    if not out:
        return []
    commits = []
    for chunk in out.split("\0")[1:]:
        lines = [x for x in chunk.strip().split("\n") if x.strip()]
        if not lines:
            continue
        t = ts(lines[0])
        if t:
            commits.append((t, lines[1:]))
    return commits


def agent_sessions(root, store):
    """Sessions in this project with the files they edited, cached by log size and time."""
    cache_path = Path(store) / "cache" / "sessions.json"
    cache = read_json(cache_path, {})
    rootp = Path(root).resolve()
    out, fresh = [], {}
    for log in P.candidate_logs():
        try:
            st = log.stat()
        except OSError:
            continue
        key = [st.st_size, int(st.st_mtime)]
        hit = cache.get(str(log))
        if hit and hit["key"] == key:
            row = hit["row"]
        else:
            if not P.inside(P.first_cwd(log), root):
                row = None
            else:
                meta, events = P.read_session(log)
                edits = []
                for e in events:
                    if e["kind"] != "edit" or not e.get("t"):
                        continue
                    fp = Path(e["path"]).expanduser()
                    if not fp.is_absolute():
                        fp = Path(meta.get("cwd") or root) / fp
                    try:
                        rel = fp.resolve().relative_to(rootp).as_posix()
                    except (ValueError, OSError):
                        continue
                    edits.append([e["t"].isoformat(), rel])
                times = [e["t"] for e in events if e.get("t")]
                row = {"id": meta.get("id"), "agent": meta.get("agent"), "title": meta.get("title"),
                       "start": min(times).isoformat() if times else None, "edits": edits}
        fresh[str(log)] = {"key": key, "row": row}
        if row and row["edits"]:
            out.append(row)
    if fresh != cache:
        try:
            write_json(cache_path, fresh)
        except OSError:
            pass
    return out


# --- briefings and answers -------------------------------------------------------

def load_briefings(store):
    found = []
    for f in sorted((Path(store) / "briefings").glob("*.json")):
        b = read_json(f, None)
        if isinstance(b, dict) and not P.validate(b):
            found.append(b)
    return found


def load_answers(store):
    a = read_json(Path(store) / "answers.json", {})
    a.setdefault("version", VERSION)
    a.setdefault("briefings", {})
    return a


def ref_path(ref):
    """'payments/webhooks.py:88' → 'payments/webhooks.py'. Commands and prose give None."""
    s = str(ref).strip().strip("`")
    if " " in s or not s:
        return None
    return re.sub(r":\d+(-\d+)?$", "", s)


def rel_to_root(p, root):
    q = Path(p).expanduser()
    if q.is_absolute():
        try:
            return q.resolve().relative_to(Path(root).resolve()).as_posix()
        except (ValueError, OSError):
            return None
    return norm_prefix(p)


# --- the map ----------------------------------------------------------------------

def status_of(need, you):
    if need == 0:
        return "ok"
    if you is None:
        return "unknown"
    if you >= need:
        return "solid"
    return "gap" if need - you >= 2 else "thin"


def map_data(root):
    root = Path(root).resolve()
    store = P.store_dir(root)
    a = load_areas(store)
    base = {"version": VERSION, "project": {"name": root.name, "path": str(root)}, "created": stamp(), "areas": None}
    briefings = load_briefings(store)
    saved = load_answers(store)
    answers = saved["briefings"]
    reports = saved.get("areas", {})
    base["briefings"] = [{"id": b["id"], "title": b["session"]["title"], "created": b["created"]} for b in briefings]
    if not a:
        return base
    areas = a["areas"]
    find = area_lookup(areas)
    files = repo_files(root)
    lines = line_counts(root, files, store)
    sessions = agent_sessions(root, store)
    commits = git_commits(root, 120)
    t_now = now()
    recent_cut = t_now - dt.timedelta(days=RECENT_DAYS)

    per = {ar["id"]: {"id": ar["id"], "name": ar["name"], "paths": [norm_prefix(p) for p in ar["paths"]],
                      "need": ar["need"], "why": ar.get("why", ""), "lines": 0, "files": 0,
                      "evidence": [], "check": None, "calls": [], "pending": None}
           for ar in areas}
    unmapped = {"lines": 0, "files": 0}
    for rel, n in lines.items():
        aid = find(rel)
        tgt = per[aid] if aid else unmapped
        tgt["lines"] += n
        tgt["files"] += 1

    # Understanding comes from explain-it-back answers; open calls from briefings without a pick.
    for b in briefings:
        rec = answers.get(b["id"], {})
        q = b.get("question")
        if q and q.get("area"):
            rel = rel_to_root(q["area"], root)
            aid = find(rel) if rel else None
            if aid:
                ans = rec.get("answer")
                depth = q.get("depth") if isinstance(q.get("depth"), int) else DEFAULT_DEPTH
                if ans and ans.get("key") and ans.get("at"):
                    right = ans["key"] == q["answer"]
                    at = ans["at"]
                    per[aid]["evidence"].append((at, "right" if right else "wrong", depth))
                    if not per[aid]["check"] or at > per[aid]["check"]["at"]:
                        per[aid]["check"] = {"at": at, "right": right, "depth": depth, "briefing": b["id"]}
                elif not per[aid]["pending"]:
                    per[aid]["pending"] = {"briefing": b["id"], "title": b["session"]["title"]}
        picks = rec.get("picks", {})
        for i, it in enumerate(b["items"]):
            if it.get("kind") != "call" or str(i) in picks:
                continue
            aid = None
            for r in it.get("refs") or []:
                rel = rel_to_root(ref_path(r) or "", root) if ref_path(r) else None
                aid = find(rel) if rel else None
                if aid:
                    break
            if aid:
                per[aid]["calls"].append({"briefing": b["id"], "item": i, "title": it["title"], "urgent": bool(it.get("urgent"))})

    for aid, r in reports.items():
        if aid in per and isinstance(r, dict) and isinstance(r.get("level"), int) and r.get("at"):
            per[aid]["evidence"].append((r["at"], "said", r["level"]))

    recent_sessions, recent_files = set(), set()
    for s in sessions:
        for t, rel in s["edits"]:
            if ts(t) and ts(t) >= recent_cut:
                recent_sessions.add(s["id"])
                recent_files.add(rel)

    for ar in per.values():
        # Replay the evidence in time order: a right answer raises the level to its depth, a wrong one caps it
        # below its depth, and what you said about yourself sets it until a question tests it.
        level, source, understood = None, None, None
        for at, kind, depth in sorted(ar.pop("evidence")):
            if kind == "right":
                level, source = max(level or 0, depth), "question"
                understood = at
            elif kind == "wrong":
                level, source = min(level if level is not None else depth, depth - 1), "question"
            else:
                level, source = depth, "you said"
                understood = at if depth else understood
            ar["evidence_at"] = at
        ar["level"], ar["source"], ar["last"] = level, source, understood
        last = parse_stamp(ar.get("evidence_at")) if ar.get("evidence_at") else None
        since = last or (t_now - dt.timedelta(days=NEVER_DAYS))
        s_ids, s_files, latest = set(), set(), None
        for s in sessions:
            for t, rel in s["edits"]:
                tt = ts(t)
                if tt and tt > since and find(rel) == ar["id"]:
                    s_ids.add(s["id"])
                    s_files.add(rel)
                    if not latest or tt > latest[0]:
                        latest = (tt, s)
        c_count = sum(1 for t, fs in commits if t > since and any(find(f) == ar["id"] for f in fs))
        ar["changed"] = {"since": stamp(since), "sessions": len(s_ids), "files": len(s_files), "commits": c_count,
                         "counted_from": "last checked" if last else f"last {NEVER_DAYS} days"}
        if latest:
            s = latest[1]
            ar["latest_session"] = {"id": s["id"], "agent": s["agent"], "title": s.get("title"), "at": stamp(latest[0].astimezone())}
        stale = level is not None and level > 0 and bool(s_ids or c_count)
        ar["you"] = None if level is None else (level - 1 if stale else level)
        ar["stale"] = stale
        ar["status"] = status_of(ar["need"], ar["you"])

    base.update({
        "areas": list(per.values()),
        "unmapped": unmapped,
        "confirmed": a.get("confirmed"),
        "recent": {"days": RECENT_DAYS, "sessions": len(recent_sessions), "files": len(recent_files)},
    })
    return base


# --- pages ----------------------------------------------------------------------

def embed(data):
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")


def map_html(data, server=""):
    viewer = P.SKILL_DIR / "viewer"
    return ((viewer / "map.html").read_text()
            .replace("{{TITLE}}", html.escape(f"Plumb · {data['project']['name']} · map"))
            .replace("/*{{CSS}}*/", (viewer / "briefing.css").read_text() + "\n" + (viewer / "map.css").read_text())
            .replace("/*{{JS}}*/", (viewer / "map.js").read_text())
            .replace("<!--{{SERVER}}-->", server)
            .replace("{{DATA}}", embed(data)))


def refresh_pages(root):
    """Rewrite the map and every briefing page from their data, so links and templates are current."""
    store = P.store_dir(root)
    has_map = load_areas(store) is not None
    for b in load_briefings(store):
        try:
            (store / "briefings" / f"{b['id']}.html").write_text(P.page_html(b, has_map=has_map))
        except OSError:
            pass
    page = store / "map.html"
    try:
        store.mkdir(parents=True, exist_ok=True)
        page.write_text(map_html(map_data(root)))
    except OSError:
        return None
    return page


def outline(root):
    """Folders up to two levels deep, with files, lines and recent agent edits, to propose areas from."""
    root = Path(root).resolve()
    store = P.store_dir(root)
    files = repo_files(root)
    lines = line_counts(root, files, store)
    sessions = agent_sessions(root, store)
    cut = now() - dt.timedelta(days=NEVER_DAYS)
    edited = {}
    for s in sessions:
        for t, rel in s["edits"]:
            tt = ts(t)
            if tt and tt >= cut:
                edited[rel] = edited.get(rel, 0) + 1
    rows = {}
    for rel, n in lines.items():
        parts = rel.split("/")
        for depth in (1, 2):
            if len(parts) > depth or (depth == 1 and len(parts) == 1):
                key = "/".join(parts[:depth]) if len(parts) > depth else "(top-level files)"
                r = rows.setdefault(key, {"path": key, "files": 0, "lines": 0, "agent_edits_30d": 0})
                r["files"] += 1
                r["lines"] += n
                r["agent_edits_30d"] += edited.get(rel, 0)
    out = sorted(rows.values(), key=lambda r: r["path"])
    return {"project": str(root), "files": len(lines), "lines": sum(lines.values()),
            "folders": [r for r in out if r["lines"] or r["agent_edits_30d"]]}


# --- answers from the pages --------------------------------------------------------

def find_briefing(store, bid):
    if not BRIEF_ID.fullmatch(bid or ""):
        return None
    b = read_json(Path(store) / "briefings" / f"{bid}.json", None)
    return b if isinstance(b, dict) and b.get("id") == bid else None


def briefing_state(store, bid):
    rec = load_answers(store)["briefings"].get(bid, {})
    ans = rec.get("answer") or {}
    return {"picks": {k: v for k, v in rec.get("picks", {}).items()}, "answer": ans.get("key")}


def record(store, bid, change):
    """Apply one change from a briefing page: a pick, an answer, or clearing both."""
    b = find_briefing(store, bid)
    if not b:
        raise ValueError("unknown briefing")
    with _lock:
        a = load_answers(store)
        rec = a["briefings"].setdefault(bid, {"picks": {}})
        rec.setdefault("picks", {})
        if change.get("clear"):
            a["briefings"].pop(bid, None)
        elif "item" in change:
            i, j = change["item"], change.get("opt")
            items = b["items"]
            if not isinstance(i, int) or not 0 <= i < len(items) or not items[i].get("options"):
                raise ValueError("unknown item")
            if j is None:
                rec["picks"].pop(str(i), None)
            elif isinstance(j, int) and 0 <= j < len(items[i]["options"]):
                rec["picks"][str(i)] = j
            else:
                raise ValueError("unknown option")
        elif "answer" in change:
            q = b.get("question")
            keys = [c["key"] for c in (q or {}).get("choices", [])]
            if change["answer"] not in keys:
                raise ValueError("unknown choice")
            if not rec.get("answer"):  # the first answer counts; the page locks after it
                rec["answer"] = {"key": change["answer"], "right": change["answer"] == q["answer"], "at": stamp()}
        else:
            raise ValueError("nothing to record")
        write_json(Path(store) / "answers.json", a)


def set_level(store, aid, level):
    """What the user says they know about an area. It counts until a question tests it."""
    if not isinstance(level, int) or isinstance(level, bool) or not 0 <= level <= 3:
        raise ValueError("level must be 0 to 3")
    a = load_areas(store)
    if not a or aid not in {ar["id"] for ar in a["areas"]}:
        raise ValueError("unknown area")
    with _lock:
        ans = load_answers(store)
        ans.setdefault("areas", {})[aid] = {"level": level, "at": stamp()}
        write_json(Path(store) / "answers.json", ans)


def set_need(store, aid, need):
    if not isinstance(need, int) or isinstance(need, bool) or not 0 <= need <= 3:
        raise ValueError("need must be 0 to 3")
    with _lock:
        a = load_areas(store)
        if not a:
            raise ValueError("no areas")
        for ar in a["areas"]:
            if ar["id"] == aid:
                ar["need"] = need
                if need and not ar.get("why"):
                    ar["why"] = "you said so on the map."
                break
        else:
            raise ValueError("unknown area")
        write_json(Path(store) / "areas.json", a)


# --- the server -------------------------------------------------------------------

def server_file():
    return P.plumb_home() / "server.json"


def projects_dir():
    return P.plumb_home() / "projects"


def store_root(name):
    """The project folder a store belongs to, from its saved data."""
    if not STORE_NAME.fullmatch(name or ""):
        return None
    store = projects_dir() / name
    if not store.is_dir():
        return None
    for f in ("areas.json", "index.json"):
        p = read_json(store / f, {}).get("project")
        if p and P.store_dir(p) == store:
            return Path(p)
    return None


def server_bits(token, store_name, state=None):
    meta = {"token": token, "store": store_name, "map": f"/p/{store_name}/map", "briefings": f"/p/{store_name}/b/"}
    out = f'<meta name="plumb-server" content="{html.escape(json.dumps(meta), quote=True)}">'
    if state is not None:
        out += f'\n<script id="plumb-state" type="application/json">{embed(state)}</script>'
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "Plumb"
    token = ""
    port = 0
    last_hit = [time.time()]

    def log_message(self, fmt, *args):  # quiet: the log file only gets errors
        pass

    def host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        if host not in (f"127.0.0.1:{self.port}", f"localhost:{self.port}"):
            return False
        origin = self.headers.get("Origin")
        return not origin or origin.lower() in (f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}")

    def send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, code, obj):
        self.send(code, json.dumps(obj), "application/json")

    def do_GET(self):
        Handler.last_hit[0] = time.time()
        if not self.host_ok():
            return self.send(403, "Forbidden")
        url = urlparse(self.path)
        if url.path == "/api/ping":
            return self.send_json(200, {"plumb": VERSION, "pid": os.getpid()})
        m = re.fullmatch(r"/p/([^/]+)/(map|b/([^/]+))/?", url.path)
        if not m:
            if url.path in ("/", ""):
                return self.send(200, self.index_page())
            return self.send(404, "Not found")
        name = m.group(1)
        root = store_root(name)
        if not root:
            return self.send(404, "Unknown project")
        store = projects_dir() / name
        try:
            if m.group(2) == "map":
                return self.send(200, map_html(map_data(root), server_bits(self.token, name)))
            bid = m.group(3)
            b = find_briefing(store, bid)
            if not b:
                return self.send(404, "Unknown briefing")
            page = P.page_html(b, has_map=True, server=server_bits(self.token, name, briefing_state(store, bid)))
            return self.send(200, page)
        except Exception as err:  # keep serving other pages
            sys.stderr.write(f"plumb serve: {self.path}: {err!r}\n")
            return self.send(500, "Plumb couldn't build this page. Run the command again in your agent.")

    def do_POST(self):
        Handler.last_hit[0] = time.time()
        if not self.host_ok() or not secrets.compare_digest(self.headers.get("X-Plumb-Token", ""), self.token):
            return self.send_json(403, {"error": "forbidden"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self.send_json(415, {"error": "send JSON"})
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 65536)
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self.send_json(400, {"error": "bad JSON"})
        name = body.get("store")
        if not store_root(name):
            return self.send_json(404, {"error": "unknown project"})
        store = projects_dir() / name
        try:
            if self.path == "/api/record":
                record(store, body.get("briefing"), body.get("change") or {})
            elif self.path == "/api/need":
                set_need(store, body.get("area"), body.get("need"))
            elif self.path == "/api/level":
                set_level(store, body.get("area"), body.get("level"))
            else:
                return self.send_json(404, {"error": "not found"})
        except (ValueError, OSError) as err:
            return self.send_json(400, {"error": str(err)})
        return self.send_json(200, {"ok": True})

    def index_page(self):
        rows = []
        for d in sorted(projects_dir().glob("*")):
            if store_root(d.name):
                rows.append(f'<li><a href="/p/{html.escape(d.name)}/map">{html.escape(str(store_root(d.name)))}</a></li>')
        return ("<!doctype html><meta charset='utf-8'><title>Plumb</title>"
                "<body style='font:16px system-ui;margin:40px'><h1>Plumb</h1><ul>" + "".join(rows) + "</ul>")


def ping(port, timeout=0.6):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=timeout) as r:
            return json.loads(r.read()).get("plumb") == VERSION
    except (OSError, ValueError):
        return False


def cmd_serve(args):
    token = secrets.token_urlsafe(24)
    start = int(args.port or os.environ.get("PLUMB_PORT") or DEFAULT_PORT)
    httpd = None
    for port in range(start, start + 10):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if not httpd:
        print(f"plumb: no free port from {start} to {start + 9}", file=sys.stderr)
        return 1
    Handler.token, Handler.port = token, port
    idle = float(os.environ.get("PLUMB_IDLE") or IDLE_SECONDS)
    write_json(server_file(), {"port": port, "pid": os.getpid(), "token": token, "started": stamp()})
    try:
        os.chmod(server_file(), 0o600)  # it holds the token
    except OSError:
        pass

    def watchdog():
        while True:
            time.sleep(min(30, max(idle / 4, 0.2)))
            if time.time() - Handler.last_hit[0] > idle:
                httpd.shutdown()
                return
    threading.Thread(target=watchdog, daemon=True).start()
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        httpd.server_close()
        if read_json(server_file(), {}).get("pid") == os.getpid():
            try:
                server_file().unlink()
            except OSError:
                pass
    return 0


def ensure_server():
    """The port of a running Plumb server, starting one if needed. None if it can't start (a sandbox, say)."""
    info = read_json(server_file(), {})
    if info.get("port") and ping(info["port"]):
        return info["port"]
    log = P.plumb_home() / "server.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a") as fh:
            subprocess.Popen([sys.executable, str(Path(P.__file__).resolve()), "serve"], stdin=subprocess.DEVNULL,
                             stdout=fh, stderr=fh, start_new_session=True, close_fds=True)
    except OSError:
        return None
    for _ in range(40):
        time.sleep(0.15)
        info = read_json(server_file(), {})
        if info.get("port") and ping(info["port"], 0.3):
            return info["port"]
    return None


def open_in_browser(target):
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        if shutil.which(opener):
            subprocess.run([opener, str(target)], check=False, capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        pass


def cmd_open(args):
    root = P.project_root(args.project)
    store = P.store_dir(root)
    target = args.target or "map"
    if target != "map" and not find_briefing(store, target):
        print(f"plumb: no briefing {target!r} for {root}. Run `plumb.py open map` or brief a session first.", file=sys.stderr)
        return 1
    if load_areas(store) is not None or target == "map":
        idx = P.load_index(root)  # remember which folder this store belongs to, for the server
        if not idx.get("project"):
            idx["project"] = str(Path(root).resolve())
            try:
                write_json(store / "index.json", idx)
            except OSError:
                pass
    page = refresh_pages(root)
    file_target = page if target == "map" else store / "briefings" / f"{target}.html"
    port = None if args.no_server else ensure_server()
    if port:
        url = f"http://127.0.0.1:{port}/p/{store.name}/" + ("map" if target == "map" else f"b/{target}")
        print(f"{'Map' if target == 'map' else 'Briefing'}: {url}")
        print(f"Served by Plumb on 127.0.0.1:{port}; answers and picks are saved as you click. "
              f"It stops after {IDLE_SECONDS // 60} idle minutes.")
        if not args.no_browser:
            open_in_browser(url)
    else:
        if not file_target or not Path(file_target).exists():
            print("plumb: couldn't write the page here (probably a sandbox).", file=sys.stderr)
            return 3
        print(f"{'Map' if target == 'map' else 'Briefing'}: {file_target}")
        print("Plumb's page server couldn't start here, so this is a plain file. Answers stay in this browser "
              "until you open it again with `plumb.py open`.")
        if not args.no_browser:
            open_in_browser(file_target)
    if target == "map" and load_areas(store) is None:
        print("No areas yet: run /plumb:map to set them up.")
    return 0


def cmd_areas(args):
    root = P.project_root(args.project)
    store = P.store_dir(root)
    if args.set:
        try:
            text = sys.stdin.read() if args.set == "-" else Path(args.set).read_text()
            a = json.loads(text)
        except (OSError, ValueError) as err:
            raise SystemExit(f"plumb: cannot read areas: {err}")
        errors = validate_areas(a)
        if errors:
            print("plumb: the areas are not valid. Fix these and try again:", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            return 1
        out = {"version": VERSION, "project": str(Path(root).resolve()), "confirmed": stamp(),
               "areas": [{"id": ar["id"], "name": ar["name"].strip(), "paths": [norm_prefix(p) for p in ar["paths"]],
                          "need": ar["need"], "why": (ar.get("why") or "").strip()} for ar in a["areas"]]}
        write_json(store / "areas.json", out)
        data = map_data(root)
        um = data.get("unmapped") or {}
        total = um.get("lines", 0) + sum(x["lines"] for x in data["areas"] or [])
        print(f"Saved {len(out['areas'])} areas for {root}.")
        if total and um.get("lines"):
            print(f"{um['files']} files ({round(100 * um['lines'] / total)}% of lines) aren't in any area.")
        refresh_pages(root)
        return 0
    saved = load_areas(store)
    print(json.dumps({"saved": saved, "outline": outline(root)}, ensure_ascii=False, indent=1))
    return 0


def cmd_map(args):
    root = P.project_root(args.project)
    page = refresh_pages(root)
    if args.json:
        print(json.dumps(map_data(root), ensure_ascii=False, indent=1))
    elif page:
        print(f"Map page: {page}")
    return 0
