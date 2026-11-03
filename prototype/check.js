/* Check page: one explain-it-back question. A right answer moves refunds from Gap to Thin. */
(function () {
  "use strict";

  const P = window.Plumb;
  const state = P.load();
  const $ = (id) => document.getElementById(id);

  const ANSWERS = [
    ["A", "The late webhook is ignored, because the refund already went through."],
    ["B", "The customer is refunded twice."],
    ["C", "The retry is undone and the refund is marked as failed."],
    ["D", "refund_attempts sees the earlier attempt and blocks the second refund."]
  ];

  const WRONG_NOTES = {
    A: "Nothing ignores it any more: the check that used to do that was removed last night.",
    C: "A late webhook doesn't undo anything. The handler treats it as a fresh request to refund.",
    D: "refund_attempts only records attempts. Nothing reads it before issuing a refund."
  };

  const PATH = [
    ["The refund times out", false],
    ["The retry succeeds and the refund is issued", false],
    ["The provider's original webhook arrives late", false],
    ["The handler no longer checks for an existing refund", true],
    ["A second refund is issued", true]
  ];

  function answersHTML(answer) {
    const answered = answer !== null;
    return ANSWERS.map(([key, text]) => {
      let cls = "";
      let tag = "";
      if (answered && key === P.RIGHT_ANSWER) {
        cls = " is-right";
        tag = key === answer ? "Your answer · right" : "Right answer";
      } else if (answered && key === answer) {
        cls = " is-wrong";
        tag = "Your answer";
      }
      return `
        <button class="answer${cls}" type="button" data-key="${key}" aria-pressed="${key === answer}"${answered ? " disabled" : ""}>
          <span class="answer-key">${key}</span>
          <span class="answer-text">${P.esc(text)}</span>
          ${tag ? `<span class="answer-tag">${tag}</span>` : ""}
        </button>`;
    }).join("");
  }

  function feedbackHTML(answer) {
    const right = answer === P.RIGHT_ANSWER;
    const restoreQueued = state.picks.d1 === "restore";
    const title = right ? "Right." : "Not quite, and that's useful to know.";
    const text = right
      ? "The retry already issued the refund. When the late webhook arrives, the handler no longer checks whether a refund exists, so it issues another one. That's why the first decision in your briefing matters."
      : `${WRONG_NOTES[answer]} Here's what actually happens:`;
    const buttons = right
      ? `<button class="btn btn-lg btn-primary" type="button" data-action="restore"${restoreQueued ? " disabled" : ""}>${restoreQueued ? "Restore queued" : "Restore the duplicate check"}</button>
         <button class="btn btn-lg" type="button" data-todo="The line-by-line walkthrough">Walk me through the 62 lines that move money</button>`
      : `<button class="btn btn-lg btn-primary" type="button" data-todo="The step-by-step walkthrough">Walk me through it</button>
         <button class="btn btn-lg" type="button" data-action="retry">Try again</button>`;
    const restoreNote = right && restoreQueued
      ? P.ICON.check + "Queued: Claude Code will restore the check and add a test for duplicate webhooks."
      : "";
    return `
      <div>
        <h2 class="fb-title" id="feedback-title" tabindex="-1">${title}</h2>
        <p class="fb-text">${P.esc(text)}</p>
      </div>
      <ol class="path" aria-label="What happens, step by step">
        ${PATH.map(([step, bad], i) => `<li class="${bad ? "bad" : ""}"><b>Step ${i + 1}</b><span>${step}</span></li>`).join("")}
      </ol>
      <div class="btn-row">
        ${buttons}
        <a class="btn-link" href="index.html">Back to the map</a>
      </div>
      <p class="result">${restoreNote}</p>`;
  }

  function sideHTML(answer) {
    const answered = answer !== null;
    const right = answer === P.RIGHT_ANSWER;
    let title;
    let text;
    if (right) {
      title = "Gap → Thin";
      text = "You now understand how refunds fit together. Code that moves money needs every line, so one step is left: a walkthrough of the 62 lines that matter.";
    } else if (answered) {
      title = "Still a gap";
      text = "No change yet, and that's fine. The walkthrough shows the path step by step, then you can try again.";
    } else {
      title = "Gap now";
      text = "Answer this right and payments/refunds moves from Gap to Thin: you'll understand its shape.";
    }
    const ladder = [
      ["Contract", "You have it", true],
      ["Shape", right ? "You have it now" : "This question", right],
      ["Every line", "Walkthrough · 62 lines", false]
    ];
    return `
      <p class="eyebrow">Your map</p>
      <div class="big-tile s-${right ? "thin" : "gap"}">
        <span class="tile-name">payments/refunds</span>
        <span class="tile-foot">
          <span class="tile-label">${right ? "Thin" : "Gap"}</span>
          <span class="bars" aria-hidden="true">${P.barsHTML(right ? 2 : 1, 3)}</span>
        </span>
      </div>
      <div>
        <h2 class="side-title">${title}</h2>
        <p class="muted">${text}</p>
      </div>
      <ul class="ladder">
        ${ladder.map(([name, when, done]) => `
          <li>
            <span class="${done ? "ic-done" : "ic-todo"}">${done ? P.ICON.checkLg : P.ICON.circle}</span>
            <span class="ladder-name">${name}</span>
            <span class="when">${when}</span>
          </li>`).join("")}
      </ul>`;
  }

  function render() {
    const answer = state.answer;
    $("answers").innerHTML = answersHTML(answer);
    const feedback = $("feedback");
    feedback.hidden = answer === null;
    feedback.innerHTML = answer === null ? "" : feedbackHTML(answer);
    $("side").innerHTML = sideHTML(answer);
  }

  $("answers").addEventListener("click", (e) => {
    const btn = e.target.closest(".answer");
    if (!btn || btn.disabled) return;
    state.answer = btn.dataset.key;
    P.save(state);
    render();
    $("feedback-title").focus();
  });

  $("feedback").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    if (btn.dataset.action === "retry") {
      state.answer = null;
      P.save(state);
      render();
      $("answers").querySelector(".answer").focus();
    } else if (btn.dataset.action === "restore") {
      state.picks.d1 = "restore";
      P.save(state);
      render();
      P.renderHeader();
    }
  });

  render();
})();
