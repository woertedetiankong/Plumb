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
  // One mark per status, so colour is never the only signal.
  const MARK = {
    ok: { icon: svg('<path d="M20 6 9 17l-5-5"/>', 14), label: "OK" },
    bad: { icon: svg('<path d="M18 6 6 18"/><path d="m6 6 12 12"/>', 14), label: "Problem" },
    warn: { icon: svg('<path d="M12 8v5"/><path d="M12 16.5h.01"/>', 14), label: "Watch" },
    unknown: { icon: svg('<path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7"/><path d="M12 16.5h.01"/>', 14), label: "Not checked" }
  };
  const status = (s) => (MARK[s] ? s : "");
  function markHTML(s) {
    return MARK[s] ? `<span class="mark m-${s}" role="img" aria-label="${MARK[s].label}">${MARK[s].icon}</span>` : "";
  }

  // Served by `plumb.py open`: picks and the answer are saved to ~/.plumb, so the map can use them.
  // Opened as a plain file: they stay in this browser's storage.
  const SRV = (() => {
    const m = document.querySelector('meta[name="plumb-server"]');
    try { return m ? JSON.parse(m.content) : null; } catch (e) { return null; }
  })();
  const MAP = SRV ? SRV.map : document.body.dataset.map || "";

  function load() {
    const served = document.getElementById("plumb-state");
    if (SRV && served) {
      try {
        const s = JSON.parse(served.textContent);
        const picks = {};
        Object.keys(s.picks || {}).forEach((k) => { picks[k] = Number(s.picks[k]); });
        return { picks, answer: s.answer ?? null };
      } catch (e) { /* fall through to browser storage */ }
    }
    try {
      const s = JSON.parse(localStorage.getItem(KEY) || "{}");
      return { picks: s.picks || {}, answer: s.answer ?? null };
    } catch (e) {
      return { picks: {}, answer: null };
    }
  }
  function save(change) {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* storage blocked: still works for this visit */ }
    if (!SRV || !change) return;
    fetch("/api/record", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Plumb-Token": SRV.token },
      body: JSON.stringify({ store: SRV.store, briefing: B.id, change })
    }).then((r) => { if (!r.ok) throw new Error(r.status); })
      .catch(() => toast("Couldn't save to Plumb (its page server may have stopped). Kept in this browser."));
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

  // --- Exhibits: one picture per finding. Text inside is escaped like everything else. ---
  // Like inline(), but long paths may wrap after a "/" instead of mid-name.
  function pathy(s) {
    return inline(String(s ?? "").replace(/\//g, "/\u2060")).replace(/\/\u2060/g, "/<wbr>");
  }
  function refHTML(r) {
    return r ? `<span class="ref" title="${esc(r)}">${esc(shortPath(r))}</span>` : "";
  }

  const EXHIBIT = {
    compare(ex) {
      const rows = ex.rows.map((r) => `
        <div class="cmp-row${status(r.status) ? " st-" + r.status : ""}">
          <div class="cmp-cell cmp-left"><span class="cmp-tag">${inline(ex.left)}</span>${inline(r.left)}</div>
          <div class="cmp-arrow" aria-hidden="true">${ICON.arrow}</div>
          <div class="cmp-cell cmp-right"><span class="cmp-tag">${inline(ex.right)}</span><span class="cmp-val">${markHTML(r.status)}<span>${inline(r.right)}</span></span></div>
        </div>`).join("");
      return `<div class="cmp"><div class="cmp-head" aria-hidden="true"><span>${inline(ex.left)}</span><span></span><span>${inline(ex.right)}</span></div>${rows}</div>`;
    },
    flow(ex) {
      const steps = ex.steps;
      return `<ol class="flow${steps.length <= 5 ? " flow-short" : ""}">${steps.map((st, k) => `
        <li class="flow-step${st.bad ? " bad" : ""}">
          <span class="flow-num">${k + 1}</span>
          <span class="flow-text">${inline(st.text)}</span>
          ${st.bad ? `<span class="flow-flag">${MARK.bad.icon}Goes wrong here</span>` : ""}
          ${refHTML(st.ref)}
        </li>`).join("")}</ol>`;
    },
    places(ex) {
      const n = (s) => ex.places.filter((x) => x.status === s).length;
      const sum = ["ok", "bad", "warn", "unknown"].filter((s) => n(s))
        .map((s) => `<span class="sum-chip st-${s}">${markHTML(s)}${n(s)} ${{ ok: "ok", bad: n(s) === 1 ? "problem" : "problems", warn: "to watch", unknown: "not checked" }[s]}</span>`).join("");
      return `<div class="places-sum">${sum}</div><ul class="places">${ex.places.map((x) => `
        <li class="place st-${status(x.status)}">
          ${markHTML(x.status)}
          <span class="place-label">${pathy(x.label)}</span>
          ${x.sub ? `<span class="place-sub">${inline(x.sub)}</span>` : ""}
        </li>`).join("")}</ul>`;
    },
    tally(ex) {
      const total = ex.total;
      return `<div class="tally">${ex.rows.map((r) => {
        const st = status(r.status) || "ok";
        let units;
        if (total <= 60) {
          units = `<span class="units${total > 30 ? " units-dense" : ""}" aria-hidden="true">${Array.from({ length: total }, (_, k) =>
            `<span class="unit${k < r.value ? " on" : ""}"></span>`).join("")}</span>`;
        } else {
          const pct = Math.round((r.value / total) * 1000) / 10;
          units = `<span class="bar" aria-hidden="true"><span class="bar-fill" style="width:${pct}%"></span></span>`;
        }
        return `
          <div class="tally-row st-${st}">
            <div class="tally-head"><span class="tally-num">${esc(r.value)}<span class="tally-of"> of ${esc(total)}</span></span><span class="tally-label">${inline(r.label)}</span></div>
            ${units}
          </div>`;
      }).join("")}</div>`;
    },
    timeline(ex) {
      return `<ol class="tl">${ex.events.map((e) => `
        <li class="tl-event st-${status(e.status) || "none"}">
          <span class="tl-when">${esc(e.when)}</span>
          <span class="tl-dot" aria-hidden="true"></span>
          <span class="tl-text">${markHTML(e.status)}<span>${inline(e.text)}</span></span>
        </li>`).join("")}</ol>`;
    },
    code(ex) {
      const sign = { add: "+", del: "−", bad: "!" };
      return `<figure class="code"><figcaption class="code-ref" title="${esc(ex.ref)}">${esc(shortPath(ex.ref))}</figcaption>
        <pre><code>${ex.lines.map((l) => `<span class="ln${l.mark ? " " + esc(l.mark) : ""}"><span class="ln-n">${l.n != null ? esc(l.n) : ""}</span><span class="ln-s" aria-hidden="true">${sign[l.mark] || " "}</span>${l.mark ? `<span class="sr">(${{ add: "added", del: "removed", bad: "problem" }[l.mark]}) </span>` : ""}<span class="ln-t">${esc(/^\s*/.exec(l.text)[0])}<span class="ln-code">${esc(l.text.trimStart())}</span></span></span>`).join("")}</code></pre></figure>`;
    }
  };

  function exhibitHTML(ex) {
    if (!ex || !EXHIBIT[ex.type]) return "";
    return `<div class="exhibit ex-${esc(ex.type)}">${EXHIBIT[ex.type](ex)}${ex.caption ? `<p class="ex-caption">${inline(ex.caption)}</p>` : ""}</div>`;
  }

  // Refs and the long version sit behind one toggle, so the card shows the finding and the picture.
  function moreHTML(it) {
    const refs = it.refs && it.refs.length;
    if (!refs && !it.detail) return "";
    const label = it.detail ? "Details and evidence" : "Evidence";
    return `
      <details class="more">
        <summary>${label}${refs ? ` <span class="more-n">${it.refs.length} ref${it.refs.length === 1 ? "" : "s"}</span>` : ""}</summary>
        ${it.detail ? `<div class="body">${md(it.detail)}</div>` : ""}
        ${refs ? `<ul class="refs">${it.refs.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
      </details>`;
  }

  const withOptions = () => B.items.map((it, i) => i).filter((i) => B.items[i].options && B.items[i].options.length);
  const decidedCount = () => withOptions().filter((i) => state.picks[i] != null).length;

  function pickedText(o) {
    return ICON.check + "<span>Your call: " + inline(o.label) + (o.prompt ? ". The prompt for your agent is on your clipboard." : ".") + "</span>";
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
        ${exhibitHTML(it.exhibit)}
        <div class="body">${md(it.body)}</div>
        ${opts ? `<div class="options" role="group" aria-label="Your call">${opts}</div>
        <p class="picked" id="picked-${i}" aria-live="polite">${chosen ? pickedText(chosen) : ""}</p>` : ""}
        ${moreHTML(it)}
      </article>`;
  }

  function groupItemHTML(it, i) {
    return `
      <article class="item ${esc(it.kind)}${it.urgent ? " urgent" : ""}" id="item-${i}">
        ${it.urgent ? '<span class="stakes stakes-high tag">Most urgent</span>' : ""}
        <h3>${inline(it.title)}</h3>
        ${exhibitHTML(it.exhibit)}
        <div class="body">${md(it.body)}</div>
        ${moreHTML(it)}
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
          ${q.path && q.path.length ? `<div class="path"><p class="label">What happens, step by step</p>${exhibitHTML({ type: "flow", steps: q.path })}</div>` : ""}
          ${q.why ? `<div class="why body">${md(q.why)}</div>` : ""}
          ${MAP && q.area ? `<p class="to-map">${right ? "Your map now counts this for" : "Your map still shows a gap in"} <code>${esc(shortPath(q.area))}</code>${SRV ? "" : " once you open it with <code>plumb.py open</code>"}. <a href="${esc(MAP)}">See the map</a></p>` : ""}
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
    if (MAP) { $("map-link").href = MAP; $("map-link").hidden = false; }
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
      save({ item: i, opt: j });
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
      save({ answer: state.answer });
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
      save({ clear: true });
      render();
      toast("Your answers are cleared.");
    }
  });

  render();
})();
