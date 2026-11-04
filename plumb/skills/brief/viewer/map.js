/* Plumb map page: renders the embedded map data as a treemap with a details panel.
   Served by `plumb.py open`, depth changes are saved to ~/.plumb; opened as a file, the page is read-only. */
(function () {
  "use strict";

  const D = JSON.parse(document.getElementById("map-data").textContent);
  const SRV = (() => {
    const m = document.querySelector('meta[name="plumb-server"]');
    try { return m ? JSON.parse(m.content) : null; } catch (e) { return null; }
  })();
  const $ = (id) => document.getElementById(id);
  const DEPTHS = ["Contract", "Shape", "Every line"];
  const NEED_PHRASE = ["nothing", "the contract", "the shape", "every line"];
  const NEED_LABEL = ["None", "Contract", "Shape", "Every line"];
  const STATUS = {
    solid: { label: "Solid", verdict: "You understand this as deeply as it needs." },
    thin: { label: "Thin", verdict: "You know it, but one level less deeply than it needs." },
    gap: { label: "Gap", verdict: "High stakes, and you don't understand it yet." },
    ok: { label: "Covered", verdict: "Low stakes. Fine to treat as a black box." },
    unknown: { label: "Unchecked", verdict: "Nothing shows yet how well you know it. Answer a briefing question about it, or say how well you know it below." },
    none: { label: "Not mapped", verdict: "These files aren't in any area yet." }
  };
  const ORDER = { gap: 0, thin: 1, unknown: 2, solid: 3, ok: 4, none: 5 };
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function svg(paths, size) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${paths}</svg>`;
  }
  const ARROW = svg('<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>', 16);
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const num = (n) => Number(n || 0).toLocaleString("en-US");
  function day(s) {
    const m = /^(\d{4})-(\d\d)-(\d\d)/.exec(s || "");
    return m ? MONTHS[+m[2] - 1] + " " + +m[3] : s || "";
  }
  const briefingHref = (id, hash) => (SRV ? SRV.briefings + encodeURIComponent(id) : "briefings/" + encodeURIComponent(id) + ".html") + (hash || "");

  let toastTimer;
  function toast(msg) {
    const el = $("toast");
    el.textContent = msg;
    el.hidden = false;
    requestAnimationFrame(() => el.classList.add("show"));
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.classList.remove("show"); toastTimer = setTimeout(() => { el.hidden = true; }, 250); }, 3600);
  }
  async function copy(text) {
    try { await navigator.clipboard.writeText(text); return true; } catch (e) {
      const ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
      ta.remove();
      return ok;
    }
  }

  $("project").textContent = D.project.name;
  $("meta").textContent = "Updated " + day(D.created) + ", " + String(D.created || "").slice(11, 16) + (SRV ? " · live" : "");

  if (!D.areas) {
    $("app").innerHTML = `
      <section class="card empty">
        <p class="eyebrow">Understanding map</p>
        <h1>No map yet for ${esc(D.project.name)}</h1>
        <p class="muted">The map shows each part of your project, sized by code and colored by whether you understand it as deeply as its stakes need. To set it up, run <code>/plumb:map</code> in Claude Code (or <code>$plumb-map</code> in Codex). Your agent proposes the areas and you confirm them.</p>
        ${D.briefings && D.briefings.length ? `<p class="muted">${plural(D.briefings.length, "briefing")} so far. Their answers count once the map exists.</p>` : ""}
      </section>`;
    return;
  }

  // Areas plus one tile for files outside every area.
  const areas = D.areas.map((a) => ({ ...a }));
  if (D.unmapped && D.unmapped.lines > 0) {
    areas.push({ id: "_unmapped", name: "Not in any area", status: "none", lines: D.unmapped.lines, files: D.unmapped.files, need: 0, you: 0, paths: [], calls: [] });
  }
  const mapped = areas.filter((a) => a.id !== "_unmapped");
  const openCalls = mapped.flatMap((a) => a.calls);
  const pending = mapped.filter((a) => a.pending);
  const firstPick = () => {
    const pri = (a) => ORDER[a.status] * 1e12 - a.lines;
    return [...mapped].sort((x, y) => pri(x) - pri(y))[0] || areas[0];
  };
  let picked = (() => {
    try { const id = sessionStorage.getItem("plumb:map:" + D.project.path); if (areas.some((a) => a.id === id)) return id; } catch (e) { /* none */ }
    return firstPick().id;
  })();

  function barsHTML(you, need) {
    return [0, 1, 2].map((i) => `<span class="bar ${i < you ? "have" : i < need ? "missing" : "extra"}"></span>`).join("");
  }

  function bannerHTML() {
    const r = D.recent || { sessions: 0, files: 0, days: 7 };
    const changed = r.sessions
      ? `${plural(r.sessions, "agent session")} changed ${plural(r.files, "file")} in the last ${r.days} days.`
      : `No agent changes in the last ${r.days} days.`;
    let extra = "", link = "";
    if (openCalls.length) {
      const c = openCalls.find((x) => x.urgent) || openCalls[0];
      extra = ` <em>${plural(openCalls.length, "decision")} ${openCalls.length === 1 ? "needs" : "need"} your judgment.</em>`;
      link = `<a class="btn btn-lg btn-on-dark" href="${esc(briefingHref(c.briefing, "#item-" + c.item))}">Open the briefing${ARROW}</a>`;
    } else if (pending.length) {
      extra = ` <em>${plural(pending.length, "question")} ${pending.length === 1 ? "is" : "are"} waiting for you.</em>`;
      link = `<a class="btn btn-lg btn-on-dark" href="${esc(briefingHref(pending[0].pending.briefing, "#check"))}">Answer it${ARROW}</a>`;
    } else if (D.briefings && D.briefings.length) {
      const last = [...D.briefings].sort((a, b) => (a.created < b.created ? 1 : -1))[0];
      link = `<a class="btn btn-lg btn-on-dark" href="${esc(briefingHref(last.id))}">Latest briefing${ARROW}</a>`;
    }
    return `
      <section class="banner" aria-label="While you were away">
        <div class="grow"><p class="eyebrow">While you were away</p><p class="banner-text">${changed}${extra}</p></div>
        ${link}
      </section>`;
  }

  function headHTML() {
    const needYou = mapped.filter((a) => a.status === "gap" || a.status === "thin" || a.status === "unknown").length;
    const gaps = mapped.filter((a) => a.status === "gap").length;
    const unknown = mapped.filter((a) => a.status === "unknown").length;
    return `
      <div class="title-row">
        <div class="grow">
          <h1 class="page-title">What you understand in ${esc(D.project.name)}</h1>
          <p class="lede">Each area is colored by whether you understand it as deeply as its stakes need. Right answers to briefing questions raise it; agent changes since then lower it a level.</p>
        </div>
        <div class="stats">
          <div class="stat"><p class="stat-num">${needYou} of ${mapped.length}</p><p class="stat-label">areas need you</p></div>
          <div class="stat"><p class="stat-num${gaps ? " is-gap" : ""}">${gaps}</p><p class="stat-label">${gaps === 1 ? "gap" : "gaps"} in high-stakes code</p></div>
          ${unknown ? `<div class="stat"><p class="stat-num">${unknown}</p><p class="stat-label">not checked yet</p></div>` : ""}
        </div>
      </div>`;
  }

  // Squarified treemap: rows of tiles laid along the shorter side, keeping tiles close to square.
  function worst(row, side) {
    const sum = row.reduce((s, r) => s + r.v, 0);
    const max = Math.max(...row.map((r) => r.v)), min = Math.min(...row.map((r) => r.v));
    return Math.max((side * side * max) / (sum * sum), (sum * sum) / (side * side * min));
  }
  function squarify(items, x, y, w, h) {
    const out = [];
    let rest = items.slice();
    while (rest.length) {
      if (rest.length === 1 || w < 1 || h < 1) {
        if (w >= h) {
          const sum = rest.reduce((s, r) => s + r.v, 0);
          let xx = x;
          rest.forEach((r) => { const rw = (r.v / sum) * w; out.push({ ...r, x: xx, y, w: rw, h }); xx += rw; });
        } else {
          const sum = rest.reduce((s, r) => s + r.v, 0);
          let yy = y;
          rest.forEach((r) => { const rh = (r.v / sum) * h; out.push({ ...r, x, y: yy, w, h: rh }); yy += rh; });
        }
        break;
      }
      const side = Math.min(w, h);
      const row = [rest[0]];
      let i = 1;
      while (i < rest.length && worst(row.concat(rest[i]), side) <= worst(row, side)) { row.push(rest[i]); i++; }
      const sum = row.reduce((s, r) => s + r.v, 0);
      if (w >= h) {
        const rw = sum / h;
        let yy = y;
        row.forEach((r) => { const rh = r.v / rw; out.push({ ...r, x, y: yy, w: rw, h: rh }); yy += rh; });
        x += rw; w -= rw;
      } else {
        const rh = sum / w;
        let xx = x;
        row.forEach((r) => { const rw = r.v / rh; out.push({ ...r, x: xx, y, w: rw, h: rh }); xx += rw; });
        y += rh; h -= rh;
      }
      rest = rest.slice(i);
    }
    return out;
  }

  function tileHTML(a, style, tiny) {
    const s = STATUS[a.status];
    const flags = (a.calls.length ? " · " + plural(a.calls.length, "call") : "") + (a.pending ? " · question waiting" : "");
    const label = a.id === "_unmapped"
      ? `${a.name}: ${plural(a.files, "file")}.`
      : `${a.name}: ${s.label}. Needs ${NEED_PHRASE[a.need]}; ${a.you == null ? "not checked yet" : "you have " + (a.you ? NEED_PHRASE[a.you] : "nothing yet")}.${flags}`;
    return `
      <button class="tile s-${a.status}${tiny ? " tiny" : ""}" type="button" data-id="${esc(a.id)}" aria-pressed="${a.id === picked}" aria-label="${esc(label)}" title="${esc(a.name)}"${style ? ` style="${style}"` : ""}>
        <span class="tile-top"><span class="tile-name">${esc(a.name)}</span>${a.calls.length ? `<span class="tile-badge" aria-hidden="true">${tiny ? a.calls.length : plural(a.calls.length, "call")}</span>` : ""}</span>
        <span class="tile-foot">
          <span class="tile-label">${s.label}</span>
          ${a.id === "_unmapped" ? "" : `<span class="bars" aria-hidden="true">${barsHTML(a.you || 0, a.need)}</span>`}
        </span>
      </button>`;
  }

  function renderTreemap() {
    const el = $("treemap");
    const width = el.clientWidth;
    if (width < 640) {
      el.classList.add("as-grid");
      el.style.height = "";
      el.innerHTML = [...areas].sort((x, y) => ORDER[x.status] - ORDER[y.status] || y.lines - x.lines).map((a) => tileHTML(a, "", false)).join("");
      return;
    }
    el.classList.remove("as-grid");
    const height = Math.round(Math.min(560, Math.max(340, width * 0.56)));
    el.style.height = height + "px";
    const total = areas.reduce((s, a) => s + a.lines, 0) || areas.length;
    // Small areas are drawn at a minimum size so they stay readable and clickable; the caption says so.
    // Unmapped files get a smaller minimum: they matter only when there are many.
    const floor = (a) => total * (a.id === "_unmapped" ? 0.015 : 0.06);
    const items = areas.map((a) => ({ a, v: Math.max(a.lines || 0, floor(a)) || 1 })).sort((x, y) => y.v - x.v);
    const sum = items.reduce((s, r) => s + r.v, 0);
    items.forEach((r) => { r.v = (r.v / sum) * width * height; });
    const gap = 3;
    el.innerHTML = squarify(items, 0, 0, width, height).map((r) => {
      const w = Math.max(r.w - gap * 2, 4), h = Math.max(r.h - gap * 2, 4);
      const style = `left:${(r.x + gap).toFixed(1)}px;top:${(r.y + gap).toFixed(1)}px;width:${w.toFixed(1)}px;height:${h.toFixed(1)}px`;
      return tileHTML(r.a, style, w < 100 || h < 58).replace('class="tile ', `class="tile${h < 86 || w < 150 ? " short" : ""} `);
    }).join("");
  }

  function depthHTML(a) {
    const you = a.you || 0;
    if (a.you == null) {
      return [1, 2, 3].map((k) => `<div class="depth-step ${k <= a.need ? "unknown" : "extra"}"><b>${DEPTHS[k - 1]}</b><span>${k === a.need ? "Needed · not checked" : k < a.need ? "Not checked" : "Not needed"}</span></div>`).join("");
    }
    a = { ...a, you };
    return [1, 2, 3].map((k) => {
      const needed = k === a.need;
      let cls, note;
      if (k <= a.you) { cls = "have"; note = [k === a.you ? "you" : "", needed ? "needed" : ""].filter(Boolean).join(" · "); }
      else if (k <= a.need) { cls = "missing"; note = needed ? "needed" : "missing"; }
      else { cls = "extra"; note = "not needed"; }
      note = note.charAt(0).toUpperCase() + note.slice(1);
      return `<div class="depth-step ${cls}"><b>${DEPTHS[k - 1]}</b><span>${note}</span></div>`;
    }).join("");
  }

  function changedText(c) {
    if (!c || (!c.sessions && !c.commits)) return "No changes";
    const parts = [];
    if (c.sessions) parts.push(plural(c.sessions, "agent session") + " · " + plural(c.files, "file"));
    if (c.commits) parts.push(plural(c.commits, "commit"));
    return parts.join(" · ");
  }

  function actionsHTML(a) {
    const out = [];
    if (a.pending) {
      out.push(`<a class="btn btn-lg btn-primary btn-block" href="${esc(briefingHref(a.pending.briefing, "#check"))}">Check my understanding${ARROW}</a>`);
    }
    if (a.calls.length) {
      const c = a.calls.find((x) => x.urgent) || a.calls[0];
      out.push(`<a class="btn btn-block${a.pending ? "" : " btn-lg btn-primary"}" href="${esc(briefingHref(c.briefing, "#item-" + c.item))}">Make the call${a.calls.length > 1 ? ` (${a.calls.length})` : ""}${ARROW}</a>`);
    }
    if (a.status === "gap" || a.status === "thin" || a.status === "unknown") {
      if (a.latest_session && a.latest_session.id) {
        const cmd = "/plumb:brief " + a.latest_session.id.slice(0, 8);
        out.push(`<button class="btn btn-block" type="button" data-copy="${esc(cmd)}" data-what="the command">Brief me on the latest change<span class="sr"> (copies ${esc(cmd)})</span></button>
          <p class="btn-sub">Copies <code>${esc(cmd)}</code> · ${esc(a.latest_session.agent === "codex" ? "Codex" : "Claude Code")} session, ${esc(day(a.latest_session.at))}</p>`);
      } else if (!a.pending && !a.calls.length) {
        const prompt = `Explain how ${a.paths.join(", ")} works in this project: the main entry points, what calls them, and what can go wrong. Cite file:line for each step.`;
        out.push(`<p class="note note-ok">No agent changed it recently, so there's no briefing to give. Ask your agent to walk you through it.</p>
          <button class="btn btn-block" type="button" data-copy="${esc(prompt)}" data-what="the prompt">Copy a prompt that explains it</button>`);
      }
    } else if (a.status === "solid" && !out.length) {
      out.push(`<p class="note note-solid">You're current. Nothing here needs you.</p>`);
    } else if (a.status === "ok" && !out.length) {
      out.push(`<p class="note note-ok">Skip it unless something breaks. If it matters more than that, raise how deep it needs to be.</p>`);
    }
    return out.join("");
  }

  function levelSetHTML(a) {
    if (a.need === 0) return "";
    const mine = a.source === "you said" ? a.level : null;
    const btns = [0, 1, 2, 3].map((k) => `<button type="button" class="btn" data-level="${k}" aria-pressed="${k === mine}"${SRV ? "" : " disabled"}>${k ? NEED_LABEL[k] : "Nothing"}</button>`).join("");
    return `<div><p class="depth-title">How well do you know it?</p><div class="need-set" role="group" aria-label="How well you know it">${btns}</div>
      <p class="need-hint">Your answer counts until a briefing question tests it.</p></div>`;
  }

  function needSetHTML(a) {
    const btns = [0, 1, 2, 3].map((k) => `<button type="button" class="btn" data-need="${k}" aria-pressed="${k === a.need}"${SRV ? "" : " disabled"}>${NEED_LABEL[k]}</button>`).join("");
    return `<div><p class="depth-title">How deep it needs to be</p><div class="need-set" role="group" aria-label="How deep it needs to be">${btns}</div>
      ${SRV ? "" : `<p class="need-hint">To change it, open the map with <code>plumb.py open</code> or run <code>/plumb:map</code>.</p>`}</div>`;
  }

  function renderPanel() {
    const a = areas.find((x) => x.id === picked) || areas[0];
    const s = STATUS[a.status];
    if (a.id === "_unmapped") {
      $("panel").innerHTML = `
        <div><span class="chip s-none">${s.label}</span><h2 class="panel-path">${esc(a.name)}</h2><p class="muted">${s.verdict}</p></div>
        <dl class="facts"><div><dt>Size</dt><dd>${num(a.lines)} lines in ${plural(a.files, "file")}</dd></div></dl>
        <p class="note note-ok">Run <code>/plumb:map</code> and ask to add them to an area, if any of them matter.</p>`;
      return;
    }
    const needLine = a.need === 0 ? "You don't need to know how it works. Its behavior is enough." : `Needs ${NEED_PHRASE[a.need]} because ${esc(a.why).replace(/\.$/, "")}.`;
    const last = a.last && a.level ? day(a.last) + " · " + DEPTHS[a.level - 1].toLowerCase() + (a.source === "you said" ? " (you said)" : "") : "Never";
    const check = a.check ? (a.check.right ? "Right" : "Wrong") + " · " + day(a.check.at) : "None yet";
    const facts = [
      [a.changed && a.changed.counted_from === "last checked" ? "Changed since it was last checked"
        : `Changed in the ${a.changed ? a.changed.counted_from : "last 30 days"}`, changedText(a.changed)],
      ["Last understood", last],
      ["Last question", check],
      ["Size", `${num(a.lines)} lines in ${plural(a.files, "file")}`],
      ["Decisions waiting", a.calls.length ? plural(a.calls.length, "call") : "None"]
    ];
    $("panel").innerHTML = `
      <div>
        <span class="chip s-${a.status}">${s.label}</span>
        <h2 class="panel-path">${esc(a.name)}</h2>
        <ul class="panel-paths" aria-label="Files and folders">${a.paths.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>
        <p class="muted">${s.verdict}</p>
      </div>
      <div>
        <p class="depth-title">Depth</p>
        <div class="depth-grid">${depthHTML(a)}</div>
        <p class="need-line">${needLine}</p>
        ${a.stale ? `<p class="stale-line">Agents changed it since it was last checked, so it counts one level lower until you're checked again.</p>` : ""}
        ${a.source === "you said" ? `<p class="need-line">Based on what you said. A briefing question about it will test that.</p>` : ""}
      </div>
      <dl class="facts">${facts.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>
      <div class="actions">${actionsHTML(a)}</div>
      ${levelSetHTML(a)}
      ${needSetHTML(a)}`;
  }

  function render() {
    $("app").innerHTML = `
      ${bannerHTML()}
      ${headHTML()}
      <div class="map-split">
        <section class="card map-main" aria-labelledby="map-title">
          <div class="card-head">
            <h2 id="map-title">Understanding map</h2>
            <p class="muted small">${plural(mapped.length, "area")} · sized by lines of code, small ones enlarged · select one for details</p>
          </div>
          <div id="treemap" class="treemap"></div>
          <div class="legend">
            <span><i class="swatch s-solid" aria-hidden="true"></i>Solid: understood as deeply as it needs</span>
            <span><i class="swatch s-thin" aria-hidden="true"></i>Thin: one level short</span>
            <span><i class="swatch s-gap" aria-hidden="true"></i>Gap: high stakes, not understood</span>
            <span><i class="swatch s-unknown" aria-hidden="true"></i>Unchecked: no answers yet</span>
            <span><i class="swatch s-ok" aria-hidden="true"></i>Covered: low stakes</span>
            <span><span class="bars" aria-hidden="true"><span class="bar have"></span><span class="bar missing"></span><span class="bar extra"></span></span>Bars: contract, shape, every line. Dashed means needed but missing.</span>
          </div>
        </section>
        <aside id="panel" class="card map-side panel" aria-label="Selected area" aria-live="polite"></aside>
      </div>`;
    renderTreemap();
    renderPanel();
  }

  document.addEventListener("click", async (e) => {
    const tile = e.target.closest(".tile");
    if (tile) {
      picked = tile.dataset.id;
      try { sessionStorage.setItem("plumb:map:" + D.project.path, picked); } catch (err) { /* fine */ }
      document.querySelectorAll("#treemap .tile").forEach((t) => t.setAttribute("aria-pressed", String(t.dataset.id === picked)));
      renderPanel();
      if (innerWidth < 1000) $("panel").scrollIntoView({ block: "start" });
      return;
    }
    const c = e.target.closest("[data-copy]");
    if (c) {
      const ok = await copy(c.dataset.copy);
      toast(ok ? `Copied ${c.dataset.what}. Paste it into your agent.` : "Couldn't copy. It is: " + c.dataset.copy);
      return;
    }
    const n = e.target.closest("[data-need], [data-level]");
    if (n && SRV && !n.disabled) {
      const isNeed = "need" in n.dataset;
      const body = { store: SRV.store, area: picked };
      body[isNeed ? "need" : "level"] = Number(isNeed ? n.dataset.need : n.dataset.level);
      try {
        const r = await fetch(isNeed ? "/api/need" : "/api/level", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Plumb-Token": SRV.token },
          body: JSON.stringify(body)
        });
        if (!r.ok) throw new Error(r.status);
        location.reload();
      } catch (err) {
        toast("Couldn't save. Plumb's page server may have stopped; run plumb.py open again.");
      }
    }
  });

  let resizeTimer;
  addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(renderTreemap, 120); });

  render();
})();
