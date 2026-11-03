/* Recap page: the before-and-after mini maps on the monthly card. */
(function () {
  "use strict";

  const P = window.Plumb;

  // Snapshots of each area's status at the start and end of the month.
  const OCT_1 = { refunds: "gap", checkout: "gap", orders: "thin", search: "solid", notifications: "thin", sessions: "gap", migrations: "gap", webhooks: "gap", inventory: "thin", api: "thin", ui: "ok", scripts: "ok", analytics: "ok" };
  const OCT_31 = { refunds: "gap", checkout: "solid", orders: "solid", search: "solid", notifications: "solid", sessions: "thin", migrations: "gap", webhooks: "thin", inventory: "thin", api: "solid", ui: "ok", scripts: "ok", analytics: "ok" };

  function summary(snapshot) {
    const counts = { solid: 0, thin: 0, gap: 0, ok: 0 };
    Object.values(snapshot).forEach((s) => { counts[s] += 1; });
    return `${counts.solid} solid, ${counts.thin} thin, ${counts.gap} gaps, ${counts.ok} covered by tests`;
  }

  function fill(id, label, snapshot) {
    const el = document.getElementById(id);
    el.setAttribute("aria-label", `Map on ${label}: ${summary(snapshot)}`);
    el.innerHTML = P.MODULES
      .map((m) => `<div class="mini s-${snapshot[m.id]}" style="grid-column: ${m.col}; grid-row: ${m.row};"></div>`)
      .join("");
  }

  fill("map-before", "October 1", OCT_1);
  fill("map-after", "October 31", OCT_31);
})();
