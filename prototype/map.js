/* Map page: the treemap, the summary numbers and the details panel. */
(function () {
  "use strict";

  const P = window.Plumb;
  const state = P.load();
  const modules = P.getModules(state);
  const $ = (id) => document.getElementById(id);
  let picked = "refunds";

  function renderBanner() {
    const open = P.openDecisions(state);
    const text = open
      ? `5 agent sessions changed 35 files. Most of it is low stakes. <em>${open} ${open === 1 ? "decision" : "decisions"} from last night's refund work ${open === 1 ? "needs" : "need"} your judgment.</em>`
      : "You've made every decision from last night's refund work.";
    const link = open ? "Start briefing · about 4 min" : "Review the briefing";
    $("banner").innerHTML = `
      <div class="grow">
        <p class="eyebrow">While you were away</p>
        <p class="banner-text">${text}</p>
      </div>
      <a class="btn btn-lg btn-on-dark" href="briefing.html">${link}${P.ICON.arrow}</a>`;
  }

  function renderStats() {
    const needYou = modules.filter((m) => m.status === "gap" || m.status === "thin").length;
    const gaps = modules.filter((m) => m.status === "gap").length;
    $("stat-need").textContent = `${needYou} of ${modules.length}`;
    $("stat-gaps").textContent = String(gaps);
    $("stat-gaps-label").textContent = gaps === 1 ? "gap in high-stakes code" : "gaps in high-stakes code";
  }

  function renderMap() {
    $("treemap").innerHTML = modules
      .map((m) => {
        const s = P.STATUS[m.status];
        const label = `${m.path}: ${s.label}. Needs ${P.NEED_PHRASE[m.need]}; you have ${P.HAVE_PHRASE[m.you]}.`;
        return `
          <button class="tile s-${m.status}" type="button" data-id="${m.id}" aria-pressed="${m.id === picked}" aria-label="${P.esc(label)}" style="grid-column: ${m.col}; grid-row: ${m.row};">
            <span class="tile-name">${P.esc(m.path)}</span>
            <span class="tile-foot">
              <span class="tile-label">${s.label}</span>
              <span class="bars" aria-hidden="true">${P.barsHTML(m.you, m.need)}</span>
            </span>
          </button>`;
      })
      .join("");
  }

  function depthStepsHTML(m) {
    return [1, 2, 3]
      .map((k) => {
        const name = P.DEPTHS[k - 1];
        const needed = k === m.need;
        let cls;
        let note;
        if (k <= m.you) {
          cls = "have";
          note = [k === m.you ? "you" : "", needed ? "needed" : ""].filter(Boolean).join(" · ");
        } else if (k <= m.need) {
          cls = "missing";
          note = needed ? "needed" : "missing";
        } else {
          cls = "extra";
          note = "not needed";
        }
        note = note.charAt(0).toUpperCase() + note.slice(1);
        return `<div class="depth-step ${cls}"><b>${name}</b><span>${note}</span></div>`;
      })
      .join("");
  }

  function actionsHTML(m) {
    const changeDepth = '<button class="btn btn-block" type="button" data-todo="Changing how deep an area needs to be">Change how deep this needs to be</button>';
    if (m.status === "gap" || m.status === "thin") {
      const brief = m.briefing
        ? `<a class="btn btn-lg btn-primary btn-block" href="briefing.html">Brief me · about ${m.id === "refunds" ? 4 : 3} min${P.ICON.arrow}</a>`
        : `<button class="btn btn-lg btn-primary btn-block" type="button" data-todo="A briefing for ${P.esc(m.path)}">Brief me · about 3 min${P.ICON.arrow}</button>`;
      return brief + changeDepth;
    }
    if (m.status === "solid") {
      return '<p class="note note-solid">You\'re current. Nothing here needs you.</p>' +
        '<button class="btn btn-block" type="button" data-todo="Refreshing your understanding">Refresh my understanding</button>';
    }
    return '<p class="note note-ok">Skip it unless something breaks. You\'ll get a briefing if its stakes change.</p>' + changeDepth;
  }

  function renderPanel() {
    const m = modules.find((x) => x.id === picked);
    const s = P.STATUS[m.status];
    const needLine = m.need === 0
      ? "Tests and screenshots cover it, so you can treat it as a black box."
      : `Needs ${P.NEED_PHRASE[m.need]} because ${m.why}`;
    const facts = [
      ["Changed since you last understood it", m.since],
      ["Written by agents", m.agent],
      ["Tests", m.tests],
      ["Last understood", m.last],
      ["Decisions made without you", m.dec]
    ];
    $("panel").innerHTML = `
      <div>
        <span class="chip s-${m.status}">${s.label}</span>
        <h2 class="panel-path">${P.esc(m.path)}</h2>
        <p class="muted">${s.verdict}</p>
      </div>
      <div>
        <p class="depth-title">Depth</p>
        <div class="depth-grid">${depthStepsHTML(m)}</div>
        <p class="need-line">${P.esc(needLine)}</p>
      </div>
      <dl class="facts">
        ${facts.map(([k, v]) => `<div><dt>${k}</dt><dd>${P.esc(v)}</dd></div>`).join("")}
      </dl>
      <div class="actions">${actionsHTML(m)}</div>`;
  }

  $("treemap").addEventListener("click", (e) => {
    const tile = e.target.closest(".tile");
    if (!tile) return;
    picked = tile.dataset.id;
    // Update the pressed state in place so keyboard focus stays on the tile.
    document.querySelectorAll("#treemap .tile").forEach((t) => {
      t.setAttribute("aria-pressed", String(t.dataset.id === picked));
    });
    renderPanel();
  });

  renderBanner();
  renderStats();
  renderMap();
  renderPanel();
})();
