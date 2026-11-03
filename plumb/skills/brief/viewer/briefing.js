/* Plumb briefing page: renders the embedded briefing JSON. Picks and the answer are kept in localStorage. */
(function () {
  "use strict";

  const B = JSON.parse(document.getElementById("briefing-data").textContent);
  const KEY = "plumb:briefing:" + B.id;
  const SECTIONS = [
    ["call", "Needs your call"],
    ["decided", "Decided without asking"],
    ["fyi", "Worth knowing"],
    ["unchecked", "Not checked"],
    ["outside", "Outside this session"]
  ];
  const AGENT = { "claude-code": "Claude Code", codex: "Codex" };
  const $ = (id) => document.getElementById(id);

  function load() {
    try {
      const s = JSON.parse(localStorage.getItem(KEY) || "{}");
      return { picks: s.picks || {}, answer: s.answer ?? null };
    } catch (e) {
      return { picks: {}, answer: null };
    }
  }
  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* storage blocked: still works for this visit */ }
  }
  const state = load();

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  // Escape first, then allow `code` and **bold** only.
  function inline(s) {
    return esc(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  }
  // Paragraphs split on blank lines; lines starting with "- " become a list.
  function md(text) {
    return String(text || "").split(/\n\s*\n/).map((block) => {
      const lines = block.split("\n");
      if (lines.every((l) => /^\s*[-*] /.test(l))) {
        return "<ul>" + lines.map((l) => "<li>" + inline(l.replace(/^\s*[-*] /, "")) + "</li>").join("") + "</ul>";
      }
      return "<p>" + lines.map(inline).join("<br>") + "</p>";
    }).join("");
  }

  let toastTimer;
  function toast(msg) {
    const el = $("toast");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 3200);
  }

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
      ta.remove();
      return ok;
    }
  }

  function itemHTML(it, i) {
    const pick = state.picks[i];
    const opts = (it.options || []).map((o, j) => `
      <button type="button" class="opt" data-item="${i}" data-opt="${j}" aria-pressed="${pick === j}">
        ${inline(o.label)}${o.recommended ? '<span class="rec">Recommended</span>' : ""}
      </button>`).join("");
    const chosen = pick != null && it.options && it.options[pick];
    return `
      <article class="item ${esc(it.kind)}${it.urgent ? " urgent" : ""}" id="item-${i}">
        ${it.urgent ? '<span class="tag">Most urgent</span>' : ""}
        <h3>${inline(it.title)}</h3>
        <div class="body">${md(it.body)}</div>
        ${it.refs && it.refs.length ? `<div class="refs">${it.refs.map((r) => `<code>${esc(r)}</code>`).join("")}</div>` : ""}
        ${opts ? `<div class="options" role="group" aria-label="Your call">${opts}</div>
        <p class="picked" id="picked-${i}">${chosen ? pickedText(chosen) : ""}</p>` : ""}
      </article>`;
  }

  function pickedText(o) {
    return "Your call: " + esc(o.label) + (o.prompt ? ". The prompt for your agent is on your clipboard." : ".");
  }

  function questionHTML(q) {
    const answered = state.answer !== null;
    const answers = q.choices.map((c) => {
      let cls = "", tag = "";
      if (answered && c.key === q.answer) { cls = " is-right"; tag = c.key === state.answer ? "Your answer · right" : "Right answer"; }
      else if (answered && c.key === state.answer) { cls = " is-wrong"; tag = "Your answer"; }
      return `
        <button type="button" class="answer${cls}" data-key="${esc(c.key)}" aria-pressed="${c.key === state.answer}"${answered ? " disabled" : ""}>
          <span class="answer-key">${esc(c.key)}</span>
          <span class="answer-text">${inline(c.text)}</span>
          ${tag ? `<span class="answer-tag">${tag}</span>` : ""}
        </button>`;
    }).join("");
    let feedback = "";
    if (answered) {
      const right = state.answer === q.answer;
      const mine = q.choices.find((c) => c.key === state.answer);
      feedback = `
        <div class="feedback">
          <h3 class="fb-title" id="fb-title" tabindex="-1">${right ? "Right." : "Not quite: the answer is " + esc(q.answer) + "."}</h3>
          ${!right && mine && mine.note ? `<div class="body">${md(mine.note)}</div>` : ""}
          <div class="body">${md(q.explanation)}</div>
          ${q.path && q.path.length ? `<ol class="path" aria-label="What happens, step by step">${q.path.map((s) => `
            <li class="${s.bad ? "bad" : ""}"><span>${inline(s.text)}</span>${s.ref ? `<span class="ref">${esc(s.ref)}</span>` : ""}</li>`).join("")}
          </ol>` : ""}
          ${q.why ? `<div class="why body">${md(q.why)}</div>` : ""}
        </div>`;
    }
    return `
      <section class="question" id="question" aria-labelledby="q-title">
        <p class="eyebrow">One question${q.area ? " · " + esc(q.area) : ""}</p>
        <h2 id="q-title">${inline(q.text)}</h2>
        <div class="answers">${answers}</div>
        ${feedback}
      </section>`;
  }

  function render() {
    const s = B.session;
    $("meta").textContent = [B.project.name, (AGENT[s.agent] || s.agent) + " session", s.started + " → " + s.ended,
      "briefed " + B.created].join(" · ");
    const items = B.items.map((it, i) => ({ it, i }));
    const sections = SECTIONS.map(([kind, title]) => {
      const list = items.filter((x) => x.it.kind === kind).sort((a, b) => (b.it.urgent ? 1 : 0) - (a.it.urgent ? 1 : 0));
      if (!list.length) return "";
      return `
        <section class="section">
          <div class="section-head"><h2>${title}</h2><span class="count">${list.length}</span></div>
          ${list.map((x) => itemHTML(x.it, x.i)).join("")}
        </section>`;
    }).join("");
    const sum = B.summary;
    $("app").innerHTML = `
      <section class="hero">
        <p class="eyebrow">Briefing</p>
        <h1>${inline(s.title)}</h1>
        <div class="lead body">${md(sum.text)}</div>
        ${sum.did && sum.did.length ? `<ul class="did">${sum.did.map((d) => `<li>${inline(d)}</li>`).join("")}</ul>` : ""}
        ${sum.state ? `<p class="state">${inline(sum.state)}</p>` : ""}
        ${B.question ? '<a class="jump" href="#question">Answer the question ↓</a>' : ""}
      </section>
      ${sections}
      ${B.question ? questionHTML(B.question) : ""}`;
  }

  document.addEventListener("click", async (e) => {
    const opt = e.target.closest(".opt");
    if (opt) {
      const i = Number(opt.dataset.item), j = Number(opt.dataset.opt);
      const o = B.items[i].options[j];
      state.picks[i] = j;
      save();
      opt.parentElement.querySelectorAll(".opt").forEach((b) => b.setAttribute("aria-pressed", String(b === opt)));
      if (o.prompt) {
        const ok = await copy(o.prompt);
        toast(ok ? "Copied. Paste it into your agent to act on it." : "Couldn't copy. The prompt is: " + o.prompt);
      } else {
        toast("Noted.");
      }
      $("picked-" + i).innerHTML = pickedText(o);
      return;
    }
    const ans = e.target.closest(".answer");
    if (ans && !ans.disabled) {
      state.answer = ans.dataset.key;
      save();
      render();
      const t = $("fb-title");
      if (t) t.focus();
      return;
    }
    if (e.target.id === "reset") {
      state.picks = {};
      state.answer = null;
      try { localStorage.removeItem(KEY); } catch (err) { /* nothing stored */ }
      render();
      toast("Your answers are cleared.");
    }
  });

  render();
})();
