"""Builds a sample project for the map tests: a small git repo, a Claude Code log that edits it two days ago,
the example briefing (with the project path filled in) and a set of areas. Prints the briefing id.

Run: python3 map_fixture.py BASE PATH/TO/plumb.py
"""
import datetime as dt, json, os, subprocess, sys
from pathlib import Path
base = Path(sys.argv[1]).resolve(); plumb = sys.argv[2]
repo = base / "shopfront"
files = {
  "payments/refunds.py": 420, "payments/webhooks.py": 180, "payments/checkout.py": 610, "payments/__init__.py": 5,
  "db/migrations/0041_orders.py": 60, "db/migrations/0042_refund_attempts.py": 40,
  "orders/models.py": 380, "orders/api.py": 240, "auth/sessions.py": 300, "auth/tokens.py": 120,
  "search/index.py": 210, "notifications/email.py": 160, "inventory/stock.py": 260,
  "web/ui/app.tsx": 900, "web/ui/cart.tsx": 520, "web/ui/styles.css": 400,
  "scripts/admin/backfill.py": 90, "analytics/events.py": 130, "README.md": 40, "tests/test_refunds.py": 350,
}
for rel, n in files.items():
    p = repo / rel; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(f"line {i}\n" for i in range(n)))
env = dict(os.environ, GIT_AUTHOR_DATE="2026-10-01T10:00:00", GIT_COMMITTER_DATE="2026-10-01T10:00:00")
subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
subprocess.run(["git", "add", "."], cwd=repo, check=True)
subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"], cwd=repo, check=True, env=env)
now = dt.datetime.now(dt.timezone.utc)
t0 = now - dt.timedelta(days=2)
sid = "3f9c21ab-5d1e-4c55-9a0b-1c2d3e4f5a6b"
ts = lambda m: (t0 + dt.timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
cwd = str(repo)
def edit(i, rel): return {"type": "tool_use", "id": f"e{i}", "name": "Edit", "input": {"file_path": f"{cwd}/{rel}", "old_string": "a", "new_string": "b"}}
recs = [
  {"type": "user", "cwd": cwd, "timestamp": ts(0), "message": {"role": "user", "content": "Make refunds survive provider timeouts"}},
  {"type": "assistant", "cwd": cwd, "timestamp": ts(5), "message": {"role": "assistant", "content": [
     edit(1, "payments/refunds.py"), edit(2, "payments/webhooks.py"), edit(3, "db/migrations/0042_refund_attempts.py"),
     edit(4, "tests/test_refunds.py"), edit(5, "web/ui/cart.tsx")]}},
  {"type": "assistant", "cwd": cwd, "timestamp": ts(200), "message": {"role": "assistant", "content": [{"type": "text", "text": "Done."}]}},
]
log = base / "claude" / "-shopfront" / f"{sid}.jsonl"
log.parent.mkdir(parents=True, exist_ok=True)
log.write_text("".join(json.dumps(r) + "\n" for r in recs))
old = now.timestamp() - 3600; os.utime(log, (old, old))
b = json.load(open(Path(plumb).parent.parent / "examples" / "shopfront.json"))
b["project"]["path"] = cwd
b["question"]["depth"] = 2
fmt = lambda t: t.astimezone().strftime("%Y-%m-%d %H:%M")
b["session"]["started"], b["session"]["ended"], b["created"] = fmt(t0), fmt(t0 + dt.timedelta(minutes=200)), fmt(now - dt.timedelta(days=1))
b["id"] = fmt(t0)[:10] + "-3f9c21ab"
(base / "briefing.json").write_text(json.dumps(b))
areas = {"areas": [
  {"id": "refunds", "name": "payments/refunds", "paths": ["payments/refunds.py"], "need": 3, "why": "it moves money"},
  {"id": "checkout", "name": "payments/checkout", "paths": ["payments/checkout.py", "payments/__init__.py"], "need": 3, "why": "it moves money"},
  {"id": "webhooks", "name": "webhooks", "paths": ["payments/webhooks.py"], "need": 3, "why": "outside systems call it, and it can issue refunds"},
  {"id": "migrations", "name": "db/migrations", "paths": ["db/migrations"], "need": 3, "why": "it changes production data and is hard to undo"},
  {"id": "orders", "name": "orders", "paths": ["orders"], "need": 2, "why": "most other areas depend on it"},
  {"id": "sessions", "name": "auth", "paths": ["auth"], "need": 3, "why": "it decides who is logged in"},
  {"id": "search", "name": "search", "paths": ["search"], "need": 1, "why": "it only reads data"},
  {"id": "notifications", "name": "notifications", "paths": ["notifications"], "need": 1, "why": "what it sends customers matters more than how"},
  {"id": "inventory", "name": "inventory", "paths": ["inventory"], "need": 2, "why": "wrong counts mean selling stock you don't have"},
  {"id": "ui", "name": "web/ui", "paths": ["web/ui"], "need": 0, "why": ""},
  {"id": "tests", "name": "tests", "paths": ["tests"], "need": 0, "why": ""},
]}
(base / "areas.json").write_text(json.dumps(areas))
print(b["id"])
