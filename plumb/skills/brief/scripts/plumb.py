#!/usr/bin/env python3
"""plumb: the helper behind the /plumb:brief skill.

Subcommands (stdlib only, read-only on the user's project):
  sessions  list recent Claude Code and Codex sessions for a project
  digest    condense one session log into text an agent can read in one go
  state     summarize the project as it is now (git, processes, ports)
  render    validate a briefing JSON file and write it out as an HTML page

Briefings are stored under $PLUMB_HOME (default ~/.plumb), never in the project.
"""

import argparse
import datetime as dt
import glob
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

HOME = Path.home()
SKILL_DIR = Path(__file__).resolve().parent.parent


def env_path(name, default):
    return Path(os.environ.get(name) or default).expanduser()


def claude_dir():
    return env_path("PLUMB_CLAUDE_DIR", HOME / ".claude" / "projects")


def codex_dir():
    return env_path("PLUMB_CODEX_DIR", HOME / ".codex" / "sessions")


def plumb_home():
    return env_path("PLUMB_HOME", HOME / ".plumb")


LIVE_SECONDS = 120          # a log written this recently is probably the session running the skill
BIG_LINE = 200_000          # lines longer than this are tool output or images; skip them when listing


def tilde(path):
    s = str(path)
    h = str(HOME)
    return "~" + s[len(h):] if s == h or s.startswith(h + os.sep) else s


def parse_ts(value):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def fmt_ts(t):
    return t.astimezone().strftime("%Y-%m-%d %H:%M") if t else "?"


def fmt_hours(seconds):
    if seconds is None:
        return "?"
    if seconds < 3600:
        return f"{round(seconds / 60)} min"
    return f"{seconds / 3600:.1f} h"


def project_root(path=None):
    start = Path(path or os.getcwd()).expanduser().resolve()
    r = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    return Path(r.stdout.strip()).resolve() if r.returncode == 0 and r.stdout.strip() else start


def inside(cwd, root):
    if not cwd:
        return False
    try:
        c = Path(cwd).expanduser().resolve()
    except OSError:
        return False
    return c == root or root in c.parents


def short(text, limit):
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1] + f"… [+{len(text) - limit + 1} chars]"


def one_line(text, limit):
    return short(" ".join(str(text or "").split()), limit)


# Logs contain whatever the user pasted and whatever commands the agent ran, keys included.
# Everything this script prints passes through redact(); render refuses briefings that still contain one.
SECRET_PATTERNS = [
    re.compile(r"\b(sk-(?:ant-|proj-|cp-|live-|test-)?[A-Za-z0-9_\-]{20,})"),
    re.compile(r"\b(AIza[0-9A-Za-z_\-]{30,})"),
    re.compile(r"\b(AQ\.[0-9A-Za-z_\-.]{30,})"),
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
    re.compile(r"\b(xox[abprs]-[A-Za-z0-9-]{10,})"),
    re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
    re.compile(r"\b(eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"),
    re.compile(r"(?i)\bBearer\s+([A-Za-z0-9._~+/=-]{20,})"),
    re.compile(r"(?i)(?:api[_-]?key|secret|token|passw(?:or)?d|\bkey)[\"']?\s*[:=]\s*[\"']([^\"'\s]{16,})[\"']"),
    re.compile(r"\b[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*=([^\s\"'$<{][^\s\"']{15,})"),
    re.compile(r"\b[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*=[\"']([^\"'\s$<{][^\"'\s]{15,})[\"']"),
]
# Fallback for formats nobody listed yet: a long run that mixes upper case, lower case and digits looks like a key.
# Hex hashes, UUIDs and paths don't match (no upper case, or a slash); tool and message ids are allowed through.
RANDOM_TOKEN = re.compile(r"(?<![\w/.-])([A-Za-z0-9][A-Za-z0-9_\-.]{31,})(?![\w/-])")
ID_PREFIXES = ("toolu_", "msg_", "call_", "req_", "resp_", "ctc_", "ctco_", "rs_", "fc_")


def looks_random(token):
    return (re.search(r"[A-Z]", token) and re.search(r"[a-z]", token) and re.search(r"\d", token)
            and not token.startswith(ID_PREFIXES) and token.count(".") <= 2 and not token.endswith((".jsonl", ".json", ".md")))


def redact(text):
    text = str(text)
    for pat in SECRET_PATTERNS:
        text = pat.sub(lambda m: m.group(0).replace(m.group(1), f"[secret hidden, {len(m.group(1))} chars]"), text)
    return RANDOM_TOKEN.sub(lambda m: f"[secret hidden, {len(m.group(1))} chars]" if looks_random(m.group(1)) else m.group(0), text)


def find_secrets(text):
    text = str(text)
    found = [m.group(1) for pat in SECRET_PATTERNS for m in pat.finditer(text)]
    return found + [m.group(1) for m in RANDOM_TOKEN.finditer(text) if looks_random(m.group(1))]


def clip(text, limit):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --- reading logs ------------------------------------------------------------
#
# Both readers turn a log into the same event list:
#   {"t": datetime, "kind": "user"|"agent"|"tool"|"edit"|"error"|"note", "text": str, ...}
# plus a meta dict. Unknown record types are ignored, so new log fields don't break anything.

WRAPPER = re.compile(r"^<(command-name|local-command-stdout|local-command-caveat|system-reminder|"
                     r"task-notification|bash-input|bash-stdout|bash-stderr|user-prompt-submit-hook)")
PASTE_TAG = re.compile(r"</?pasted_content[^>]*>")
COMPACTED = "This session is being continued from a previous conversation"
PATCH_FILE = re.compile(r"\*\*\* (Update|Add|Delete) File: ([^\n\\\"']+)")
EXIT_CODE = re.compile(r'"exit_code"\s*:\s*([1-9]\d*)|Exit code:? ([1-9]\d*)|Process exited with code ([1-9]\d*)')


def iter_json(path, skip_big=False):
    with open(path, errors="replace") as fh:
        for line in fh:
            if skip_big and len(line) > BIG_LINE:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue  # a torn last line while the agent is still writing


def text_blocks(content, kinds=("text", "input_text", "output_text")):
    if isinstance(content, str):
        return [content]
    out = []
    for b in content or []:
        if isinstance(b, dict) and b.get("type") in kinds and b.get("text"):
            out.append(b["text"])
    return out


def clean_user_text(text):
    """Return what the person typed, or None for harness wrappers."""
    t = text.strip()
    if t.startswith("<pasted_content"):
        return PASTE_TAG.sub("", t).strip()
    if t.startswith("<command-name>"):
        name = re.search(r"<command-name>(.*?)</command-name>", t, re.S)
        args = re.search(r"<command-args>(.*?)</command-args>", t, re.S)
        return f"(ran {' '.join(filter(None, [name.group(1).strip(), args.group(1).strip() if args else '']))})" if name else None
    if WRAPPER.match(t) or t.startswith("Base directory for this skill"):
        return None
    return PASTE_TAG.sub("", t).strip()


def read_claude(path, skip_big=False):
    meta = {"agent": "claude-code", "path": str(path), "id": Path(path).stem, "cwd": None, "title": None,
            "models": set(), "cost_usd": None, "lines_added": None, "lines_removed": None}
    events = []
    for d in iter_json(path, skip_big):
        meta["cwd"] = meta["cwd"] or d.get("cwd")
        kind = d.get("type")
        t = parse_ts(d.get("timestamp"))
        if kind == "ai-title":
            meta["title"] = d.get("aiTitle") or meta["title"]
        elif kind == "cost-state":
            meta["cost_usd"] = d.get("totalCostUSD")
            meta["lines_added"] = d.get("totalLinesAdded")
            meta["lines_removed"] = d.get("totalLinesRemoved")
        elif kind == "system" and d.get("subtype") == "compact_boundary":
            events.append({"t": t, "kind": "note", "text": "context compacted here"})
        elif kind == "attachment" and (d.get("attachment") or {}).get("type") == "queued_command":
            # Messages typed while the agent was busy, and background-task results, arrive this way.
            a = d["attachment"]
            prompt = str(a.get("prompt") or "")
            if prompt.strip().startswith("<task-notification>"):
                events.extend(task_note(t, prompt))
            elif (a.get("origin") or {}).get("kind", "human") == "human" and clean_user_text(prompt):
                events.append({"t": t, "kind": "user", "text": "(sent while the agent was working) " + clean_user_text(prompt)})
        if d.get("isSidechain") or kind not in ("user", "assistant"):
            continue
        msg = d.get("message") or {}
        content = msg.get("content")
        if kind == "user":
            if d.get("isMeta"):
                continue
            for text in text_blocks(content):
                if text.strip().startswith(COMPACTED) or d.get("isCompactSummary"):
                    events.append({"t": t, "kind": "note", "text": "summary carried over after compaction:\n"
                                   + text.split("Summary:", 1)[-1].strip()})
                    continue
                if text.strip().startswith("<task-notification>"):
                    events.extend(task_note(t, text))
                    continue
                typed = clean_user_text(text)
                if typed:
                    events.append({"t": t, "kind": "user", "text": typed})
            for b in content if isinstance(content, list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                    events.append({"t": t, "kind": "error", "text": " ".join(text_blocks(b.get("content")))
                                   if isinstance(b.get("content"), list) else str(b.get("content"))})
        else:
            if msg.get("model") and not str(msg["model"]).startswith("<"):
                meta["models"].add(msg["model"])
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text", "").strip():
                    events.append({"t": t, "kind": "agent", "text": b["text"].strip()})
                elif b.get("type") == "tool_use":
                    events.extend(claude_tool(t, b.get("name", ""), b.get("input") or {}))
    return meta, events


def task_note(t, text):
    summary = re.search(r"<summary>(.*?)</summary>", text, re.S)
    status = re.search(r"<status>(.*?)</status>", text, re.S)
    return [{"t": t, "kind": "note", "text": "background task " + (status.group(1).strip() if status else "finished")
             + ": " + (summary.group(1).strip() if summary else "")}]


def claude_tool(t, name, inp):
    if name in ("Edit", "MultiEdit", "Write", "NotebookEdit"):
        path = inp.get("file_path") or inp.get("notebook_path") or "?"
        if name == "Write":
            delta = (inp.get("content") or "").count("\n") + 1
            how = f"wrote {delta} lines"
        elif name == "MultiEdit":
            how = f"{len(inp.get('edits') or [])} edits"
        else:
            old, new = inp.get("old_string") or "", inp.get("new_string") or ""
            how = f"{new.count(chr(10)) - old.count(chr(10)):+d} lines"
        return [{"t": t, "kind": "edit", "path": path, "text": f"{name} {path} ({how})"}]
    if name == "Bash":
        cmd = inp.get("command") or ""
        ev = {"t": t, "kind": "tool", "text": "$ " + cmd, "background": bool(inp.get("run_in_background"))}
        return [ev]
    if name in ("Read", "Grep", "Glob", "LS", "ToolSearch", "TodoWrite", "TaskOutput"):
        return []  # looking around; too noisy to list
    detail = inp.get("description") or inp.get("skill") or inp.get("url") or inp.get("query") or inp.get("prompt") or ""
    return [{"t": t, "kind": "tool", "text": f"→ {name} {one_line(detail, 160)}".rstrip()}]


def read_codex(path, skip_big=False):
    meta = {"agent": "codex", "path": str(path), "id": None, "cwd": None, "title": None,
            "models": set(), "cost_usd": None, "lines_added": None, "lines_removed": None}
    events = []
    for d in iter_json(path, skip_big):
        kind = d.get("type")
        p = d.get("payload") or {}
        t = parse_ts(d.get("timestamp"))
        if kind == "session_meta":
            meta["id"] = meta["id"] or p.get("id") or p.get("session_id")
            meta["cwd"] = meta["cwd"] or p.get("cwd")
        elif kind == "turn_context":
            meta["cwd"] = meta["cwd"] or p.get("cwd")
            if p.get("model"):
                meta["models"].add(p["model"])
        elif kind == "event_msg" and p.get("type") == "context_compacted":
            events.append({"t": t, "kind": "note", "text": "context compacted here"})
        if kind != "response_item":
            continue
        ptype = p.get("type")
        if ptype == "message" and p.get("role") == "user":
            for text in text_blocks(p.get("content")):
                s = text.strip()
                if s.startswith("<") and not s.startswith("<pasted_content") or s.startswith("# AGENTS.md"):
                    continue
                typed = clean_user_text(s)
                if typed:
                    events.append({"t": t, "kind": "user", "text": typed})
        elif ptype == "message" and p.get("role") == "assistant":
            for text in text_blocks(p.get("content")):
                if text.strip():
                    events.append({"t": t, "kind": "agent", "text": text.strip()})
        elif ptype in ("custom_tool_call", "function_call"):
            raw = p.get("input") if ptype == "custom_tool_call" else p.get("arguments")
            events.extend(codex_tool(t, p.get("name", ""), raw if isinstance(raw, str) else json.dumps(raw)))
        elif ptype in ("custom_tool_call_output", "function_call_output"):
            out = p.get("output")
            out = " ".join(text_blocks(out)) if isinstance(out, list) else str(out or "")
            if EXIT_CODE.search(out):
                events.append({"t": t, "kind": "error", "text": out})
    meta["id"] = meta["id"] or Path(path).stem
    return meta, events


def codex_tool(t, name, raw):
    raw = raw or ""
    events = []
    files = sorted({m.group(2).strip() for m in PATCH_FILE.finditer(raw)})
    for f in files:
        events.append({"t": t, "kind": "edit", "path": f, "text": f"apply_patch {f}"})
    cmds = re.findall(r'cmd\s*:\s*"((?:[^"\\]|\\.)*)"', raw) or re.findall(r"cmd\s*:\s*'((?:[^'\\]|\\.)*)'", raw)
    if not cmds:
        try:
            args = json.loads(raw)
            c = args.get("command") or args.get("cmd") if isinstance(args, dict) else None
            cmds = [" ".join(c) if isinstance(c, list) else c] if c else []
        except ValueError:
            pass
    for c in cmds:
        c = c.encode().decode("unicode_escape", errors="replace") if "\\n" in c else c
        if "apply_patch" in c and files:
            continue
        events.append({"t": t, "kind": "tool", "text": "$ " + c})
    if not files and not cmds and name not in ("sleep", "wait"):
        events.append({"t": t, "kind": "tool", "text": f"→ {name} {one_line(raw, 160)}"})
    return events


def read_session(path, skip_big=False):
    return read_codex(path, skip_big) if "/.codex/" in str(path) or Path(path).name.startswith("rollout-") \
        else read_claude(path, skip_big)


# --- finding sessions --------------------------------------------------------

def first_cwd(path):
    """The working directory recorded near the top of a log, without reading the whole file."""
    with open(path, errors="replace") as fh:
        for i, line in enumerate(fh):
            if i > 400:
                break
            if len(line) > BIG_LINE:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            cwd = d.get("cwd") or (d.get("payload") or {}).get("cwd")
            if cwd:
                return cwd
    return None


def candidate_logs():
    logs = [Path(p) for p in glob.glob(str(claude_dir() / "*" / "*.jsonl"))]
    logs += [Path(p) for p in glob.glob(str(codex_dir() / "**" / "rollout-*.jsonl"), recursive=True)]
    return sorted(logs, key=lambda p: p.stat().st_mtime, reverse=True)


RISKY_CMD = re.compile(r"\bgit (commit|push|reset|checkout|stash|tag|clean)\b|\brm -r?f\b|\bnpm (publish|install|i)\b|"
                       r"\bpip3? install\b|\bbrew install\b|\bnohup\b|&\s*\)?\s*$|\bkill\b|\bpkill\b|launchctl|crontab|"
                       r"\bln -s\b|\bchmod\b|settings\.json|\bcurl\b.*\b(-X|--data|-d)\b")
WRITE_CMD = re.compile(r"\bsed -i|\bperl -pi|open\([^)]*['\"][wa]['\"]|write_text\(|\bcat > |\btee\b|\bcp\b|\bmv\b|"
                       r">\s*[\w~./-]+\.(py|js|mjs|ts|json|md|html|css|sh|toml|yaml|yml|txt)\b")


def shell_commands(events):
    return [e["text"][2:] for e in events if e["kind"] == "tool" and e["text"].startswith("$ ")]


def when(t, now=None):
    """'today 06:48', 'yesterday 22:10', '3 days ago', or 'Oct 29' for older sessions."""
    if not t:
        return "?"
    local = t.astimezone()
    days = ((now or dt.datetime.now().astimezone()).date() - local.date()).days
    if days <= 0:
        return f"today {local:%H:%M}"
    if days == 1:
        return f"yesterday {local:%H:%M}"
    if days < 7:
        return f"{days} days ago"
    return f"{local:%b} {local.day}"


def summarize(path, meta, events):
    times = [e["t"] for e in events if e.get("t")]
    start, end = (min(times), max(times)) if times else (None, None)
    mtime = Path(path).stat().st_mtime
    edits = [e for e in events if e["kind"] == "edit"]
    requests = [e for e in events if e["kind"] == "user" and not e["text"].startswith("(ran ")]
    # Changes: edits plus shell commands that write files, commit, install or start/stop processes.
    changes = len(edits) + sum(1 for c in shell_commands(events) if RISKY_CMD.search(c) or WRITE_CMD.search(c))
    first = clip(requests[0]["text"], 140) if requests else ""
    return {
        "id": meta["id"], "agent": meta["agent"], "path": str(path), "cwd": meta["cwd"],
        "title": meta["title"], "label": clip(meta["title"] or first, 50),
        "start": start.isoformat() if start else None, "end": end.isoformat() if end else None,
        "when": when(start), "hours": round((end - start).total_seconds() / 3600, 2) if start and end else None,
        "requests": len(requests), "edits": len(edits), "files_edited": len({e["path"] for e in edits}),
        "changes": changes, "first_request": first,
        "live": (dt.datetime.now().timestamp() - mtime) < LIVE_SECONDS,
        "cost_usd": meta["cost_usd"],
        "_search": " ".join([meta["id"] or "", meta["title"] or ""] + [e["text"] for e in requests]).lower(),
    }


def find_sessions(root, limit, exclude=None, match=None):
    briefed = load_index(root).get("briefed", {})
    words = (match or "").lower().split()
    found = []
    for path in candidate_logs():
        if len(found) >= limit:
            break
        if exclude and exclude in path.name:
            continue
        if not inside(first_cwd(path), root):
            continue
        meta, events = read_session(path, skip_big=True)
        if not any(e["kind"] == "user" for e in events):
            continue
        row = summarize(path, meta, events)
        search = row.pop("_search")
        if words and not all(w in search for w in words):
            continue
        row["briefed"] = briefed.get(row["id"])
        found.append(row)
    return found


def resolve_session(ref):
    p = Path(ref).expanduser()
    if p.is_file():
        return p
    matches = [path for path in candidate_logs() if ref in path.name]
    if not matches:
        raise SystemExit(f"plumb: no session log matches {ref!r}. Run `plumb.py sessions` to list them.")
    if len(matches) > 1:
        names = ", ".join(m.name for m in matches[:5])
        raise SystemExit(f"plumb: {ref!r} matches {len(matches)} logs ({names}). Use a longer id.")
    return matches[0]


def cmd_sessions(args):
    root = project_root(args.project)
    exclude = args.exclude if args.exclude and not args.exclude.startswith("${") else None
    rows = find_sessions(root, args.limit, exclude, args.match)
    for r in rows:
        for k in ("first_request", "title", "label"):
            r[k] = redact(r[k]) if r[k] else r[k]
    if args.json:
        print(json.dumps({"project": str(root), "match": args.match, "sessions": rows}, indent=2))
        return 0
    found = f"matching \"{args.match}\"" if args.match else "newest first"
    print(f"Agent sessions for {tilde(root)}, {found} (briefings are kept in {tilde(store_dir(root))})\n")
    if not rows:
        print("No matching Claude Code or Codex sessions." if args.match else "No Claude Code or Codex sessions found for this project.")
    width = max([display_width(r["label"]) for r in rows] + [10])
    for n, r in enumerate(rows, 1):
        what = (plural(r["edits"], "edit") + " in " + plural(r["files_edited"], "file") if r["edits"] else
                plural(r["changes"], "shell change") if r["changes"] else "talk only, no changes")
        facts = [AGENT_NAMES.get(r["agent"], r["agent"]), r["when"], fmt_hours(r["hours"] and r["hours"] * 3600), what]
        if r["cost_usd"]:
            facts.append(f"${r['cost_usd']:.2f}")
        if r["briefed"]:
            facts.append(f"briefed {r['briefed'][:10]}")
        if r["live"]:
            facts.append("LIVE: probably this session")
        print(f"{n:2}  {r['label']}{' ' * (width - display_width(r['label']))}  {' · '.join(facts)}")
        print(f"    id {r['id'][:8]} · \"{clip(r['first_request'], 100)}\"")
    return 0


AGENT_NAMES = {"claude-code": "Claude Code", "codex": "Codex"}


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def display_width(text):
    """Terminal columns: Chinese, Japanese and Korean characters take two."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


# --- digest ------------------------------------------------------------------

def build_digest(path, max_chars):
    meta, events = read_session(path)
    info = summarize(path, meta, events)
    head = [f"# Session digest: {info['title'] or info['first_request'][:60]}",
            f"agent: {meta['agent']} · id: {meta['id']} · project: {tilde(meta['cwd'] or '?')}",
            f"time: {fmt_ts(parse_ts(info['start']))} → {fmt_ts(parse_ts(info['end']))} local "
            f"({fmt_hours(info['hours'] and info['hours'] * 3600)} wall clock) · {info['requests']} requests"
            + (f" · models: {', '.join(sorted(meta['models']))}" if meta["models"] else "")
            + (f" · cost ${meta['cost_usd']:.2f}" if meta["cost_usd"] else "")
            + (f" · +{meta['lines_added']}/-{meta['lines_removed']} lines" if meta["lines_added"] is not None else ""),
            f"log: {tilde(path)}"]

    edits = {}
    for e in events:
        if e["kind"] == "edit":
            edits[e["path"]] = edits.get(e["path"], 0) + 1
    root = Path(meta["cwd"]).expanduser() if meta["cwd"] else None
    rel = lambda p: os.path.relpath(p, root) if root and os.path.isabs(p) and inside(p, root.resolve()) else tilde(p)
    sections = ["\n## Files edited (edit count)"]
    sections += [f"- {rel(p)} ({n})" for p, n in sorted(edits.items(), key=lambda kv: -kv[1])] or ["- none"]
    cmds = shell_commands(events)
    bg = [e["text"][2:] for e in events if e.get("background")]
    sections.append("\n## Commands worth checking (commits, installs, deletes, processes started or stopped)")
    sections += [f"- {one_line(c, 220)}" for c in ([c for c in cmds if RISKY_CMD.search(c)] + [f"[background] {b}" for b in bg])[:40]] or ["- none"]
    shell_writes = [c for c in cmds if WRITE_CMD.search(c) and not RISKY_CMD.search(c)]
    sections.append("\n## Shell commands that may have written files (not in 'Files edited'; check git status)")
    sections += [f"- {one_line(c, 200)}" for c in shell_writes[:30]] or ["- none"]

    # Timeline. The last agent message before each new request is the agent's report: keep it whole.
    lines, last_agent = [], {}
    for i, e in enumerate(events):
        if e["kind"] == "agent":
            nxt = next((x for x in events[i + 1:] if x["kind"] in ("user", "agent")), None)
            if nxt is None or nxt["kind"] == "user":
                last_agent[i] = True
    for i, e in enumerate(events):
        stamp = e["t"].astimezone().strftime("%m-%d %H:%M") if e.get("t") else "     ?     "
        k = e["kind"]
        if k == "user":
            lines.append((0, f"\n[{stamp}] USER: {short(e['text'], 4000)}"))
        elif k == "agent":
            if last_agent.get(i):
                lines.append((0, f"\n[{stamp}] AGENT (report): {short(e['text'], 6000)}"))
            else:
                lines.append((1, f"[{stamp}] agent: {one_line(e['text'], 400)}"))
        elif k == "note":
            lines.append((0, f"\n[{stamp}] --- {short(e['text'], 2500)} ---"))
        elif k == "edit":
            lines.append((2, f"    ✎ {e['text'].replace(e['path'], rel(e['path']))}"))
        elif k == "tool":
            lines.append((2, f"    {one_line(e['text'], 220)}"))
        elif k == "error":
            lines.append((1, f"    ! error: {one_line(e['text'], 300)}"))

    out = "\n".join(head + sections) + "\n\n## Timeline (local time)\n"
    budget = max_chars - len(out)
    dropped = 0
    for level in (2, 1):  # drop tool lines first, then intermediate agent chatter
        if sum(len(t) + 1 for _, t in lines) <= budget:
            break
        keep = []
        for lv, t in lines:
            if lv >= level:
                dropped += 1
            else:
                keep.append((lv, t))
        lines = keep
    body = "\n".join(t for _, t in lines)
    if len(body) > budget:
        body = body[: max(budget, 0)] + "\n… [digest cut at max size; read the log for the rest]"
    if dropped:
        out += f"(Dropped {dropped} lower-priority lines to fit {max_chars} characters; the log has them.)\n"
    return out + body


def cmd_digest(args):
    print(redact(build_digest(resolve_session(args.session), args.max_chars)))
    return 0


# --- state -------------------------------------------------------------------

def run(cmd, cwd=None, timeout=20):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def cmd_state(args):
    root = project_root(args.project)
    print(f"# Project state now: {tilde(root)} ({dt.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')})\n")
    if run(["git", "rev-parse", "--git-dir"], cwd=root):
        branch = run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=root) or "(detached)"
        print(f"## Git\nbranch: {branch}")
        print("last commits:\n" + (run(["git", "log", "--format=  %h %ad %s", "--date=format:%Y-%m-%d %H:%M", "-8"], cwd=root)
                                   or "  (no commits yet)"))
        if args.since:
            since = run(["git", "log", f"--since={args.since}", "--format=  %h %ad %s", "--date=format:%Y-%m-%d %H:%M"], cwd=root)
            print(f"commits since {args.since}:\n{since or '  none'}")
        status = run(["git", "status", "--porcelain"], cwd=root).splitlines()
        counts = {}
        for s in status:
            counts[s[:2].strip() or "?"] = counts.get(s[:2].strip() or "?", 0) + 1
        print(f"uncommitted: {len(status)} paths {counts if counts else ''}")
        stat = run(["git", "diff", "--shortstat", "HEAD"], cwd=root) or run(["git", "diff", "--shortstat"], cwd=root)
        if stat:
            print(f"diff vs last commit: {stat}")
        top = {}
        for s in status:
            part = s[3:].split("/")[0]
            top[part] = top.get(part, 0) + 1
        if top:
            print("uncommitted by top folder: " + ", ".join(f"{k} ({v})" for k, v in sorted(top.items(), key=lambda kv: -kv[1])[:12]))
    else:
        print("## Git\nnot a git repository: nothing records what changed. File times are the only history.")

    print("\n## Processes started from this project (still running)")
    for line in project_processes(root):
        print(redact(line))
    return 0


# Agents, shells and short-lived text tools (often the rest of the pipeline that ran this script).
AGENT_PROCESS = re.compile(r"\b(claude|codex)\b|plumb\.py|(^|/)(-?zsh|bash|sh|fish|login|sed|cut|grep|rg|head|tail|awk|"
                           r"sort|uniq|wc|cat|less|more|tee|xargs|lsof|ps|footprint|sleep)$")


def project_processes(root):
    """Processes whose working folder is in the project, or whose command line names it.

    Outside a sandbox `ps` gives start times and full commands. Codex's sandbox blocks `ps` but allows `lsof`,
    so fall back to what lsof knows: pid, program name, working folder and listening ports.
    """
    rootstr, pids, names, parents = str(root), set(), {}, {}
    for line in run(["ps", "-axo", "pid=,ppid=,command="]).splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3:
            parents[parts[0]] = parts[1]
            if rootstr in parts[2]:
                pids.add(parts[0])
    pid = None
    for line in run(["lsof", "-a", "-d", "cwd", "-FpRcn"], timeout=30).splitlines():
        if line.startswith("p"):
            pid = line[1:]
        elif line.startswith("R") and pid:
            parents[pid] = line[1:]
        elif line.startswith("c") and pid:
            names[pid] = line[1:]
        elif line.startswith("n") and pid and inside(line[1:], root):
            pids.add(pid)
    me, caller = str(os.getpid()), str(os.getppid())
    # Leave out this script, whatever started it, and the other commands in the same pipeline.
    pids = {p for p in pids if p not in (me, caller) and parents.get(p) not in (me, caller)}
    if not pids:
        return ["- none found"]

    def ports(p):
        out = run(["lsof", "-nP", "-a", "-p", p, "-iTCP", "-sTCP:LISTEN", "-Fn"], timeout=10)
        found = sorted({l[1:] for l in out.splitlines() if l.startswith("n")})
        return f", listening {', '.join(found)}" if found else ""

    def memory(p, rss_kb=None):
        out = run(["footprint", "-p", p], timeout=10) if shutil.which("footprint") else ""
        m = re.search(r"Footprint:\s*([\d.]+ \w+)", out)
        if m:
            return m.group(1)
        return f"{int(rss_kb) // 1024} MB resident (GPU memory not counted)" if rss_kb else "unknown"

    lines = []
    details = run(["ps", "-o", "pid=,etime=,rss=,command=", "-p", ",".join(sorted(pids))])
    if details:
        for line in details.splitlines():
            p, etime, rss, command = line.split(None, 3)
            if not AGENT_PROCESS.search(command.split()[0]) and not re.search(r"\b(claude|codex)\b|plumb\.py", command):
                lines.append(f"- pid {p}, up {etime}, memory {memory(p, rss)}{ports(p)}: {tilde(one_line(command, 160))}")
    else:
        for p in sorted(pids, key=int):
            name = names.get(p, "?")
            if not AGENT_PROCESS.search(name):
                lines.append(f"- pid {p}, {name}, memory {memory(p)}{ports(p)}")
        if lines:
            lines.append("(`ps` isn't allowed here, probably a sandbox, so start times and full commands are missing)")
    return lines or ["- none found"]


# --- briefing store and validation ---------------------------------------------

KINDS = ("call", "decided", "fyi", "unchecked", "outside")
AGENTS = ("claude-code", "codex")


def store_dir(root):
    root = Path(root).resolve()
    digest = hashlib.sha1(str(root).encode()).hexdigest()[:8]
    return plumb_home() / "projects" / f"{re.sub(r'[^A-Za-z0-9._-]+', '-', root.name)}-{digest}"


def load_index(root):
    """Which sessions have a briefing, from the store and from the temp-folder fallback used inside sandboxes."""
    store = store_dir(root)
    idx = {}
    for d in (store, Path(tempfile.gettempdir()) / "plumb" / store.name):
        try:
            data = json.loads((d / "index.json").read_text())
        except (OSError, ValueError):
            continue
        if not idx:
            idx = data
        else:
            idx.setdefault("briefed", {}).update(data.get("briefed", {}))
    return idx


# Exhibit type → (list field, min, max entries, required text fields per entry).
EXHIBITS = {
    "compare": ("rows", 1, 6, ("left", "right")),
    "flow": ("steps", 2, 7, ("text",)),
    "places": ("places", 1, 12, ("label",)),
    "tally": ("rows", 1, 4, ("label",)),
    "timeline": ("events", 2, 8, ("when", "text")),
    "code": ("lines", 1, 14, ("text",)),
}
STATUSES = ("ok", "bad", "warn", "unknown")
MARKS = ("add", "del", "bad")


def validate_exhibit(ex, where, errors):
    kind = ex.get("type")
    if kind not in EXHIBITS:
        errors.append(f"{where}.type: must be one of {', '.join(EXHIBITS)}")
        return
    if ex.get("caption") is not None and not isinstance(ex["caption"], str):
        errors.append(f"{where}.caption: expected a string")
    field, lo, hi, texts = EXHIBITS[kind]
    entries = ex.get(field)
    if not isinstance(entries, list) or not lo <= len(entries) <= hi:
        errors.append(f"{where}.{field}: give {lo} to {hi} entries")
        entries = entries if isinstance(entries, list) else []
    for k in {"compare": ("left", "right"), "code": ("ref",)}.get(kind, ()):
        if not isinstance(ex.get(k), str):
            errors.append(f"{where}.{k}: missing")
    total = ex.get("total")
    if kind == "tally" and (not isinstance(total, int) or isinstance(total, bool) or total < 1):
        errors.append(f"{where}.total: must be a whole number above 0")
        total = None
    for j, e in enumerate(entries):
        w = f"{where}.{field}[{j}]"
        if not isinstance(e, dict):
            errors.append(f"{w}: expected an object")
            continue
        for k in texts:
            if not isinstance(e.get(k), str):
                errors.append(f"{w}.{k}: missing")
        if e.get("status") is not None and e["status"] not in STATUSES:
            errors.append(f"{w}.status: must be one of {', '.join(STATUSES)}")
        if kind == "places" and e.get("status") not in STATUSES:
            errors.append(f"{w}.status: must be one of {', '.join(STATUSES)}")
        if kind == "tally":
            v = e.get("value")
            if not isinstance(v, int) or isinstance(v, bool) or v < 0 or (total and v > total):
                errors.append(f"{w}.value: must be a whole number from 0 to total")
        if kind == "code":
            if e.get("mark") is not None and e["mark"] not in MARKS:
                errors.append(f"{w}.mark: must be one of {', '.join(MARKS)}")
            if e.get("n") is not None and (not isinstance(e["n"], int) or isinstance(e["n"], bool)):
                errors.append(f"{w}.n: expected a line number")
        for k in ("ref", "sub"):
            if e.get(k) is not None and not isinstance(e[k], str):
                errors.append(f"{w}.{k}: expected a string")


CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def word_count(text):
    """Words in Latin-script text; two CJK characters count as one word."""
    text = str(text or "")
    cjk = len(CJK.findall(text))
    return len(CJK.sub(" ", text).split()) + (cjk + 1) // 2


BODY_WORDS, SUMMARY_WORDS, PAGE_WORDS = 40, 60, 450


def exhibit_text(ex):
    parts = [ex.get("caption"), ex.get("left"), ex.get("right")]
    field = EXHIBITS.get(ex.get("type"), ("",))[0]
    for e in ex.get(field) or []:
        if isinstance(e, dict):
            parts += [e.get(k) for k in ("left", "right", "text", "label", "sub")]
    return " ".join(p for p in parts if isinstance(p, str))


def text_warnings(b):
    """Advice, not errors: the page renders anyway. Keeps briefings short and visual."""
    warns = []
    summ = b.get("summary") or {}
    n = word_count(summ.get("text"))
    if n > SUMMARY_WORDS:
        warns.append(f"summary.text: {n} words. Keep it to {SUMMARY_WORDS} or fewer.")
    shown = n + sum(word_count(d) for d in summ.get("did") or []) + word_count(summ.get("state"))
    items = b.get("items") or []
    pictured = 0
    for i, it in enumerate(items):
        n = word_count(it.get("body"))
        shown += n + word_count(it.get("title")) + word_count(exhibit_text(it.get("exhibit") or {}))
        if n > BODY_WORDS:
            warns.append(f"items[{i}].body: {n} words. Keep it to {BODY_WORDS} or fewer; move evidence to "
                         "`detail` (shown collapsed) or into the exhibit.")
        if it.get("exhibit"):
            pictured += 1
        elif it.get("kind") in ("call", "decided") or it.get("urgent"):
            warns.append(f"items[{i}]: {'the urgent' if it.get('urgent') else 'a ' + it.get('kind')} item has no exhibit. "
                         "Show the finding as a picture (see reference.md).")
    if items and pictured * 2 < len(items):
        warns.append(f"items: only {pictured} of {len(items)} items have an exhibit. Aim for at least half.")
    if shown > PAGE_WORDS:
        warns.append(f"briefing: {shown} words on the page before details and the question. Aim for {PAGE_WORDS} "
                     "or fewer: cut items, shorten bodies, or show more as exhibits.")
    return warns


def validate(b):
    errors = []

    def need(obj, key, typ, where, optional=False):
        if not isinstance(obj, dict) or key not in obj or obj[key] is None:
            if not optional:
                errors.append(f"{where}.{key}: missing")
            return None
        if not isinstance(obj[key], typ):
            errors.append(f"{where}.{key}: expected {typ.__name__ if isinstance(typ, type) else '/'.join(t.__name__ for t in typ)}")
            return None
        return obj[key]

    if not isinstance(b, dict):
        return ["briefing: expected a JSON object"]
    if b.get("version") != 1:
        errors.append("version: must be 1")
    bid = need(b, "id", str, "briefing")
    if bid and not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", bid):
        errors.append("briefing.id: use letters, digits, dot, dash or underscore only")
    proj = need(b, "project", dict, "briefing")
    if proj is not None:
        need(proj, "name", str, "project")
        need(proj, "path", str, "project")
    ses = need(b, "session", dict, "briefing")
    if ses is not None:
        if ses.get("agent") not in AGENTS:
            errors.append(f"session.agent: must be one of {', '.join(AGENTS)}")
        for k in ("id", "title", "started", "ended"):
            need(ses, k, str, "session")
    need(b, "created", str, "briefing")
    summ = need(b, "summary", dict, "briefing")
    if summ is not None:
        need(summ, "text", str, "summary")
        did = need(summ, "did", list, "summary", optional=True)
        if did and not all(isinstance(x, str) for x in did):
            errors.append("summary.did: every entry must be a string")
        need(summ, "state", str, "summary", optional=True)
    items = need(b, "items", list, "briefing")
    urgent = 0
    for i, it in enumerate(items or []):
        w = f"items[{i}]"
        if not isinstance(it, dict):
            errors.append(f"{w}: expected an object")
            continue
        if it.get("kind") not in KINDS:
            errors.append(f"{w}.kind: must be one of {', '.join(KINDS)}")
        need(it, "title", str, w)
        need(it, "body", str, w)
        urgent += bool(it.get("urgent"))
        refs = need(it, "refs", list, w, optional=True)
        if refs and not all(isinstance(r, str) for r in refs):
            errors.append(f"{w}.refs: every ref must be a string")
        opts = need(it, "options", list, w, optional=True)
        for j, o in enumerate(opts or []):
            if not isinstance(o, dict) or not isinstance(o.get("label"), str):
                errors.append(f"{w}.options[{j}].label: missing")
            elif o.get("prompt") is not None and not isinstance(o["prompt"], str):
                errors.append(f"{w}.options[{j}].prompt: expected a string")
        if it.get("kind") == "call" and not opts:
            errors.append(f"{w}: a 'call' item needs options")
        need(it, "detail", str, w, optional=True)
        ex = need(it, "exhibit", dict, w, optional=True)
        if ex is not None:
            validate_exhibit(ex, f"{w}.exhibit", errors)
    if urgent > 1:
        errors.append("items: mark at most one item urgent")
    if find_secrets(json.dumps(b, ensure_ascii=False)):
        errors.append("briefing: contains what looks like an API key or token. Describe it (\"the MiniMax key\") instead of including it")
    q = b.get("question", "missing")
    if q == "missing":
        errors.append("briefing.question: missing (use null only when no question is worth asking)")
    elif q is not None:
        if not isinstance(q, dict):
            errors.append("question: expected an object or null")
        else:
            for k in ("text", "answer", "explanation"):
                need(q, k, str, "question")
            need(q, "area", str, "question", optional=True)
            need(q, "why", str, "question", optional=True)
            choices = need(q, "choices", list, "question") or []
            keys = []
            for j, c in enumerate(choices):
                if not isinstance(c, dict) or not isinstance(c.get("key"), str) or not isinstance(c.get("text"), str):
                    errors.append(f"question.choices[{j}]: needs key and text")
                else:
                    keys.append(c["key"])
            if choices and not 2 <= len(choices) <= 5:
                errors.append("question.choices: give 2 to 5 choices")
            if len(set(keys)) != len(keys):
                errors.append("question.choices: keys must be unique")
            if keys and q.get("answer") not in keys:
                errors.append("question.answer: must be one of the choice keys")
            for j, s in enumerate(need(q, "path", list, "question", optional=True) or []):
                if not isinstance(s, dict) or not isinstance(s.get("text"), str):
                    errors.append(f"question.path[{j}].text: missing")
    return errors


def page_html(b):
    viewer = SKILL_DIR / "viewer"
    data = json.dumps(b, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")
    template = (viewer / "briefing.html").read_text()
    return (template
            .replace("{{TITLE}}", html.escape(f"Briefing · {b['project']['name']} · {b['session']['title']}"))
            .replace("/*{{CSS}}*/", (viewer / "briefing.css").read_text())
            .replace("/*{{JS}}*/", (viewer / "briefing.js").read_text())
            .replace("{{DATA}}", data))


def save_briefing(b, store):
    out = store / "briefings"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{b['id']}.json").write_text(json.dumps(b, ensure_ascii=False, indent=2))
    page = out / f"{b['id']}.html"
    page.write_text(page_html(b))
    return page


def cmd_render(args):
    try:
        b = json.loads(Path(args.file).read_text())
    except (OSError, ValueError) as err:
        raise SystemExit(f"plumb: cannot read {args.file}: {err}")
    errors = validate(b)
    if errors:
        print("plumb: the briefing is not valid. Fix these and run render again:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    warns = text_warnings(b)
    if warns:
        print("plumb: the page renders, but it is harder to read than it needs to be. Fix these and run render again:",
              file=sys.stderr)
        for w in warns:
            print(f"  - {w}", file=sys.stderr)
    root = Path(b["project"]["path"]).expanduser()
    if args.out:
        out = Path(args.out).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        page = out / f"{b['id']}.html"
        (out / f"{b['id']}.json").write_text(json.dumps(b, ensure_ascii=False, indent=2))
        page.write_text(page_html(b))
        print(f"Briefing page: {page}")
        return 0
    # Sandboxed agents (Codex's default workspace-write mode, for one) may not write outside the project.
    # Plumb never writes inside the project, so fall back to the temp folder, which sandboxes allow.
    store, note = store_dir(root), ""
    try:
        page = save_briefing(b, store)
    except OSError:
        store = Path(tempfile.gettempdir()) / "plumb" / store.name
        try:
            page = save_briefing(b, store)
        except OSError as err:
            print(f"plumb: can't save the page anywhere here ({err.strerror}). The agent may be in a read-only "
                  "sandbox. Give the briefing in chat instead.", file=sys.stderr)
            return 3
        note = (f"Note: {tilde(store_dir(root))} isn't writable here (probably a sandbox), so the page went to a "
                f"temporary folder, which the system clears eventually. To keep briefings, allow writing to "
                f"{tilde(plumb_home())} or set PLUMB_HOME to a writable folder.")
    try:
        idx = load_index(root)
        idx.setdefault("project", str(root.resolve()))
        idx.setdefault("briefed", {})[b["session"]["id"]] = b["created"]
        (store / "index.json").write_text(json.dumps(idx, indent=2))
    except OSError:
        pass  # the page matters; the "briefed" marker is a convenience
    print(f"Briefing page: {page}")
    if note:
        print(note)
    if args.open:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        try:
            if shutil.which(opener):
                subprocess.run([opener, str(page)], check=False, capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            pass  # a sandbox may block launching the browser; the path is printed above
    return 0


# --- installing for other agents -------------------------------------------------

INSTALL_MARKER = ".plumb-install"


def codex_skill_text(src, target, name):
    """SKILL.md for agents that don't fill in Claude Code's ${...} placeholders: absolute paths, plain frontmatter."""
    m = re.match(r"^---\n(.*?)\n---\n", src, re.S)
    if not m:
        raise SystemExit("plumb: SKILL.md has no frontmatter")
    desc = re.search(r"^description:\s*(.+)$", m.group(1), re.M).group(1).strip().strip('"')
    body = (src[m.end():]
            .replace(" --exclude ${CLAUDE_SESSION_ID}", "")
            .replace("${CLAUDE_SKILL_DIR}", str(target))
            .replace("(`$ARGUMENTS`)", "(in their request)"))
    left = re.findall(r"\$\{CLAUDE_[A-Z_]+\}|\$ARGUMENTS", body)
    if left:
        raise SystemExit(f"plumb: SKILL.md still has Claude Code placeholders after conversion: {', '.join(sorted(set(left)))}")
    return f"---\nname: {name}\ndescription: {json.dumps(desc, ensure_ascii=False)}\n---\n" + body


def cmd_install(args):
    target = Path(args.dir).expanduser() / args.name
    if target.exists() and not (target / INSTALL_MARKER).exists():
        print(f"plumb: {tilde(target)} exists and wasn't installed by Plumb; not touching it. Use --name.", file=sys.stderr)
        return 1
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(SKILL_DIR, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    (target / "SKILL.md").write_text(codex_skill_text((SKILL_DIR / "SKILL.md").read_text(), target, args.name))
    (target / "agents").mkdir(exist_ok=True)
    (target / "agents" / "openai.yaml").write_text(
        'interface:\n'
        '  display_name: "Plumb"\n'
        '  short_description: "Briefings on what your coding agents did, checked against the project now"\n'
        f'  default_prompt: "Use ${args.name} to brief me on a recent agent session in this project."\n')
    (target / INSTALL_MARKER).write_text(json.dumps({"from": str(SKILL_DIR), "installed": dt.datetime.now().isoformat(timespec="seconds")}) + "\n")
    print(f"Installed the Plumb skill for Codex at {tilde(target)}.")
    print(f"In Codex, type ${args.name}, or ask to be briefed on a recent agent session. "
          f"Run this command again after updating Plumb.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="plumb.py", description="Helper for the /plumb:brief skill.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sessions", help="list recent agent sessions for a project")
    s.add_argument("--project", help="project folder (default: the git root of the current folder)")
    s.add_argument("--limit", type=int, default=12)
    s.add_argument("--exclude", help="session id to leave out (the session running the skill)")
    s.add_argument("--match", help="only sessions whose title or requests contain all these words")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_sessions)
    d = sub.add_parser("digest", help="condense one session log")
    d.add_argument("session", help="session id (or a unique prefix), or a path to the log")
    d.add_argument("--max-chars", type=int, default=90_000)
    d.set_defaults(func=cmd_digest)
    st = sub.add_parser("state", help="summarize the project as it is now")
    st.add_argument("--project")
    st.add_argument("--since", help="also list commits since this date/time (e.g. the session start)")
    st.set_defaults(func=cmd_state)
    r = sub.add_parser("render", help="validate a briefing JSON file and write the HTML page")
    r.add_argument("file")
    r.add_argument("--open", action="store_true", help="open the page in the browser")
    r.add_argument("--out", help="write here instead of the Plumb store (used by tests)")
    r.set_defaults(func=cmd_render)
    i = sub.add_parser("install", help="install the skill for another agent (codex)")
    i.add_argument("agent", choices=["codex"])
    i.add_argument("--dir", default=str(HOME / ".agents" / "skills"), help="skills folder (default: ~/.agents/skills)")
    i.add_argument("--name", default="plumb-brief", help="skill name in that agent (default: plumb-brief)")
    i.set_defaults(func=cmd_install)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
