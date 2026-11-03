/* Plumb prototype: shared sample data, saved state and helpers.
   A plain script (no modules) so the pages also work when opened straight from disk. */
(function () {
  "use strict";

  const STORE_KEY = "plumb-prototype-v1";

  function load() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE_KEY) || "{}");
      return { picks: saved.picks || {}, answer: saved.answer ?? null };
    } catch (e) {
      return { picks: {}, answer: null };
    }
  }

  function save(state) {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(state));
    } catch (e) {
      // Storage can be blocked (private windows, some browsers on file://).
      // The page still works; choices just aren't remembered between pages.
    }
  }

  function reset() {
    try {
      localStorage.removeItem(STORE_KEY);
    } catch (e) {
      // See save().
    }
  }

  // Depths of understanding, shallowest first. Index + 1 is the depth number.
  const DEPTHS = ["Contract", "Shape", "Every line"];
  const NEED_PHRASE = ["nothing", "the contract", "the shape", "every line"];
  const HAVE_PHRASE = ["nothing yet", "the contract", "the shape", "every line"];

  const STATUS = {
    solid: { label: "Solid", verdict: "You understand this as deeply as it needs." },
    thin: { label: "Thin", verdict: "You know it, but one level less deeply than it needs." },
    gap: { label: "Gap", verdict: "High stakes, and you don't understand it yet." },
    ok: { label: "Covered", verdict: "Low stakes. Tests cover it, so it's fine as a black box." }
  };

  // Sample codebase. need/you: 0 = none, 1 = contract, 2 = shape, 3 = every line.
  // col/row place each area on a 12-column, 6-row treemap.
  // briefing: true means the refund briefing covers this area.
  const MODULES = [
    { id: "refunds", path: "payments/refunds", col: "1 / span 4", row: "1 / span 3", need: 3, you: 1, briefing: true, why: "it moves money.", since: "3 sessions last night · 14 files", agent: "94%", tests: "31 passing", last: "Oct 21" },
    { id: "checkout", path: "payments/checkout", col: "5 / span 4", row: "1 / span 2", need: 3, you: 3, why: "it moves money.", since: "No changes", agent: "71%", tests: "58 passing", last: "Oct 30" },
    { id: "orders", path: "orders", col: "9 / span 4", row: "1 / span 3", need: 2, you: 2, why: "most other areas depend on it.", since: "1 session · 2 files", agent: "66%", tests: "44 passing", last: "Nov 1" },
    { id: "search", path: "search", col: "5 / span 2", row: "3 / span 1", need: 1, you: 1, why: "it only reads data, and tests pin down what it returns.", since: "No changes", agent: "88%", tests: "19 passing", last: "Oct 12" },
    { id: "notifications", path: "notifications", col: "7 / span 2", row: "3 / span 1", need: 1, you: 2, why: "what it sends customers matters more than how.", since: "No changes", agent: "79%", tests: "12 passing", last: "Oct 18" },
    { id: "sessions", path: "auth/sessions", col: "1 / span 3", row: "4 / span 2", need: 3, you: 2, why: "it decides who is logged in.", since: "1 session · 3 files", agent: "83%", tests: "27 passing", last: "Oct 26" },
    { id: "migrations", path: "db/migrations", col: "4 / span 2", row: "4 / span 2", need: 3, you: 0, briefing: true, why: "it changes production data and is hard to undo.", since: "1 session last night · 1 file", agent: "100%", tests: "None", last: "Never" },
    { id: "webhooks", path: "webhooks", col: "6 / span 2", row: "4 / span 2", need: 3, you: 2, briefing: true, why: "outside systems call it, and it can issue refunds.", since: "1 session last night · 2 files", agent: "90%", tests: "16 passing", last: "Oct 21" },
    { id: "inventory", path: "inventory", col: "8 / span 3", row: "4 / span 2", need: 2, you: 1, why: "wrong counts mean selling stock you don't have.", since: "No changes", agent: "75%", tests: "22 passing", last: "Oct 3" },
    { id: "api", path: "api/routes", col: "11 / span 2", row: "4 / span 2", need: 2, you: 2, why: "it is the list of everything the app exposes.", since: "1 session · 4 files", agent: "70%", tests: "35 passing", last: "Nov 1" },
    { id: "ui", path: "web/ui", col: "1 / span 8", row: "6 / span 1", need: 0, you: 0, why: "", since: "2 sessions last night · 18 files", agent: "97%", tests: "140 passing · screenshots match", last: "Not needed" },
    { id: "scripts", path: "scripts/admin", col: "9 / span 2", row: "6 / span 1", need: 0, you: 0, why: "", since: "No changes", agent: "100%", tests: "Smoke test passing", last: "Not needed" },
    { id: "analytics", path: "analytics", col: "11 / span 2", row: "6 / span 1", need: 0, you: 0, why: "", since: "No changes", agent: "92%", tests: "9 passing", last: "Not needed" }
  ];

  // Which area each briefing decision belongs to.
  const DECISION_AREA = { d1: "webhooks", d2: "refunds", d3: "migrations" };
  const RIGHT_ANSWER = "B";

  function statusOf(m) {
    if (m.need === 0) return "ok";
    if (m.you >= m.need) return "solid";
    return m.need - m.you >= 2 ? "gap" : "thin";
  }

  // The sample data with the visitor's saved choices applied on top.
  function getModules(state) {
    const understoodRefunds = state.answer === RIGHT_ANSWER;
    return MODULES.map((m) => {
      const mod = { ...m };
      if (m.id === "refunds" && understoodRefunds) {
        mod.you = 2;
        mod.since = "No changes since";
        mod.last = "Today";
      }
      const decision = Object.keys(DECISION_AREA).find((d) => DECISION_AREA[d] === m.id);
      if (!decision) mod.dec = "None";
      else if (state.picks[decision]) mod.dec = "Decided by you";
      else mod.dec = m.id === "webhooks" ? "1 waiting · needs your call" : "1 waiting";
      mod.status = statusOf(mod);
      return mod;
    });
  }

  function openDecisions(state) {
    return Object.keys(DECISION_AREA).filter((d) => !state.picks[d]).length;
  }

  function barsHTML(you, need) {
    return [0, 1, 2]
      .map((i) => `<span class="bar ${i < you ? "have" : i < need ? "missing" : "extra"}"></span>`)
      .join("");
  }

  const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  function esc(value) {
    return String(value).replace(/[&<>"']/g, (c) => ESCAPES[c]);
  }

  function icon(paths, size) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${paths}</svg>`;
  }

  const ICON = {
    plumb: icon('<path d="M12 1.5V4"/><path d="M7 9a5 5 0 0 1 10 0c0 3-2.5 7-5 12.5C9.5 16 7 12 7 9z"/>', 22),
    chevron: icon('<path d="m6 9 6 6 6-6"/>', 14),
    user: icon('<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/>', 18),
    arrow: icon('<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>', 16),
    check: icon('<path d="M20 6 9 17l-5-5"/>', 16),
    checkLg: icon('<path d="M20 6 9 17l-5-5"/>', 18),
    alert: icon('<path d="M12 3 2 21h20L12 3z"/><path d="M12 10v5"/><path d="M12 18h.01"/>', 18),
    circle: icon('<circle cx="12" cy="12" r="8"/>', 18)
  };

  function renderHeader() {
    const el = document.getElementById("site-header");
    if (!el) return;
    const page = document.body.dataset.page;
    const open = openDecisions(load());
    const current = (name) => (page === name ? ' aria-current="page"' : "");
    const badge = open ? `<span class="badge">${open}<span class="sr-only"> open</span></span>` : "";
    el.innerHTML = `
      <div class="header-inner">
        <a class="brand" href="index.html">${ICON.plumb}<span>Plumb</span></a>
        <button class="repo-btn" type="button" data-todo="Switching repositories" aria-label="Switch repository. Current: shopfront">shopfront${ICON.chevron}</button>
        <nav class="nav" aria-label="Main">
          <a href="index.html"${current("map")}>Map</a>
          <a href="briefing.html"${current("briefing")}>Briefings${badge}</a>
          <a href="recap.html"${current("recap")}>Growth</a>
        </nav>
        <div class="header-right">
          <span class="watching"><span class="dot" aria-hidden="true"></span>Watching Claude Code and Codex</span>
          <button class="avatar" type="button" data-todo="Account settings" aria-label="Account">${ICON.user}</button>
        </div>
      </div>`;
  }

  function renderFooter() {
    const el = document.getElementById("site-footer");
    if (!el) return;
    el.innerHTML = '<span>Prototype with sample data.</span><button class="link-btn" type="button" data-reset>Reset demo</button>';
  }

  let toastEl = null;
  let toastTimer = 0;
  function toast(message) {
    toastEl.textContent = message;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("show"), 2600);
  }

  function init() {
    toastEl = document.createElement("div");
    toastEl.className = "toast";
    toastEl.setAttribute("role", "status");
    document.body.appendChild(toastEl);

    renderHeader();
    renderFooter();

    // Buttons for features this prototype doesn't have say so instead of doing nothing.
    document.addEventListener("click", (e) => {
      const todo = e.target.closest("[data-todo]");
      if (todo) {
        toast(`${todo.dataset.todo} isn't built in this prototype yet.`);
        return;
      }
      if (e.target.closest("[data-reset]")) {
        reset();
        location.reload();
      }
    });
  }

  window.Plumb = {
    load, save, reset,
    DEPTHS, NEED_PHRASE, HAVE_PHRASE, STATUS, MODULES, DECISION_AREA, RIGHT_ANSWER,
    statusOf, getModules, openDecisions, barsHTML, esc, ICON,
    renderHeader, toast
  };

  init();
})();
