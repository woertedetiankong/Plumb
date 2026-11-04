"""Tests for plumb.py: log readers, session discovery, digest, redaction, validation and rendering.

Run: python3 -m unittest discover -s plumb/tests
"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent / "skills" / "brief"
sys.path.insert(0, str(SKILL / "scripts"))
import plumb  # noqa: E402
import mapserve  # noqa: E402

# Built at runtime so no key-shaped literal sits in the repo.
FAKE_SK = "sk-" + "Ab3" * 12
FAKE_GOOGLE = "AQ." + "Xy7_" * 10


def jl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def claude_records(cwd):
    ts = lambda m: f"2026-10-29T13:{m:02d}:00.000Z"
    return [
        {"type": "user", "cwd": cwd, "timestamp": ts(0), "isMeta": True, "message": {"role": "user", "content": "meta"}},
        {"type": "user", "cwd": cwd, "timestamp": ts(1), "message": {"role": "user", "content": "<command-name>/model</command-name>\n<command-args></command-args>"}},
        {"type": "user", "cwd": cwd, "timestamp": ts(2), "message": {"role": "user", "content": "Make refunds survive timeouts"}},
        {"type": "assistant", "cwd": cwd, "timestamp": ts(3), "message": {"role": "assistant", "model": "claude-test", "content": [
            {"type": "text", "text": "Reading the refunds code first."},
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": f"git commit -m wip && export API_KEY={FAKE_SK}"}},
            {"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": cwd + "/payments/refunds.py", "old_string": "a", "new_string": "a\nb\nc"}},
            {"type": "tool_use", "id": "t3", "name": "Bash", "input": {"command": "nohup node server.mjs", "run_in_background": True}},
            {"type": "tool_use", "id": "t4", "name": "Read", "input": {"file_path": cwd + "/x.py"}}]}},
        {"type": "user", "cwd": cwd, "timestamp": ts(4), "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": [{"type": "text", "text": "Exit code 1 boom"}]}]}},
        {"type": "attachment", "cwd": cwd, "timestamp": ts(5), "attachment": {"type": "queued_command", "prompt": "Also check webhooks", "origin": {"kind": "human"}}},
        {"type": "attachment", "cwd": cwd, "timestamp": ts(5), "attachment": {"type": "queued_command", "prompt": "<task-notification>\n<status>completed</status>\n<summary>Tests ran</summary>\n</task-notification>"}},
        {"type": "assistant", "cwd": cwd, "timestamp": ts(6), "isSidechain": True, "message": {"role": "assistant", "content": [{"type": "text", "text": "SIDECHAIN"}]}},
        {"type": "assistant", "cwd": cwd, "timestamp": ts(7), "message": {"role": "assistant", "content": [{"type": "text", "text": "Done. " + "All 212 tests pass. " * 40}]}},
        {"type": "system", "cwd": cwd, "timestamp": ts(8), "subtype": "compact_boundary", "content": "Conversation compacted"},
        {"type": "user", "cwd": cwd, "timestamp": ts(8), "isCompactSummary": True, "message": {"role": "user", "content": "This session is being continued from a previous conversation. Summary:\nThe user wanted retries."}},
        {"type": "user", "cwd": cwd, "timestamp": ts(9), "message": {"role": "user", "content": "\n\n<pasted_content id=\"ab\">\nPlease also add a test\n</pasted_content id=\"ab\">"}},
        {"type": "assistant", "cwd": cwd, "timestamp": ts(10), "message": {"role": "assistant", "content": [{"type": "text", "text": "Added the test."}]}},
        {"type": "ai-title", "aiTitle": "Refund timeouts"},
        {"type": "cost-state", "totalCostUSD": 1.5, "totalLinesAdded": 10, "totalLinesRemoved": 2},
    ]


def codex_records(cwd):
    ts = lambda m: f"2026-10-30T05:{m:02d}:00.000Z"
    return [
        {"type": "session_meta", "timestamp": ts(0), "payload": {"id": "019a-codex-1", "cwd": cwd}},
        {"type": "turn_context", "timestamp": ts(0), "payload": {"cwd": cwd, "model": "gpt-test"}},
        {"type": "response_item", "timestamp": ts(1), "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>x</environment_context>"}]}},
        {"type": "response_item", "timestamp": ts(1), "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Fix the search index"}]}},
        {"type": "response_item", "timestamp": ts(2), "payload": {"type": "custom_tool_call", "name": "exec", "input": 'text(await tools.exec_command({cmd:"npm test"}))'}},
        {"type": "response_item", "timestamp": ts(3), "payload": {"type": "custom_tool_call_output", "output": [{"type": "input_text", "text": '{"exit_code":1,"output":"2 failing"}'}]}},
        {"type": "response_item", "timestamp": ts(4), "payload": {"type": "custom_tool_call", "name": "exec", "input": "apply_patch <<'P'\n*** Begin Patch\n*** Update File: src/search.ts\n@@\n*** End Patch\nP"}},
        {"type": "response_item", "timestamp": ts(5), "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Fixed; tests pass."}]}},
    ]


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.project = (base / "shop").resolve()
        (self.project / "payments").mkdir(parents=True)
        self.other = (base / "other").resolve()
        self.other.mkdir()
        os.environ["PLUMB_CLAUDE_DIR"] = str(base / "claude")
        os.environ["PLUMB_CODEX_DIR"] = str(base / "codex")
        os.environ["PLUMB_HOME"] = str(base / "plumbhome")
        self.claude_log = jl(base / "claude" / "-shop" / "aaaa1111-2222-3333-4444-555566667777.jsonl", claude_records(str(self.project)))
        self.codex_log = jl(base / "codex" / "2026" / "10" / "30" / "rollout-2026-10-30T05-00-00-019a-codex-1.jsonl", codex_records(str(self.project)))
        jl(base / "claude" / "-other" / "bbbb.jsonl", claude_records(str(self.other)))
        old = time.time() - 3600
        for p in (self.claude_log, self.codex_log):
            os.utime(p, (old, old))

    def tearDown(self):
        for k in ("PLUMB_CLAUDE_DIR", "PLUMB_CODEX_DIR", "PLUMB_HOME"):
            os.environ.pop(k, None)
        self.tmp.cleanup()


class ReaderTest(Env):
    def test_claude_reader(self):
        meta, events = plumb.read_claude(self.claude_log)
        users = [e["text"] for e in events if e["kind"] == "user"]
        self.assertEqual(users, ["(ran /model)", "Make refunds survive timeouts",
                                 "(sent while the agent was working) Also check webhooks", "Please also add a test"])
        self.assertEqual(meta["title"], "Refund timeouts")
        self.assertEqual(meta["cost_usd"], 1.5)
        self.assertEqual(meta["models"], {"claude-test"})
        kinds = [e["kind"] for e in events]
        self.assertIn("error", kinds)
        self.assertNotIn("SIDECHAIN", json.dumps([e["text"] for e in events]))
        notes = [e["text"] for e in events if e["kind"] == "note"]
        self.assertTrue(any("background task completed: Tests ran" in n for n in notes))
        self.assertTrue(any(n.startswith("context compacted") for n in notes))
        self.assertTrue(any("The user wanted retries." in n for n in notes))
        edits = [e for e in events if e["kind"] == "edit"]
        self.assertEqual(len(edits), 1)
        self.assertIn("+2 lines", edits[0]["text"])
        self.assertFalse(any("x.py" in e["text"] for e in events))  # Read calls are left out

    def test_codex_reader(self):
        meta, events = plumb.read_codex(self.codex_log)
        self.assertEqual(meta["id"], "019a-codex-1")
        self.assertEqual([e["text"] for e in events if e["kind"] == "user"], ["Fix the search index"])
        self.assertIn("$ npm test", [e["text"] for e in events if e["kind"] == "tool"])
        self.assertEqual([e["path"] for e in events if e["kind"] == "edit"], ["src/search.ts"])
        self.assertTrue(any(e["kind"] == "error" for e in events))
        self.assertEqual([e["text"] for e in events if e["kind"] == "agent"], ["Fixed; tests pass."])


class SessionsTest(Env):
    def test_finds_only_this_project(self):
        rows = plumb.find_sessions(self.project, 10)
        self.assertEqual(sorted(r["agent"] for r in rows), ["claude-code", "codex"])
        claude = next(r for r in rows if r["agent"] == "claude-code")
        self.assertEqual(claude["requests"], 3)  # "(ran /model)" is not a request
        self.assertFalse(claude["live"])
        self.assertIsNone(claude["briefed"])

    def test_exclude_and_live(self):
        os.utime(self.codex_log, None)  # just written: looks like the running session
        rows = plumb.find_sessions(self.project, 10)
        self.assertTrue(next(r for r in rows if r["agent"] == "codex")["live"])
        rows = plumb.find_sessions(self.project, 10, exclude="aaaa1111")
        self.assertEqual([r["agent"] for r in rows], ["codex"])

    def test_picker_fields(self):
        rows = {r["agent"]: r for r in plumb.find_sessions(self.project, 10)}
        claude, codex = rows["claude-code"], rows["codex"]
        self.assertEqual(claude["label"], "Refund timeouts")             # the session title
        self.assertEqual(codex["label"], "Fix the search index")         # no title: the first request
        self.assertEqual(claude["changes"], 1 + 2)                       # one edit, a commit, a nohup
        self.assertEqual(codex["changes"], 1)                            # one apply_patch
        self.assertNotIn("_search", claude)

    def test_match_searches_every_request(self):
        self.assertEqual([r["agent"] for r in plumb.find_sessions(self.project, 10, match="WEBHOOKS")], ["claude-code"])
        self.assertEqual([r["agent"] for r in plumb.find_sessions(self.project, 10, match="search index")], ["codex"])
        self.assertEqual(plumb.find_sessions(self.project, 10, match="refund nonsense"), [])

    def test_sessions_text_output(self):
        out = StringIO()
        with redirect_stdout(out):
            plumb.main(["sessions", "--project", str(self.project), "--exclude", "${CLAUDE_SESSION_ID}"])
        text = out.getvalue()
        self.assertIn(" 1  ", text)
        self.assertIn("1 edit in 1 file", text)
        self.assertIn("id aaaa1111", text)

    def test_resolve_by_prefix(self):
        self.assertEqual(plumb.resolve_session("aaaa1111"), self.claude_log)
        with self.assertRaises(SystemExit):
            plumb.resolve_session("no-such-session")


class DigestTest(Env):
    def test_digest_sections_and_redaction(self):
        out = StringIO()
        with redirect_stdout(out):
            plumb.main(["digest", "aaaa1111"])
        text = out.getvalue()
        self.assertIn("# Session digest: Refund timeouts", text)
        self.assertIn("payments/refunds.py (1)", text)
        self.assertIn("git commit -m wip", text)
        self.assertIn("[background] nohup node server.mjs", text)
        self.assertIn("AGENT (report): Done.", text)
        self.assertNotIn(FAKE_SK, text)
        self.assertIn("[secret hidden", text)

    def test_reports_survive_truncation(self):
        text = plumb.build_digest(self.claude_log, 1500)
        self.assertIn("USER: Make refunds survive timeouts", text)
        self.assertIn("Dropped", text)
        self.assertNotIn("✎ Edit", text)  # tool lines go first


class FormatTest(unittest.TestCase):
    def test_when(self):
        import datetime as dt
        now = dt.datetime(2026, 11, 3, 9, 0).astimezone()
        at = lambda days, h=6: (now - dt.timedelta(days=days)).replace(hour=h, minute=8)
        self.assertEqual(plumb.when(at(0), now), "today 06:08")
        self.assertEqual(plumb.when(at(1, 22), now), "yesterday 22:08")
        self.assertEqual(plumb.when(at(5), now), "5 days ago")
        self.assertEqual(plumb.when(at(9), now), "Oct 25")
        self.assertEqual(plumb.when(None), "?")

    def test_plural_and_width(self):
        self.assertEqual(plumb.plural(1, "edit"), "1 edit")
        self.assertEqual(plumb.plural(3, "file"), "3 files")
        self.assertEqual(plumb.display_width("语音abc"), 7)


class RedactTest(unittest.TestCase):
    def test_known_formats(self):
        for secret in (FAKE_SK, FAKE_GOOGLE, "AIza" + "B1c" * 12, "ghp_" + "a1B" * 12, "AKIA" + "ABCDEFGH12345678"):
            self.assertNotIn(secret, plumb.redact(f"key: {secret} end"), secret)
        self.assertNotIn("hunter2hunter2hunter2", plumb.redact('password = "hunter2hunter2hunter2"'))
        self.assertNotIn("Zz9" * 8, plumb.redact("export GEMINI_API_KEY=" + "Zz9" * 8))

    def test_leaves_ordinary_text(self):
        for s in ("git log 3463c8c1f0e2d4b5a6978877665544332211aabb", "~/.claude/projects/-Users-me/7762cbf7-f34e-415b-bcc1-a8104500a3e3.jsonl",
                  "toolu_01WbcApfs8eytrg2Lmhwh5ab12CD", "voice/cascade.mjs:27 silenceMs 1000"):
            self.assertEqual(plumb.redact(s), s)


class RenderTest(Env):
    def example(self):
        return json.loads((SKILL / "examples" / "shopfront.json").read_text())

    def test_example_is_valid(self):
        self.assertEqual(plumb.validate(self.example()), [])

    def test_validation_errors(self):
        b = self.example()
        del b["summary"]
        b["items"][0]["urgent"] = b["items"][1]["urgent"] = True
        b["items"][1]["options"] = []
        b["question"]["answer"] = "Z"
        b["items"][3]["body"] = "the key is " + FAKE_SK
        errors = "\n".join(plumb.validate(b))
        for expected in ("summary: missing", "at most one item urgent", "a 'call' item needs options",
                         "question.answer", "looks like an API key"):
            self.assertIn(expected, errors)
        b2 = self.example()
        del b2["question"]
        self.assertTrue(any("question" in e for e in plumb.validate(b2)))
        b2["question"] = None
        self.assertEqual(plumb.validate(b2), [])

    def test_exhibit_errors(self):
        b = self.example()
        b["items"][0]["exhibit"] = {"type": "chart"}
        b["items"][1]["exhibit"] = {"type": "compare", "rows": [{"left": "a"}]}
        b["items"][2]["exhibit"] = {"type": "tally", "total": 3, "rows": [{"label": "x", "value": 4}]}
        b["items"][3]["exhibit"] = {"type": "places", "places": [{"label": "a", "status": "fine"}]}
        b["items"][4]["exhibit"] = {"type": "flow", "steps": [{"text": "only one"}]}
        errors = "\n".join(plumb.validate(b))
        for expected in ("items[0].exhibit.type: must be one of", "items[1].exhibit.left: missing",
                         "items[1].exhibit.rows[0].right: missing", "items[2].exhibit.rows[0].value",
                         "items[3].exhibit.places[0].status", "items[4].exhibit.steps: give 2 to 7"):
            self.assertIn(expected, errors)
        b = self.example()
        b["items"][0]["exhibit"]["lines"][0]["mark"] = "changed"
        self.assertTrue(any("mark: must be one of" in e for e in plumb.validate(b)))

    def test_bars_and_place_groups(self):
        b = self.example()
        b["items"][1]["exhibit"] = {"type": "bars", "unit": "s", "caption": "Stalls dwarf the usual wait.",
                                    "rows": [{"label": "Usual", "value": 2.45}, {"label": "Stall", "value": 22, "display": "22 s or more", "status": "bad"}]}
        b["items"][4]["exhibit"]["groups"] = {"ok": "Tested", "unknown": "Never tried"}
        self.assertEqual(plumb.validate(b), [])
        b["items"][1]["exhibit"]["rows"][0]["value"] = "fast"
        b["items"][1]["exhibit"]["rows"][1]["value"] = True
        b["items"][4]["exhibit"]["groups"] = {"fine": "Tested"}
        errors = "\n".join(plumb.validate(b))
        self.assertIn("items[1].exhibit.rows[0].value: must be a number", errors)
        self.assertIn("items[1].exhibit.rows[1].value: must be a number", errors)
        self.assertIn("items[4].exhibit.groups: map a status", errors)

    def test_exhibit_warnings(self):
        b = self.example()
        del b["items"][1]["exhibit"]["caption"]
        b["items"][2]["exhibit"]["events"][0]["text"] = "The first try goes out to the provider and then waits for its reply"
        warns = "\n".join(plumb.text_warnings(b))
        self.assertIn("items[1].exhibit: no caption", warns)
        self.assertIn("items[2].exhibit.events[0].text: 14 words", warns)
        b = self.example()
        b["items"][0]["exhibit"]["lines"][0]["text"] = "x = " + " + ".join("abcdefghijklmn")
        self.assertEqual(plumb.text_warnings(b), [], "code lines are code, not phrases")

    def test_text_warnings(self):
        self.assertEqual(plumb.text_warnings(self.example()), [])
        b = self.example()
        b["items"][0]["body"] = "word " * 45
        del b["items"][1]["exhibit"]
        for it in b["items"][2:]:
            it["exhibit"] = None
        warns = "\n".join(plumb.text_warnings(b))
        self.assertIn("items[0].body: 45 words", warns)
        self.assertIn("items[1]: a call item has no exhibit", warns)
        self.assertIn("only 1 of 5 items have an exhibit", warns)
        self.assertEqual(plumb.word_count("退款超时后重试"), 4)  # 7 CJK characters
        self.assertEqual(plumb.word_count("run `pytest` 两次"), 3)

    def test_render_prints_warnings_but_writes(self):
        b = self.example()
        b["items"][0]["body"] = "word " * 45
        src = Path(self.tmp.name) / "long.json"
        src.write_text(json.dumps(b))
        err, out = StringIO(), StringIO()
        with redirect_stderr(err), redirect_stdout(out):
            self.assertEqual(plumb.main(["render", str(src), "--out", str(Path(self.tmp.name) / "out")]), 0)
        self.assertIn("items[0].body: 45 words", err.getvalue())
        self.assertIn("Briefing page:", out.getvalue())

    def test_render_writes_page_and_index(self):
        b = self.example()
        b["project"]["path"] = str(self.project)
        b["items"][3]["title"] = "</script><img src=x onerror=alert(1)>"
        src = Path(self.tmp.name) / "b.json"
        src.write_text(json.dumps(b))
        with redirect_stdout(StringIO()):
            self.assertEqual(plumb.main(["render", str(src)]), 0)
        store = plumb.store_dir(self.project)
        page = (store / "briefings" / f"{b['id']}.html").read_text()
        self.assertNotIn("</script><img", page)  # cannot close the data block early
        self.assertIn('"title": "Make refunds survive provider timeouts"'.replace(": ", ":"), page.replace(": ", ":"))
        self.assertIn("/*", page.split("<style>")[0] + "/*")  # template placeholders replaced below
        self.assertNotIn("{{DATA}}", page)
        self.assertNotIn("/*{{JS}}*/", page)
        idx = json.loads((store / "index.json").read_text())
        self.assertIn(b["session"]["id"], idx["briefed"])
        rows = plumb.find_sessions(self.project, 10)
        self.assertEqual(len(rows), 2)

    def test_render_rejects_invalid(self):
        b = copy.deepcopy(self.example())
        b["version"] = 2
        src = Path(self.tmp.name) / "bad.json"
        src.write_text(json.dumps(b))
        err = StringIO()
        from contextlib import redirect_stderr
        with redirect_stderr(err):
            self.assertEqual(plumb.main(["render", str(src), "--out", str(Path(self.tmp.name) / "out")]), 1)
        self.assertIn("version: must be 1", err.getvalue())


class SandboxFallbackTest(Env):
    def test_unwritable_store_falls_back_to_temp(self):
        b = json.loads((SKILL / "examples" / "shopfront.json").read_text())
        b["project"]["path"] = str(self.project)
        src = Path(self.tmp.name) / "b.json"
        src.write_text(json.dumps(b))
        locked = Path(self.tmp.name) / "locked"
        locked.mkdir()
        os.environ["PLUMB_HOME"] = str(locked / "plumb")
        tmp_root = Path(self.tmp.name) / "systemp"
        tmp_root.mkdir()
        old = tempfile.tempdir
        tempfile.tempdir = str(tmp_root)
        out = StringIO()
        locked.chmod(0o500)  # like a sandbox that refuses writes outside the project
        try:
            with redirect_stdout(out):
                self.assertEqual(plumb.main(["render", str(src)]), 0)
        finally:
            locked.chmod(0o700)
            tempfile.tempdir = old
        self.assertIn("temporary folder", out.getvalue())
        self.assertTrue(list(tmp_root.glob("plumb/*/briefings/*.html")))
        self.assertFalse((locked / "plumb").exists())
        tempfile.tempdir = str(tmp_root)
        try:  # the session list still knows it was briefed
            self.assertIn(b["session"]["id"], plumb.load_index(self.project)["briefed"])
        finally:
            tempfile.tempdir = old


class MapTest(Env):
    AREAS = {"areas": [
        {"id": "refunds", "name": "payments", "paths": ["payments"], "need": 3, "why": "it moves money"},
        {"id": "web", "name": "web", "paths": ["web"], "need": 0, "why": ""}]}

    def setUp(self):
        super().setUp()
        (self.project / "payments" / "refunds.py").write_text("a\n" * 10)
        (self.project / "payments" / "webhooks.py").write_text("a\n" * 4)
        (self.project / "web").mkdir()
        (self.project / "web" / "app.js").write_text("a\n" * 5)
        (self.project / "README.md").write_text("hello")
        self.store = plumb.store_dir(self.project)
        src = Path(self.tmp.name) / "areas.json"
        src.write_text(json.dumps(self.AREAS))
        with redirect_stdout(StringIO()):
            self.assertEqual(plumb.main(["areas", "--project", str(self.project), "--set", str(src)]), 0)
        b = json.loads((SKILL / "examples" / "shopfront.json").read_text())
        b["project"]["path"] = str(self.project)
        self.bid = b["id"]
        bsrc = Path(self.tmp.name) / "b.json"
        bsrc.write_text(json.dumps(b))
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(plumb.main(["render", str(bsrc)]), 0)

    def area(self, aid):
        return {a["id"]: a for a in mapserve.map_data(self.project)["areas"]}[aid]

    def answers(self, data):
        mapserve.write_json(self.store / "answers.json", data)

    def test_sizes_count_only_code(self):
        pay = self.project / "payments"
        (pay / "runs.csv").write_text("1,2\n" * 500)
        (pay / "manual.pdf").write_bytes(b"%PDF-1.7\n" + bytes(range(128, 256)) * 50 + b"\n")
        (pay / "fixtures.json").write_text("{}\n" * 400)
        (pay / "config.json").write_text("{}\n" * 3)
        (pay / "client.js").write_text("// generated by protoc, do not edit\n" + "x\n" * 50)
        (pay / "bundle.min.js").write_text("x\n" * 50)
        (pay / "vendor").mkdir()
        (pay / "vendor" / "lib.py").write_text("x\n" * 50)
        (self.project / ".gitattributes").write_text("payments/vendor/** linguist-vendored\n")
        subprocess.run(["git", "init", "-q"], cwd=self.project, check=True)
        refunds = self.area("refunds")
        self.assertEqual((refunds["lines"], refunds["files"]), (17, 3), "refunds.py, webhooks.py and the small config")
        self.assertEqual(mapserve.code_lines("a/data.txt", b"row\n" * 301), 0)
        self.assertEqual(mapserve.code_lines("a/one-line.js", b"x" * 5000), 0)
        self.assertEqual(mapserve.code_lines("a/b.py", b"x\ny"), 2)

    def test_validate_areas(self):
        bad = {"areas": [
            {"id": "a", "name": "a", "paths": ["/etc"], "need": 3, "why": "x"},
            {"id": "a", "name": "b", "paths": ["../up"], "need": 5},
            {"id": "c", "name": "c", "paths": ["src"], "need": 2},
            {"id": "d", "name": "d", "paths": ["src/"], "need": 0}]}
        errors = "\n".join(mapserve.validate_areas(bad))
        for expected in ("areas[0].paths: '/etc'", "areas[1].id: 'a' is used twice", "areas[1].paths: '../up'",
                         "areas[1].need", "areas[2].why", "'src' is already in area 'c'"):
            self.assertIn(expected, errors)
        self.assertEqual(mapserve.validate_areas(self.AREAS), [])

    def test_sizes_and_starting_state(self):
        data = mapserve.map_data(self.project)
        refunds = self.area("refunds")
        self.assertEqual((refunds["lines"], refunds["files"]), (14, 2))
        self.assertEqual(data["unmapped"], {"lines": 1, "files": 1})
        self.assertEqual(refunds["status"], "unknown")  # no evidence is not a gap
        self.assertEqual(self.area("web")["status"], "ok")
        self.assertEqual(len(refunds["calls"]), 1)  # the webhook call; the migration's file isn't in an area
        self.assertEqual(refunds["pending"]["briefing"], self.bid)
        self.assertEqual(refunds["changed"]["sessions"], 1)  # the Claude log edited payments/refunds.py

    def test_evidence_replays_in_order(self):
        self.answers({"briefings": {self.bid: {"picks": {"0": 0}, "answer": {"key": "B", "at": "2026-11-01 09:00"}}}})
        a = self.area("refunds")
        self.assertEqual((a["you"], a["status"], a["source"], a["stale"]), (2, "thin", "question", False))
        self.assertEqual(a["calls"], [])  # picked
        self.assertIsNone(a["pending"])
        self.answers({"briefings": {self.bid: {"answer": {"key": "B", "at": "2026-11-01 09:00"}}},
                      "areas": {"refunds": {"level": 3, "at": "2026-11-02 09:00"}}})
        self.assertEqual((self.area("refunds")["you"], self.area("refunds")["status"]), (3, "solid"))
        self.answers({"briefings": {self.bid: {"answer": {"key": "A", "at": "2026-11-02 10:00"}}},
                      "areas": {"refunds": {"level": 3, "at": "2026-11-02 09:00"}}})
        self.assertEqual((self.area("refunds")["you"], self.area("refunds")["status"]), (1, "gap"))  # wrong at shape caps it at contract

    def test_agent_changes_after_a_check_lower_it(self):
        # The fixture's Claude session edited payments/refunds.py on 2026-10-29; this answer came before it.
        self.answers({"briefings": {self.bid: {"answer": {"key": "B", "at": "2026-10-28 09:00"}}}})
        a = self.area("refunds")
        self.assertEqual((a["you"], a["stale"], a["status"]), (1, True, "gap"))

    def test_record_and_levels(self):
        with self.assertRaises(ValueError):
            mapserve.record(self.store, self.bid, {"answer": "Z"})
        with self.assertRaises(ValueError):
            mapserve.record(self.store, self.bid, {"item": 3, "opt": 0})  # an fyi item has no options
        with self.assertRaises(ValueError):
            mapserve.record(self.store, "nope", {"answer": "B"})
        mapserve.record(self.store, self.bid, {"answer": "A"})
        mapserve.record(self.store, self.bid, {"answer": "B"})  # the first answer counts
        mapserve.record(self.store, self.bid, {"item": 0, "opt": 1})
        self.assertEqual(mapserve.briefing_state(self.store, self.bid), {"picks": {"0": 1}, "answer": "A"})
        mapserve.record(self.store, self.bid, {"clear": True})
        self.assertEqual(mapserve.briefing_state(self.store, self.bid), {"picks": {}, "answer": None})
        mapserve.set_need(self.store, "web", 2)
        self.assertIn("you said so", json.loads((self.store / "areas.json").read_text())["areas"][1]["why"])
        with self.assertRaises(ValueError):
            mapserve.set_level(self.store, "nope", 2)

    def test_pages_link_to_the_map(self):
        page = (self.store / "briefings" / f"{self.bid}.html").read_text()
        self.assertIn('data-map="../map.html"', page)
        self.assertTrue((self.store / "map.html").exists())
        self.assertIn("map-data", (self.store / "map.html").read_text())

    def test_server_guards(self):
        import http.client
        import threading
        from http.server import ThreadingHTTPServer
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), mapserve.Handler)
        mapserve.Handler.port, mapserve.Handler.token = httpd.server_port, "tok"
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        port = httpd.server_port

        def req(method, path, body=None, headers=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            h = {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json"}
            h.update(headers or {})
            c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
            r = c.getresponse()
            data = r.read()
            c.close()
            return r.status, data
        try:
            name = self.store.name
            self.assertEqual(req("GET", f"/p/{name}/map")[0], 200)
            status, page = req("GET", f"/p/{name}/b/{self.bid}")
            self.assertEqual(status, 200)
            self.assertIn(b'name="plumb-server"', page)
            self.assertEqual(req("GET", f"/p/{name}/map", headers={"Host": f"evil.example:{port}"})[0], 403)
            body = {"store": name, "briefing": self.bid, "change": {"answer": "B"}}
            self.assertEqual(req("POST", "/api/record", body)[0], 403)  # no token
            self.assertEqual(req("POST", "/api/record", body, {"X-Plumb-Token": "tok", "Origin": "https://evil.example"})[0], 403)
            self.assertEqual(req("POST", "/api/record", body, {"X-Plumb-Token": "tok"})[0], 200)
            self.assertEqual(mapserve.briefing_state(self.store, self.bid)["answer"], "B")
            self.assertEqual(req("POST", "/api/record", {"store": "../x", "briefing": self.bid}, {"X-Plumb-Token": "tok"})[0], 404)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_open_replaces_a_server_running_older_code(self):
        os.environ["PLUMB_PORT"] = "7371"
        old_id = mapserve.CODE_ID
        pids = []
        try:
            os.environ["PLUMB_CODE_ID"] = mapserve.CODE_ID = "before-update"
            port = mapserve.ensure_server()
            first = mapserve.ping(port)
            self.assertEqual(first["code"], "before-update")
            pids.append(first["pid"])
            self.assertEqual(mapserve.ensure_server(), port, "the same code reuses the running server")
            self.assertEqual(mapserve.ping(port)["pid"], first["pid"])
            os.environ["PLUMB_CODE_ID"] = mapserve.CODE_ID = "after-update"
            port = mapserve.ensure_server()
            second = mapserve.ping(port)
            pids.append(second["pid"])
            self.assertEqual(second["code"], "after-update")
            self.assertNotEqual(second["pid"], first["pid"])
            with self.assertRaises(OSError):
                for _ in range(20):
                    os.kill(first["pid"], 0)
                    time.sleep(0.1)
        finally:
            mapserve.CODE_ID = old_id
            for k in ("PLUMB_CODE_ID", "PLUMB_PORT"):
                os.environ.pop(k, None)
            for pid in pids:
                try:
                    os.kill(pid, 15)
                except OSError:
                    pass


class InstallTest(unittest.TestCase):
    def test_codex_install(self):
        with tempfile.TemporaryDirectory() as d:
            with redirect_stdout(StringIO()):
                self.assertEqual(plumb.main(["install", "codex", "--dir", d]), 0)
            target = Path(d) / "plumb-brief"
            text = (target / "SKILL.md").read_text()
            front = text.split("---\n")[1]
            self.assertIn("name: plumb-brief\n", front)
            self.assertIn('description: "Brief the user', front)
            self.assertNotIn("allowed-tools", front)
            self.assertNotIn("${CLAUDE_", text)
            self.assertNotIn("$ARGUMENTS", text)
            self.assertIn(f"python3 {target}/scripts/plumb.py sessions --json", text)
            for f in ("scripts/plumb.py", "viewer/briefing.js", "reference.md", "examples/shopfront.json", "agents/openai.yaml"):
                self.assertTrue((target / f).exists(), f)
            self.assertFalse(list(target.rglob("__pycache__")))
            mtext = (Path(d) / "plumb-map" / "SKILL.md").read_text()
            self.assertIn("name: plumb-map\n", mtext)
            self.assertNotIn("${CLAUDE_", mtext)
            self.assertIn(f"python3 {target}/scripts/plumb.py open map", mtext)
            self.assertIn("$plumb-brief", mtext)
            # Installing again replaces Plumb's own copy...
            with redirect_stdout(StringIO()):
                self.assertEqual(plumb.main(["install", "codex", "--dir", d]), 0)
            # ...but never a folder someone else put there.
            (Path(d) / "mine").mkdir()
            with redirect_stderr(StringIO()):
                self.assertEqual(plumb.main(["install", "codex", "--dir", d, "--name", "mine"]), 1)


if __name__ == "__main__":
    unittest.main()
