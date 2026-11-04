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

Every exhibit has a `type` and a `caption`. The caption is shown above the picture and says what to notice, in one short sentence of 16 words or fewer: "13 days since a person last called", not "Timeline of calls". Pick the type from what the finding is:

| The finding is… | `type` | Fields |
|---|---|---|
| A claim, request or plan next to what's true now ("said X, actually Y"; "asked for X, got Y") | `compare` | `left` and `right`: the column names, such as "Agent said" and "Project now". `rows`: 1 to 6 of `{ "left", "right", "status" }`. |
| A sequence where something goes wrong: a request path, a race, a failure mode | `flow` | `steps`: 2 to 7 of `{ "text", "ref", "bad" }`. Mark the step where it goes wrong `"bad": true`. Five steps or fewer draw left to right. |
| Where something is, or should be: copies, configs, environments, what's in git and what isn't | `places` | `places`: 1 to 12 of `{ "label", "sub", "status" }`. `status` is required here. Places are drawn in groups by status, worst first; `groups` names them for this finding, such as `{ "bad": "Key in plain text", "ok": "Clean" }`. |
| A count out of a total: tests, cases, clips, before and after | `tally` | `total`: a whole number. `rows`: 1 to 4 of `{ "label", "value", "status" }`, each `value` from 0 to `total`. Totals up to 20 draw one square per unit; larger ones a thin bar. |
| Amounts to compare on one scale: durations, sizes, memory, cost, rows | `bars` | `unit`: optional, such as `s` or `GB`. `rows`: 1 to 6 of `{ "label", "value", "display", "status" }`. `value` is a number; `display` replaces the printed value ("22 s or more"). Bars without a `bad` or `warn` status are grey, so the problem is the one in colour. |
| Order or timing: what happened when, how long something has been left, a retry schedule | `timeline` | `events`: 2 to 8 of `{ "when", "text", "status" }`, oldest first. `when` is short: `Oct 21`, `2026-10-21`, `14:02` or `5 s`. When every `when` is in one of these forms, the timeline is drawn to scale and long gaps are labelled ("8 days"). |
| A few lines of real code, or what was removed or added | `code` | `ref`: `file:line`. `lines`: 1 to 14 of `{ "n", "text", "mark" }`. `n` is the line number (leave it out for removed lines). `mark` is `add`, `del` or `bad`. |

`status` is `ok`, `bad`, `warn` or `unknown`, optional except in `places`. Each one is drawn with its own icon. Only `bad` and `warn` get colour; the rest stay grey or ink, so give `bad` only to what is actually wrong. Text in exhibits supports `` `code` `` and `**bold**`. Every entry is a short phrase of 10 words or fewer; numbers and names, not sentences. In a `flow`, `ref` is shown as the file name and line only.

```json
"exhibit": {
  "type": "compare",
  "caption": "Two of the agent's claims don't hold today.",
  "left": "Agent said", "right": "Project now",
  "rows": [
    { "left": "All 80 clips passed the listen-back check", "right": "The check only compares word counts", "status": "bad" },
    { "left": "The dev server is stopped", "right": "PID 4121 still listens on :5173", "status": "bad" }
  ]
}
```

A `bars` example, for a wait the user would sit through:

```json
"exhibit": {
  "type": "bars", "unit": "s",
  "caption": "Nothing times out, so a stall is silence the learner sits through.",
  "rows": [
    { "label": "Usual wait for a reply", "value": 2.45 },
    { "label": "Worst stall seen", "value": 22, "display": "22 s or more", "status": "bad" }
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

`render` warns, but still writes the page, when an exhibit has no caption or an entry over 10 words, when a `body` is over 40 words, `summary.text` is over 60 words, a `call`, `decided` or urgent item has no exhibit, fewer than half the items have one, or the page shows more than 450 words before the collapsed details and the question. Two CJK characters count as one word. Fix the warnings and render again.

## Text formatting

Text fields support `` `code` ``, `**bold**`, paragraphs separated by a blank line, and lists made of lines starting with `- `. Nothing else is interpreted, and HTML is shown as plain text.
