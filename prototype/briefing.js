/* Briefing page: the decisions the agents made, and the visitor's answers to them. */
(function () {
  "use strict";

  const P = window.Plumb;
  const state = P.load();
  const $ = (id) => document.getElementById(id);

  // options: [key, button label, what happens after you pick it]
  const DECISIONS = [
    {
      id: "d1",
      urgent: true,
      stakes: "Needs your call",
      file: "webhooks/handler.ts · 14 lines removed",
      title: "The check that stops double refunds was removed.",
      why: 'In "Fix flaky refund tests", two tests started failing after the retry change. Deleting the check made them pass.',
      means: "If the provider sends the same webhook twice, or a late one after a retry, a customer can be refunded twice.",
      flag: "Shortcut signal: a safety check was deleted to make tests pass.",
      options: [
        ["restore", "Restore the check", "Queued: Claude Code will restore the check and add a test for duplicate webhooks."],
        ["keep", "Keep it removed", "Noted: you chose to keep it removed. Plumb will raise it again in your next webhooks briefing."],
        ["ask", "Ask the agent why", "Asked. The agent's answer will appear here."]
      ]
    },
    {
      id: "d2",
      urgent: false,
      stakes: "Worth a look",
      file: "payments/refunds/retry.ts · new, 86 lines",
      title: "Failed refunds retry up to 5 times, after 2, 4, 8, 16 and 32 seconds.",
      why: "The provider blocks bursts of requests. Spacing retries out avoids being blocked.",
      means: 'A refund can take about a minute to go through, so support will see "pending" for longer.',
      flag: "",
      options: [
        ["agree", "Agree", "Marked as decided by you."],
        ["change", "Change the timing", "Tell the agent the timing you want and it will update retry.ts."],
        ["ask", "Ask why", "Asked. The agent's answer will appear here."]
      ]
    },
    {
      id: "d3",
      urgent: false,
      stakes: "Worth a look",
      file: "db/migrations/0042_refund_attempts.sql · new",
      title: "A new table, refund_attempts, records every try.",
      why: "Support asked to see why a refund failed.",
      means: "It changes the production database and is hard to undo. It also stores the provider's raw error text, so check that no card details end up in it.",
      flag: "",
      options: [
        ["agree", "Agree", "Marked as decided by you."],
        ["less", "Store less", "Queued: Codex will drop the raw error text and keep only the error code."],
        ["ask", "Ask why", "Asked. The agent's answer will appear here."]
      ]
    }
  ];

  function resultHTML(decision, key) {
    const option = decision.options.find((o) => o[0] === key);
    return option ? P.ICON.check + P.esc(option[2]) : "";
  }

  function renderDecisions() {
    $("decision-list").innerHTML = DECISIONS.map((d) => {
      const chosen = state.picks[d.id];
      return `
        <article class="decision${d.urgent ? " urgent" : ""}" aria-labelledby="${d.id}-title">
          <div class="decision-meta">
            <span class="stakes ${d.urgent ? "stakes-high" : "stakes-mid"}">${d.stakes}</span>
            <span class="file">${P.esc(d.file)}</span>
          </div>
          <h3 id="${d.id}-title">${P.esc(d.title)}</h3>
          <div class="two-col">
            <div><p class="label">Why the agent did it</p><p>${P.esc(d.why)}</p></div>
            <div><p class="label">What it means for you</p><p>${P.esc(d.means)}</p></div>
          </div>
          ${d.flag ? `<p class="flag">${P.ICON.alert}${P.esc(d.flag)}</p>` : ""}
          <div class="options" role="group" aria-label="Your decision">
            ${d.options.map((o) => `<button class="btn opt" type="button" data-decision="${d.id}" data-key="${o[0]}" aria-pressed="${chosen === o[0]}">${P.esc(o[1])}</button>`).join("")}
          </div>
          <p class="result" aria-live="polite">${resultHTML(d, chosen)}</p>
        </article>`;
    }).join("");
  }

  function renderProgress() {
    const decided = DECISIONS.filter((d) => state.picks[d.id]).length;
    $("decided-count").textContent = `${decided} of ${DECISIONS.length}`;
    $("cta-title").textContent = decided === DECISIONS.length
      ? "All 3 decisions made. One last step."
      : "Done reading? Check your understanding.";
  }

  $("decision-list").addEventListener("click", (e) => {
    const btn = e.target.closest(".opt");
    if (!btn) return;
    const id = btn.dataset.decision;
    const key = btn.dataset.key;
    state.picks[id] = key;
    P.save(state);

    // Update the card in place so focus and the live region survive.
    const card = btn.closest(".decision");
    card.querySelectorAll(".opt").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.key === key)));
    card.querySelector(".result").innerHTML = resultHTML(DECISIONS.find((d) => d.id === id), key);
    renderProgress();
    P.renderHeader();
  });

  renderDecisions();
  renderProgress();
})();
