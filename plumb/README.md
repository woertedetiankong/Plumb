# Plumb

Know the code your agents write.

After Claude Code or Codex works on your project, run `/plumb:brief`. Plumb reads that session's log, checks what the agent claimed against your project as it is now, and opens a one-page briefing:

- **Needs your call:** decisions only you should make, each with options. An option can copy a ready-to-paste instruction for your agent.
- **Decided without asking:** choices the agent made on its own.
- **Worth knowing** and **Not checked:** what's true, and what nobody has verified.
- **One question** about the part that matters most, so you find out whether you actually understand it.

Each finding is shown as a small picture first (said vs. true, a path that goes wrong, the copies a change reached, a count, a timeline, or the lines of code), with a sentence or two under it. The longer evidence stays collapsed.

Run `/plumb:map` to see your **understanding map**: every area of the project, sized by lines of code and colored by whether you understand it as deeply as its stakes need. The first time, the agent proposes the areas and how deeply each needs understanding (contract, shape or every line), and you confirm them. After that, each right answer to a briefing question moves its area forward, and agent changes since you were last checked move it back a level. Areas nobody has checked yet show as Unchecked, not as gaps; you can also say how well you know an area on the map.

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
/plumb:map                your understanding map (sets up the areas the first time)
/plumb:map redo           propose the areas again
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
- **Writes:** briefings to `~/.plumb/projects/<project>/briefings/`, as a `.json` and an `.html` file each, plus `index.json` (which sessions have a briefing), `areas.json` (your map's areas), `answers.json` (your picks, answers and what you said you know), `map.html`, and caches of line counts and session edits in `cache/`. Nothing is written inside your project.
- **Runs:** `plumb.py open` starts a small page server on `127.0.0.1` (port 7341, or `$PLUMB_PORT`), so clicks on a page are saved and the map stays current. It accepts only requests with its own `Host` and a token it puts into the pages it serves, writes `~/.plumb/server.json` (readable only by you), and stops after 30 idle minutes. If it can't start, the pages open as plain files and answers stay in the browser.
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
| `skills/brief/scripts/mapserve.py` | The map's data, the map page and the local page server, used through `plumb.py` |
| `skills/map/SKILL.md` | How the agent proposes map areas and opens the map |
| `skills/brief/viewer/` | The briefing and map templates, styles and scripts that Plumb inlines into each page |
| `skills/brief/examples/shopfront.json` | A complete example briefing |
| `tests/` | Unit tests, and headless Chrome tests of the briefing and the map |

## Tests

```sh
python3 -m unittest discover -s plumb/tests
node plumb/tests/viewer.e2e.mjs        # needs Google Chrome; set CHROME to its path elsewhere
node plumb/tests/map.e2e.mjs           # the map and a briefing through the local server
```
