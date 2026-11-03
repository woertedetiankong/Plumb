# Plumb

Know the code your agents write.

When Claude Code or Codex writes most of your code, it's easy to lose track of what changed, what the agent decided on its own, and what nobody actually checked. Plumb reads an agent session, checks the agent's claims against your project as it is now, and gives you a one-page briefing with the calls only you should make, plus one question to make sure you understand the part that matters.

## Install in Claude Code

```text
/plugin marketplace add woertedetiankong/Plumb
/plugin install plumb@plumb
```

Then, in any project, run `/plumb:brief` and pick a recent session. For Codex, and for how it works, see [plumb/README.md](plumb/README.md).

## What's here

| Folder | What it is |
|---|---|
| [`plumb/`](plumb/) | The Claude Code plugin: the `/plumb:brief` skill, its helper script, the briefing page and tests |
| [`prototype/`](prototype/) | A clickable prototype of where Plumb is headed, including the understanding map. Open `prototype/index.html`. |

Plumb is early. If you try it, I'd love to hear what it got right and what it missed.
