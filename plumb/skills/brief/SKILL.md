---
name: brief
description: Brief the user on what an AI coding agent (Claude Code or Codex) did in this project, checked against the project as it is now. The briefing covers decisions the agent made without asking, what nobody verified, and one explain-it-back question, shown as a local HTML page. Use when the user asks for a briefing, asks what an agent did or changed, or wants to catch up on agent work.
argument-hint: "[session id, or words from its topic] (no argument: choose from recent sessions)"
allowed-tools:
  - Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/plumb.py *)
  - Read
  - Grep
  - Glob
  - AskUserQuestion
---

# Plumb briefing

The user lets agents write code they don't read line by line. Tell them what they need to know about one agent session so they stay in charge of their project. **Check the agent's work; don't just retell it.** In tests, the findings users valued most came from comparing the agent's claims with the project as it is now: a server still running days later, a backup that was gone, a check weaker than its report said, a copy of a file the change never reached.

`${CLAUDE_SKILL_DIR}` below is this skill's folder, the one that contains this file.

## Ground rules

- **Read only.** Don't edit, commit, stash, install, stop processes, or run anything that deploys, sends messages, costs money, or takes more than about 2 minutes unless the user agrees first. The only files you write are the briefing JSON (in a temp folder outside the project) and what `render` writes under `~/.plumb`. The only process Plumb leaves running is its own page server, which `open` starts on 127.0.0.1 and which stops after 30 idle minutes.
- **Never print a secret.** Logs hold whatever the user pasted and whatever the agent ran. `plumb.py` hides common key formats, but if you still see something that looks like a key, password or token, don't repeat it; name it instead ("the MiniMax key"). To check whether a key leaked, compare inside a script and print only counts.
- **State as fact only what you checked.** Anything you couldn't check goes in a `unchecked` item.
- **Write in the language the user writes to you in.**

## Steps

1. **Let the user choose the session.** The user decides which sessions get a briefing. Plumb never briefs the session it is running in: leave out the excluded id and any row marked `live`.
   `python3 ${CLAUDE_SKILL_DIR}/scripts/plumb.py sessions --exclude ${CLAUDE_SESSION_ID} --json`
   - **They named one** (`$ARGUMENTS`). If it looks like a session id (6 or more letters and digits from an id), use that session. Otherwise treat it as words from the topic and run `sessions --match "<their words>" --json`. With one match, use it. With several, let them choose among the matches as below. With none, say so and offer the recent sessions instead.
   - **They didn't name one.** Offer the 4 newest sessions that changed something (`changes` above 0), newest first. Use each row's `label` as the option's name. Put its `when`, its length, what it changed (edits and files) and, if set, "briefed <date>" in the description. Mark the newest one without a briefing as recommended. If you have a tool for asking the user to choose (AskUserQuestion in Claude Code), use it; its free-text answer lets them type an id or topic words instead. Otherwise print a numbered list and wait for their reply. Mention any talk-only sessions you left out, in one line.
   - **Only one candidate:** say which session you're briefing and go ahead. **None:** say there's nothing to brief yet and stop.
   - A session that already has a briefing can be briefed again; the new page replaces the old one.

   This is the only question you ask during the whole briefing.

2. **Read the digest.**
   `python3 ${CLAUDE_SKILL_DIR}/scripts/plumb.py digest <id>`
   It lists the files edited and the commands worth checking, then a timeline that keeps the agent's reports whole. Agents also change files through shell commands, so "Files edited" can be incomplete; `state` (step 4) shows what actually changed. When you need something the digest cut, Read the log around that timestamp.

3. **List every claim and action for yourself.** Note what the agent says it changed, tested, measured, fixed, left running, committed, deferred, or asked the user to do. Note where what it did differs from what the user asked: more, less, or its own interpretation.

4. **Check them against the project now.**
   `python3 ${CLAUDE_SKILL_DIR}/scripts/plumb.py state --since "<session start>"`
   Then check the claims that matter most:
   - Read the code behind each mechanism the session built or changed. Note `file:line` for anything you will cite.
   - Re-run cheap offline tests the agent said pass. Read the test script first, and skip anything that calls paid APIs or the network.
   - Check whether what it left running is still running, and whether what it said would happen next has happened.
   - Check later commits and sessions. Don't report something that has since been fixed.
   - Look for copies, configs and other places the change should have reached but didn't.
   - Check what each verification really shows. Was "passed" real use or a synthetic test? Does a check test what its name says?

5. **Choose the items.** Every item must pass one bar: after reading it, would the user decide differently or understand their code differently? Prefer what you found by checking over what the agent already reported.
   - `call`: needs the user's decision. Give 2 to 4 options, recommended one first. When an option is something their agent can do, add a `prompt`: a ready-to-paste instruction.
   - `decided`: a choice the agent made without asking that the user might not have made, such as reading an ambiguous instruction its own way, picking a default, adding scope, or departing from its own plan.
   - `fyi`: true and useful, but no decision needed. Include one item that says what checks out.
   - `unchecked`: what nobody verified, including what you couldn't check.
   - `outside`: something important you found while checking that this session didn't cause.

   Mark at most one item `urgent`. Keep 3 to 8 items and cut the rest.

   **Show each item, then say only what the picture can't.** Users found text-only briefings hard to read. For each item, choose its `exhibit` first, from what the finding is (the table in [reference.md](reference.md#exhibits)): `compare` for said-vs-true or asked-vs-did, `flow` for a path that goes wrong, `places` for copies a change should reach, `tally` for counts, `timeline` for timing, `code` for the lines that matter. Every `call`, `decided` and urgent item gets one. Then write a `body` of 1 or 2 sentences (40 words at most) for what the picture doesn't show, usually why it matters. Put longer evidence in `detail`, which the page shows collapsed. Fill exhibits only with what you checked: real line numbers, real counts, real paths.

6. **Write one explain-it-back question.** Ask about the mechanism with the highest stakes that the user is least likely to understand. Usually that's behavior a real user, caller or customer will run into.
   - It must be answerable by understanding the code, not by remembering the briefing. Don't give the answer away in an item.
   - Give 4 choices with exactly one right. Each wrong choice should be a real misconception, with a `note` saying why it's wrong.
   - `area` is the file the question is about, as a path relative to the project. It decides which area of the user's map a right answer counts for.
   - `depth` is what a right answer shows: `1` the contract (what goes in and comes out), `2` the shape (how the parts connect, the path a request takes), `3` every line (what specific lines do in an edge case). Most questions are `2`.
   - `explanation` says what actually happens. `path` walks through it step by step with `file:line` refs and marks the steps where it goes wrong as `bad`. `why` links it to an item.
   - Vary which letter is right.
   - If nothing in the session deserves a question (docs-only work, say), set `question` to `null`.

7. **Write, render and open the page.** Write the briefing JSON to a temp file outside the project (the format is in [reference.md](reference.md)), then run:
   `python3 ${CLAUDE_SKILL_DIR}/scripts/plumb.py render <file>`
   If it lists errors, fix the JSON and run it again. If it lists warnings about length or missing exhibits, fix those too and render again. If it says the page went to a temporary folder, pass that note on to the user. If it can't save the page at all (a read-only sandbox), give the briefing in chat instead: the items as a short list, then the question with its choices, and the answer only after the user replies.

   Then open it:
   `python3 ${CLAUDE_SKILL_DIR}/scripts/plumb.py open <briefing id>`
   It serves the page from Plumb's local server, so the user's picks and answer are saved and their map (`/plumb:map`) counts them. If the server can't start, it opens the plain file and says so; pass that on.

8. **Reply in chat in 3 to 5 lines.** Name the session, give the most urgent item in one sentence, give the address `open` printed, and say the question is on the page. If the user has no map yet, say in one line that `/plumb:map` sets one up. Don't paste the briefing. Offer to explain any item or act on a call, and act only if they ask.

## Writing

- Use plain words, concrete numbers with units, and absolute dates.
- Titles state the finding: "Nobody has talked to the new provider yet", not "Testing status".
- Bodies are 1 or 2 sentences. The title states the finding and the exhibit shows the evidence, so the body only adds why it matters or what's missing from the picture.
- Exhibit entries are short phrases, not sentences: "PID 4121 still listens on :5173", not "The dev server that the agent said it stopped is in fact still running".
- Put paths and commands in backticks. Text fields support `code`, **bold**, paragraphs separated by a blank line, and lists made of lines starting with "- ".
