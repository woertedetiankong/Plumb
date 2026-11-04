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
| `exhibit` | object | One picture that shows the finding (see Exhibits). Expected for `call`, `decided` and the urgent item, and for at least half of all items. |
| `body` | string | 1 or 2 sentences, 40 words at most: what the picture doesn't show, usually why it matters. |
| `detail` | string | Optional. The longer evidence, shown collapsed under "Details and evidence". |
| `urgent` | boolean | Optional. At most one item in the briefing. |
| `refs` | list of strings | Optional `file:line` references or commands that back the item. Shown collapsed. |
| `options` | list | Required for `call`, optional for `decided`. Each option has a `label`, plus optional `recommended: true` and `prompt` (a ready-to-paste instruction for the user's agent; the page copies it when clicked). |

## Exhibits

Every exhibit has a `type` and an optional `caption` (one sentence: what to notice). Pick the type from what the finding is:

| The finding is… | `type` | Fields |
|---|---|---|
| A claim, request or plan next to what's true now ("said X, actually Y"; "asked for X, got Y") | `compare` | `left` and `right`: the column names, such as "Agent said" and "Project now". `rows`: 1 to 6 of `{ "left", "right", "status" }`. |
| A sequence where something goes wrong: a request path, a race, a failure mode | `flow` | `steps`: 2 to 7 of `{ "text", "ref", "bad" }`. Mark the step where it goes wrong `"bad": true`. Five steps or fewer draw left to right. |
| A change that should reach several places: copies, configs, environments, clients | `places` | `places`: 1 to 12 of `{ "label", "sub", "status" }`. `status` is required here. |
| A count: tests, cases, clips, rows, before and after | `tally` | `total`: a whole number. `rows`: 1 to 4 of `{ "label", "value", "status" }`, each `value` from 0 to `total`. Totals up to 60 draw one square per unit; larger ones draw a bar. |
| Order or timing: what happened when, how long something has been left, a retry schedule | `timeline` | `events`: 2 to 8 of `{ "when", "text", "status" }`. `when` is short: `Oct 21`, `14:02`, `5 s`. |
| A few lines of real code, or what was removed or added | `code` | `ref`: `file:line`. `lines`: 1 to 14 of `{ "n", "text", "mark" }`. `n` is the line number (leave it out for removed lines). `mark` is `add`, `del` or `bad`. |

`status` is `ok`, `bad`, `warn` or `unknown`, optional except in `places`. Each one is drawn with its own icon as well as a colour. Text in exhibits supports `` `code` `` and `**bold**`; keep each entry to a short phrase.

```json
"exhibit": {
  "type": "compare",
  "left": "Agent said", "right": "Project now",
  "rows": [
    { "left": "All 80 clips passed the listen-back check", "right": "The check only compares word counts", "status": "bad" },
    { "left": "The dev server is stopped", "right": "PID 4121 still listens on :5173", "status": "bad" }
  ]
}
```

## Question

| Field | Type | Notes |
|---|---|---|
| `area` | string | Optional. The file the question is about, relative to the project. A right answer counts for the map area that holds it. |
| `depth` | number | Optional. What a right answer shows: `1` contract, `2` shape (the default), `3` every line. |
| `text` | string | The question. Describe a concrete situation. |
| `choices` | list | 4 choices of `{ "key": "A", "text": "...", "note": "why this is wrong" }`. The right choice needs no note. |
| `answer` | string | The key of the right choice. |
| `explanation` | string | What actually happens, in 1 to 3 sentences. |
| `path` | list | Optional. The steps, as `{ "text": "...", "ref": "file:line", "bad": true }`. `ref` and `bad` are optional. Drawn as a `flow` exhibit after the reader answers. |
| `why` | string | Optional. Why it matters, tied to an item. |

## Length

`render` warns, but still writes the page, when a `body` is over 40 words, `summary.text` is over 60 words, a `call`, `decided` or urgent item has no exhibit, fewer than half the items have one, or the page shows more than 450 words before the collapsed details and the question. Two CJK characters count as one word. Fix the warnings and render again.

## Text formatting

Text fields support `` `code` ``, `**bold**`, paragraphs separated by a blank line, and lists made of lines starting with `- `. Nothing else is interpreted, and HTML is shown as plain text.
