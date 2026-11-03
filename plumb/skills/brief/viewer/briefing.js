/* Plumb briefing page: renders the embedded briefing JSON. Picks and the answer are kept in localStorage. */
(function () {
  "use strict";

  const B = JSON.parse(document.getElementById("briefing-data").textContent);
  const KEY = "plumb:briefing:" + B.id;
  const SECTIONS = [
    { kind: "call", title: "Needs your call", sub: "Most urgent first. Picking an option copies a ready-to-paste prompt for your agent." },
    { kind: "decided", title: "Decided without asking", sub: "Choices the agent made on its own." },
    { kind: "fyi", title: "Worth knowing", sub: "" },
    { kind: "unchecked", title: "Not checked", sub: "Nobody has verified these yet." },
    { kind: "outside", title: "Outside this session", sub: "Found while checking, but this session didn't cause it." }
  ];
  const AGENT = { "claude-code": "Claude Code", codex: "Codex" };
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const $ = (id) => document.getElementById(id);

  function svg(paths, size) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${paths}</svg>`;
  }
  const ICON = {
    check: svg('<path d="M20 6 9 17l-5-5"/>', 16),
    arrow: svg('<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>', 16),
    info: svg('<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8h.01"/>', 16)
  };

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
  let questionOpen = false;

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

  // "2026-10-22 07:46" → Date in local time (or null).
  function when(s) {
    const m = /^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)/.exec(s || "");
    return m ? new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5]) : null;
  }
  const day = (d) => MONTHS[d.getMonth()] + " " + d.getDate();
  const clock = (s) => (s || "").slice(11, 16);
  function duration(a, b) {
    if (!a || !b) return "";
    const min = Math.max(0, Math.round((b - a) / 60000));
    return min < 60 ? min + " min" : Math.floor(min / 60) + " h " + (min % 60) + " min";
  }
  // Long paths read better as their last two parts; the full path stays in the tooltip.
  function shortPath(p) {
    const s = String(p || "");
    const parts = s.split("/");
    return parts.length > 2 ? "…/" + parts.slice(-2).join("/") : s;
  }

  let toastTimer;
  function toast(msg) {
    const el = $("toast");
    el.textContent = msg;
    el.hidden = false;
    requestAnimationFrame(() => el.classList.add("show"));
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      el.classList.remove("show");
      toastTimer = setTimeout(() => { el.hidden = true; }, 250);
    }, 3200);
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

  const withOptions = () => B.items.map((it, i) => i).filter((i) => B.items[i].options && B.items[i].options.length);
  const decidedCount = () => withOptions().filter((i) => state.picks[i] != null).length;

  function pickedText(o) {
    return ICON.check + "<span>Your call: " + inline(o.label) + (o.prompt ? ". The prompt for your agent is on your clipboard." : ".") + "</span>";
  }

  function refsHTML(it) {
    if (!it.refs || !it.refs.length) return "";
    return `<div><p class="label">Evidence</p><ul class="refs">${it.refs.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>`;
  }

  function decisionHTML(it, i) {
    const pick = state.picks[i];
    const opts = (it.options || []).map((o, j) => `
      <button type="button" class="btn opt" data-item="${i}" data-opt="${j}" aria-pressed="${pick === j}">
        <span>${inline(o.label)}</span>${o.recommended ? '<span class="rec">Recommended</span>' : ""}
      </button>`).join("");
    const chosen = pick != null && it.options && it.options[pick];
    let pill;
    if (it.urgent) pill = '<span class="stakes stakes-high tag">Most urgent</span>';
    else if (it.kind === "call") pill = '<span class="stakes stakes-mid">Needs your call</span>';
    else pill = '<span class="stakes stakes-low">Made without asking</span>';
    return `
      <article class="item decision ${esc(it.kind)}${it.urgent ? " urgent" : ""}" id="item-${i}" aria-labelledby="item-${i}-title">
        <div class="decision-meta">${pill}</div>
        <h3 id="item-${i}-title">${inline(it.title)}</h3>
        <div class="body">${md(it.body)}</div>
        ${refsHTML(it)}
        ${opts ? `<div class="options" role="group" aria-label="Your call">${opts}</div>
        <p class="picked" id="picked-${i}" aria-live="polite">${chosen ? pickedText(chosen) : ""}</p>` : ""}
      </article>`;
  }

  function groupItemHTML(it, i) {
    return `
      <article class="item ${esc(it.kind)}${it.urgent ? " urgent" : ""}" id="item-${i}">
        ${it.urgent ? '<span class="stakes stakes-high tag">Most urgent</span>' : ""}
        <h3>${inline(it.title)}</h3>
        <div class="body">${md(it.body)}</div>
        ${refsHTML(it)}
      </article>`;
  }

  function sectionHTML(sec) {
    const list = B.items.map((it, i) => ({ it, i }))
      .filter((x) => x.it.kind === sec.kind)
      .sort((a, b) => (b.it.urgent ? 1 : 0) - (a.it.urgent ? 1 : 0));
    if (!list.length) return "";
    const asCards = sec.kind === "call" || sec.kind === "decided";
    const inner = asCards
      ? list.map((x) => decisionHTML(x.it, x.i)).join("")
      : `<div class="card group${sec.kind === "unchecked" ? " group-quiet" : ""}">${list.map((x) => groupItemHTML(x.it, x.i)).join("")}</div>`;
    return `
      <section class="section" id="sec-${sec.kind}" aria-labelledby="sec-${sec.kind}-title">
        <div class="section-head">
          <h2 id="sec-${sec.kind}-title">${sec.title}</h2><span class="count">${list.length}</span>
          ${sec.sub ? `<p class="section-sub">${sec.sub}</p>` : ""}
        </div>
        ${inner}
      </section>`;
  }

  function railHTML() {
    const s = B.session, a = when(s.started), b = when(s.ended);
    const total = withOptions().length;
    const steps = [`<li><a href="#what" data-step="what"><span class="step-num">1</span><span class="step-label">What happened</span></a></li>`];
    if (total) {
      const first = B.items.some((it) => it.kind === "call") ? "call" : "decided";
      steps.push(`<li><a href="#sec-${first}" data-step="sec-${first}"><span class="step-num">${steps.length + 1}</span><span class="step-label">Your calls</span><span class="count" id="decided-count">${decidedCount()} of ${total}</span></a></li>`);
    }
    if (B.question) {
      steps.push(`<li><a href="#check" data-step="check" data-open-question><span class="step-num">${steps.length + 1}</span><span class="step-label">Check yourself</span></a></li>`);
    }
    const calls = B.items.filter((it) => it.kind === "call").length;
    const meta = [duration(a, b), a ? day(a) + ", " + clock(s.started) + "–" + clock(s.ended) : ""].filter(Boolean).join(" · ");
    return `
      <aside class="rail" aria-label="About this briefing">
        <div class="card rail-card">
          <p class="eyebrow">Briefing</p>
          <p class="rail-area">${esc(B.project.name)}</p>
          <p class="muted small">${esc(B.items.length)} findings${B.question ? " and 1 question" : ""}</p>
          <ol class="steps">${steps.join("")}</ol>
        </div>
        <div class="card rail-card">
          <p class="eyebrow">Built from 1 session</p>
          <ul class="sessions">
            <li>
              <p class="session-agent">${esc(AGENT[s.agent] || s.agent)}</p>
              <p class="session-title">${inline(s.title)}</p>
              <p class="session-meta"><span>${esc(meta)}</span>${calls ? `<span class="pill-warn">${calls} need${calls === 1 ? "s" : ""} your call</span>` : ""}</p>
            </li>
          </ul>
        </div>
      </aside>`;
  }

  function summaryHTML() {
    const s = B.session, sum = B.summary, a = when(s.started), b = when(s.ended), c = when(B.created);
    const line = [(AGENT[s.agent] || s.agent) + " session", a ? day(a) : s.started, duration(a, b), c ? "briefed " + day(c) : ""]
      .filter(Boolean).join(" · ");
    const did = sum.did && sum.did.length;
    return `
      <div id="what" class="section">
        <div>
          <p class="muted small">${esc(line)}</p>
          <h1 class="brief-title">${inline(s.title)}</h1>
        </div>
        <section class="card card-lg" aria-labelledby="para-title">
          <h2 id="para-title" class="eyebrow section-eyebrow">In one paragraph</h2>
          <div class="para">${md(sum.text)}</div>
        </section>
        ${did || sum.state ? `
        <section class="card card-lg" aria-labelledby="did-title">
          <h2 id="did-title" class="eyebrow section-eyebrow">What the agent did</h2>
          ${did ? `<ul class="did">${sum.did.map((d) => `<li>${ICON.check}<span>${inline(d)}</span></li>`).join("")}</ul>` : ""}
          ${sum.state ? `<p class="state">${ICON.info}<span><strong>Where it stands now.</strong> ${inline(sum.state)}</span></p>` : ""}
        </section>` : ""}
      </div>`;
  }

  function questionHTML(q) {
    const answered = state.answer !== null;
    if (!answered && !questionOpen) {
      return `
        <div class="cta-bar" id="check">
          <div class="grow">
            <p class="cta-title">${decidedCount() && decidedCount() === withOptions().length ? "All calls made. One last step." : "Done reading? Check your understanding."}</p>
            <p class="cta-sub">One question${q.area ? " about <code>" + esc(shortPath(q.area)) + "</code>" : ""}. Answer it from how the code works, not from this page.</p>
          </div>
          <button type="button" class="btn btn-lg btn-on-dark" id="open-question" data-open-question>Check my understanding${ICON.arrow}</button>
        </div>`;
    }
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
          ${!right && mine && mine.note ? `<div class="note-wrong body">${md(mine.note)}</div>` : ""}
          <div class="body">${md(q.explanation)}</div>
          ${q.path && q.path.length ? `<div><p class="label">What happens, step by step</p><ol class="path">${q.path.map((s) => `
            <li class="${s.bad ? "bad" : ""}"><span>${inline(s.text)}</span>${s.ref ? `<span class="ref" title="${esc(s.ref)}">${esc(shortPath(s.ref))}</span>` : ""}</li>`).join("")}
          </ol></div>` : ""}
          ${q.why ? `<div class="why body">${md(q.why)}</div>` : ""}
        </div>`;
    }
    return `
      <section class="card question-card question" id="check" aria-labelledby="q-title">
        <p class="eyebrow">Explain it back${q.area ? ` · <span title="${esc(q.area)}">${esc(shortPath(q.area))}</span>` : ""} · 1 question</p>
        <h2 id="q-title" class="question-text">${inline(q.text)}</h2>
        <div class="answers" role="group" aria-labelledby="q-title">${answers}</div>
        ${feedback}
      </section>`;
  }

  function renderQuestion() {
    const slot = $("question-slot");
    if (slot && B.question) slot.innerHTML = questionHTML(B.question);
  }

  function updateProgress() {
    const el = $("decided-count");
    if (el) el.textContent = decidedCount() + " of " + withOptions().length;
    if (state.answer === null && !questionOpen) renderQuestion();
    markSteps();
  }

  // Highlight the step for the part of the page being read: the last one whose start has scrolled past 40% of the window.
  let currentStep = "what";
  function markSteps(active) {
    if (active) currentStep = active;
    document.querySelectorAll(".steps a").forEach((a) => {
      const step = a.dataset.step;
      const current = step === currentStep;
      const done = step === "check" ? state.answer !== null
        : step.startsWith("sec-") ? withOptions().length > 0 && decidedCount() === withOptions().length : false;
      a.classList.toggle("current", current);
      a.classList.toggle("done", done && !current);
      if (current) a.setAttribute("aria-current", "step"); else a.removeAttribute("aria-current");
    });
  }
  function spySteps() {
    const ids = [...document.querySelectorAll(".steps a")].map((a) => a.dataset.step);
    const line = innerHeight * 0.4;
    const atBottom = innerHeight + scrollY >= document.documentElement.scrollHeight - 4;
    let active = ids[0];
    ids.forEach((id) => { const el = $(id); if (el && el.getBoundingClientRect().top <= line) active = id; });
    if (atBottom && $("check")) active = "check";
    markSteps(active);
  }
  let spyQueued = false;
  addEventListener("scroll", () => {
    if (spyQueued) return;
    spyQueued = true;
    requestAnimationFrame(() => { spyQueued = false; spySteps(); });
  }, { passive: true });
  addEventListener("resize", spySteps);

  function render() {
    const s = B.session;
    $("project").textContent = B.project.name;
    const c = when(B.created);
    $("meta").textContent = "Briefed " + (c ? day(c) + ", " + clock(B.created) : B.created) + " · " + (AGENT[s.agent] || s.agent);
    $("app").innerHTML = `
      ${railHTML()}
      <div class="main-col">
        ${summaryHTML()}
        ${SECTIONS.map(sectionHTML).join("")}
        <div id="question-slot"></div>
      </div>`;
    renderQuestion();
    spySteps();
  }

  function openQuestion(focus) {
    questionOpen = true;
    renderQuestion();
    const card = $("check");
    if (card) {
      // Focus first: moving focus during a smooth scroll stops the scroll.
      if (focus) { const first = card.querySelector(".answer"); if (first) first.focus({ preventScroll: true }); }
      card.scrollIntoView({ block: "start" });
    }
  }

  document.addEventListener("click", async (e) => {
    const opener = e.target.closest("[data-open-question]");
    if (opener) {
      e.preventDefault();
      openQuestion(opener.id === "open-question");
      return;
    }
    const opt = e.target.closest(".opt");
    if (opt) {
      const i = Number(opt.dataset.item), j = Number(opt.dataset.opt);
      const o = B.items[i].options[j];
      state.picks[i] = j;
      save();
      opt.parentElement.querySelectorAll(".opt").forEach((b) => b.setAttribute("aria-pressed", String(b === opt)));
      $("picked-" + i).innerHTML = pickedText(o);
      updateProgress();
      if (o.prompt) {
        const ok = await copy(o.prompt);
        toast(ok ? "Copied. Paste it into your agent to act on it." : "Couldn't copy. The prompt is: " + o.prompt);
      } else {
        toast("Noted.");
      }
      return;
    }
    const ans = e.target.closest(".answer");
    if (ans && !ans.disabled) {
      state.answer = ans.dataset.key;
      save();
      renderQuestion();
      markSteps();
      const t = $("fb-title");
      if (t) t.focus();
      return;
    }
    if (e.target.id === "reset") {
      state.picks = {};
      state.answer = null;
      questionOpen = false;
      try { localStorage.removeItem(KEY); } catch (err) { /* nothing stored */ }
      render();
      toast("Your answers are cleared.");
    }
  });

  render();
})();
