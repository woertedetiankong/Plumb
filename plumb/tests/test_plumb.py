"""Tests for plumb.py: log readers, session discovery, digest, redaction, validation and rendering.

Run: python3 -m unittest discover -s plumb/tests
"""

import copy
import json
import os
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
            # Installing again replaces Plumb's own copy...
            with redirect_stdout(StringIO()):
                self.assertEqual(plumb.main(["install", "codex", "--dir", d]), 0)
            # ...but never a folder someone else put there.
            (Path(d) / "mine").mkdir()
            with redirect_stderr(StringIO()):
                self.assertEqual(plumb.main(["install", "codex", "--dir", d, "--name", "mine"]), 1)


if __name__ == "__main__":
    unittest.main()
