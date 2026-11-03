# Briefing format (version 1)

`plumb.py render` checks every field below and lists anything missing or wrong. A complete example is in [examples/shopfront.json](examples/shopfront.json).

## Top level

| Field | Type | Notes |
|---|---|---|
| `version` | `1` | Always 1. |
| `id` | string | Letters, digits, `.`, `-`, `_`. Use `<session start date YYYY-MM-DD>-<first 8 chars of the session id>`. The page is saved under this name, so briefing the same session again replaces its page. |
| `project` | object | `name` (folder name) and `path` (absolute project path; it decides where the briefing is stored). |
| `session` | object | `agent` (`claude-code` or `codex`), `id` (the full session id from `sessions`), `title` (what the session was about, in a few words), `started` and `ended` (local time, `YYYY-MM-DD HH:MM`). |
| `created` | string | When you wrote the briefing, `YYYY-MM-DD HH:MM`. |
| `summary` | object | `text`: 1 to 3 sentences on what the user asked and what happened. `did`: optional list of what the agent did, one short line each. `state`: optional one line on where things stand now, such as what's uncommitted or still running. |
| `items` | list | The findings, described below. 3 to 8 items. |
| `question` | object or `null` | One explain-it-back question, described below. |

## Items

| Field | Type | Notes |
|---|---|---|
| `kind` | string | `call`, `decided`, `fyi`, `unchecked`, or `outside` (see SKILL.md, step 5). |
| `title` | string | The finding in one line. |
| `body` | string | 2 to 5 sentences: what's true, the evidence, and why it matters. |
| `urgent` | boolean | Optional. At most one item in the briefing. |
| `refs` | list of strings | Optional `file:line` references or commands that back the item. |
| `options` | list | Required for `call`, optional for `decided`. Each option has a `label`, plus optional `recommended: true` and `prompt` (a ready-to-paste instruction for the user's agent; the page copies it when clicked). |

## Question

| Field | Type | Notes |
|---|---|---|
| `area` | string | Optional. The file or part of the code it's about. |
| `text` | string | The question. Describe a concrete situation. |
| `choices` | list | 4 choices of `{ "key": "A", "text": "...", "note": "why this is wrong" }`. The right choice needs no note. |
| `answer` | string | The key of the right choice. |
| `explanation` | string | What actually happens, in 1 to 3 sentences. |
| `path` | list | Optional. The steps, as `{ "text": "...", "ref": "file:line", "bad": true }`. `ref` and `bad` are optional. |
| `why` | string | Optional. Why it matters, tied to an item. |

## Text formatting

Text fields support `` `code` ``, `**bold**`, paragraphs separated by a blank line, and lists made of lines starting with `- `. Nothing else is interpreted, and HTML is shown as plain text.
