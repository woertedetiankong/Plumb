---
name: map
description: Show the user's understanding map of this project, a treemap of its areas sized by code and colored by whether they understand each one as deeply as its stakes need, built from their answers to Plumb briefing questions. The first time, propose the areas and how deeply each needs understanding, and let the user confirm them. Use when the user asks for their map, what they understand, where their gaps are, or runs /plumb:map.
argument-hint: "[redo: propose the areas again]"
allowed-tools:
  - Bash(python3 ${CLAUDE_SKILL_DIR}/../brief/scripts/plumb.py *)
  - Read
  - Grep
  - Glob
  - AskUserQuestion
---

# Plumb map

The map shows the user which parts of their project they understand well enough for what those parts can break. Each area has a **need**: how deeply the user must understand it. Their answers to briefing questions show what they **have**. You set up the areas once; after that, the map updates itself from the briefings.

`${CLAUDE_SKILL_DIR}` below is this skill's folder, the one that contains this file. The script lives in the brief skill next to it.

## Ground rules

- **Read only.** Don't edit, commit, install or run anything in the project. Plumb writes only under `~/.plumb`.
- **Write in the language the user writes to you in.** Area names stay as paths.

## Steps

1. **Look at what's saved.**
   `python3 ${CLAUDE_SKILL_DIR}/../brief/scripts/plumb.py areas`
   It prints `saved` (the areas, or `null`) and `outline`: every folder up to two levels deep, with its files, lines and agent edits in the last 30 days. If areas are saved and the user didn't ask to redo them (`$ARGUMENTS`), go to step 4.

2. **Propose the areas.** Read the outline, the README and the main entry points until you know what each part does. Then propose 6 to 15 areas:
   - An area is a part the user would name when talking about the product: `payments/refunds`, `auth`, `db/migrations`, `web/ui`. Split a folder when its parts have different stakes. Merge small folders that do one job.
   - `paths`: the folders or files it covers, relative to the project. A file belongs to the area with the longest matching path. Together the areas should cover nearly all the code. Leave out generated code, vendored code and lockfiles.
   - `need`, from the stakes, not from the size:
     - `3` every line: it moves money, decides who can do what, changes or deletes data that can't be restored, or runs in production with no way back.
     - `2` shape: the user must know how its parts fit and where its main paths go, because other areas depend on it or its failures are subtle.
     - `1` contract: what goes in and what comes out is enough, because tests or its narrow job pin it down.
     - `0` nothing: low stakes, and tests or screenshots cover it, so it's fine as a black box.
   - `why`: one clause that finishes "needs every line because …": "it moves money", "outside systems call it".
   - `id`: a short lowercase name, such as `refunds`.

3. **Let the user confirm them.** Show the areas in chat as a table: name, paths, need, why. Then ask once, with AskUserQuestion if you have it (options: "Use these areas", "Change something"; the free-text answer lets them say what). Otherwise ask in plain text and wait. Apply their changes, then save:
   `python3 ${CLAUDE_SKILL_DIR}/../brief/scripts/plumb.py areas --set - <<'EOF'`
   `{"areas": [{"id": "refunds", "name": "payments/refunds", "paths": ["payments/refunds"], "need": 3, "why": "it moves money"}, ...]}`
   `EOF`
   If it lists errors, fix them and save again. If it says many lines aren't in any area, tell the user, and offer to add an area for them.

   This is the only question you ask.

4. **Open the map.**
   `python3 ${CLAUDE_SKILL_DIR}/../brief/scripts/plumb.py open map`
   This starts Plumb's own page server on 127.0.0.1 (it stops after 30 idle minutes) and opens the map in the browser. On the page, the user can say how well they know an area and change how deeply it needs understanding; both are saved as they click. If the server can't start, `open` opens the page as a plain file and says so; pass that on.

5. **Reply in chat in 2 to 4 lines.** Give the address `open` printed. Name the biggest gap, or the high-stakes areas nobody has checked yet. Say that each `/plumb:brief` adds a question, and a right answer moves its area forward. Don't paste the map.
