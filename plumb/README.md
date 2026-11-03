# Plumb

Know the code your agents write.

After Claude Code or Codex works on your project, run `/plumb:brief`. Plumb reads that session's log, checks what the agent claimed against your project as it is now, and opens a one-page briefing:

- **Needs your call:** decisions only you should make, each with options. An option can copy a ready-to-paste instruction for your agent.
- **Decided without asking:** choices the agent made on its own.
- **Worth knowing** and **Not checked:** what's true, and what nobody has verified.
- **One question** about the part that matters most, so you find out whether you actually understand it.

Plumb only reads your project; it never changes it. The briefing is written by the Claude Code session you run it in, using your normal Claude plan. No extra API key is needed.

## Try it locally

```sh
cd your-project
claude --plugin-dir /path/to/plumb
```

Then, in Claude Code:

```text
/plumb:brief              choose from your recent sessions in this project
/plumb:brief voice        sessions whose topic or requests mention "voice"
/plumb:brief 3f9c21ab     one session, by id
```

You decide which sessions get a briefing. Plumb never briefs the session you run it in; it checks other sessions with fresh eyes. To see the list yourself, run `python3 plumb/skills/brief/scripts/plumb.py sessions` inside the project.

After changing Plumb's files, run `/reload-plugins` in the session.

## Install from GitHub

```text
/plugin marketplace add woertedetiankong/Plumb
/plugin install plumb@plumb
```

## What it reads and writes

- **Reads:** Claude Code logs in `~/.claude/projects/` and Codex logs in `~/.codex/sessions/`, only for the project you're in. It also reads your project, through git, the processes it started, and the code the session touched.
- **Writes:** briefings to `~/.plumb/projects/<project>/briefings/`, as a `.json` and an `.html` file each, plus `index.json`, which records which sessions have a briefing. Nothing is written inside your project.
- **Secrets:** logs contain whatever was pasted or run. `plumb.py` hides common key formats (OpenAI-style `sk-`, Google `AIza` and `AQ.`, GitHub, Slack, AWS, JWTs, `*_KEY=` assignments) and any long random-looking token before printing. The renderer refuses a briefing that still contains one.

## Codex

```sh
python3 plumb/skills/brief/scripts/plumb.py install codex
```

This copies the skill to `~/.agents/skills/plumb-brief/` and converts it for Codex. Codex doesn't fill in Claude Code's `${CLAUDE_SKILL_DIR}` and `${CLAUDE_SESSION_ID}`, so the installed copy uses real paths. Then, in Codex, type `$plumb-brief` or ask to be briefed on a recent agent session. Run the command again after updating Plumb. It only ever replaces its own copy.

Codex's default sandbox (workspace-write) only allows writing inside the project and the temp folder, so the page is saved to the temp folder there, and Plumb says so. Inside that sandbox, `ps` is blocked too, so the list of processes still running comes from `lsof`, without start times or memory use.

## Layout

| Path | What it is |
|---|---|
| `.claude-plugin/plugin.json` | Plugin manifest |
| `skills/brief/SKILL.md` | The briefing method the agent follows |
| `skills/brief/reference.md` | The briefing JSON format |
| `skills/brief/scripts/plumb.py` | Lists sessions, writes digests, reports project state, renders pages (Python 3.9+, standard library only) |
| `skills/brief/viewer/` | The page template, styles and script that `render` inlines into each briefing |
| `skills/brief/examples/shopfront.json` | A complete example briefing |
| `tests/` | Unit tests and a headless Chrome test of the page |

## Tests

```sh
python3 -m unittest discover -s plumb/tests
node plumb/tests/viewer.e2e.mjs        # needs Google Chrome; set CHROME to its path elsewhere
```
