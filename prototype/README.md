# Plumb prototype

A clickable prototype of Plumb: a tool that shows how well you understand the code your AI agents write. Everything runs on sample data for a made-up codebase called `shopfront`.

## Open it

Double-click `index.html`. There's no build step and nothing to install.

If your choices don't carry from one page to the next (some browsers block storage for files opened from disk), serve the folder instead:

```sh
python3 -m http.server 8000 --directory prototype
```

Then open http://localhost:8000.

## Pages

| File | Screen |
|---|---|
| `index.html` | The understanding map. Select a tile to see its details. |
| `briefing.html` | The briefing on last night's agent work, with three decisions to make. |
| `check.html` | One explain-it-back question. A right answer moves `payments/refunds` from Gap to Thin. |
| `recap.html` | The shareable monthly recap card. |

`common.js` holds the sample data and shared helpers, `styles.css` holds all styles, and each page has its own script.

Decisions and your answer are saved in the browser's `localStorage`, so the map updates after you answer correctly. Use **Reset demo** in the footer to start over. Buttons for features that aren't built yet show a short notice instead of doing nothing.
