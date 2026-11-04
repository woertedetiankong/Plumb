// Drives the map and a briefing through Plumb's local server in headless Chrome. No dependencies (Node 22+).
// Run: node plumb/tests/map.e2e.mjs        (set PLUMB_SHOTS=<folder> to save screenshots)
import { spawn, execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const plumb = join(here, "..", "skills", "brief", "scripts", "plumb.py");
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
if (!existsSync(CHROME)) { console.log("SKIP: Chrome not found (set CHROME)"); process.exit(0); }

const work = mkdtempSync(join(tmpdir(), "plumb-map-"));
const env = { ...process.env, PLUMB_HOME: join(work, "home"), PLUMB_CLAUDE_DIR: join(work, "claude"),
  PLUMB_CODEX_DIR: join(work, "codex"), PLUMB_PORT: "7362" };
const py = (args, cwd) => execFileSync("python3", [plumb, ...args], { cwd, env, encoding: "utf8" });
const bid = execFileSync("python3", ["-I", join(here, "map_fixture.py"), work, plumb], { encoding: "utf8" }).trim();
const repo = join(work, "shopfront");
py(["areas", "--set", join(work, "areas.json")], repo);
py(["render", join(work, "briefing.json")], repo);
const mapUrl = /Map: (\S+)/.exec(py(["open", "--no-browser"], repo))[1];
const briefUrl = /Briefing: (\S+)/.exec(py(["open", bid, "--no-browser"], repo))[1];
const server = JSON.parse(readFileSync(join(work, "home", "server.json"), "utf8"));
const mapFile = join(work, "home", "projects", mapUrl.split("/p/")[1].split("/")[0], "map.html");

const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  "--remote-debugging-port=9335", `--user-data-dir=${join(work, "profile")}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let wsUrl;
for (let i = 0; i < 60 && !wsUrl; i++) {
  try { wsUrl = (await (await fetch("http://127.0.0.1:9335/json/list")).json()).find((t) => t.type === "page")?.webSocketDebuggerUrl; } catch { /* starting */ }
  if (!wsUrl) await sleep(200);
}
if (!wsUrl) { console.log("FAIL: could not connect to Chrome"); chrome.kill(); process.exit(1); }
const ws = new WebSocket(wsUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0;
const pending = new Map(), problems = [];
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  if (m.method === "Runtime.exceptionThrown") problems.push(m.params.exceptionDetails.exception?.description);
  if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") problems.push(m.params.args.map((a) => a.value).join(" "));
});
const send = (method, params = {}) => new Promise((resolve) => { const n = ++id; pending.set(n, resolve); ws.send(JSON.stringify({ id: n, method, params })); });
const ev = async (expr) => (await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true })).result?.result?.value;
const loaded = async () => { for (let i = 0; i < 50; i++) { if (await ev(`document.readyState === "complete"`)) break; await sleep(100); } await sleep(250); };
const go = async (url) => { await send("Page.navigate", { url }); await sleep(100); await loaded(); };
const shot = async (name) => {
  if (!process.env.PLUMB_SHOTS) return;
  const r = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  writeFileSync(join(process.env.PLUMB_SHOTS, name), Buffer.from(r.result.data, "base64"));
};
let failures = 0;
const check = (label, ok, detail = "") => { console.log(`${ok ? "PASS" : "FAIL"} ${label}${detail ? "  (" + detail + ")" : ""}`); if (!ok) failures++; };
const status = (aid) => ev(`(document.querySelector('.tile[data-id="${aid}"]')?.className.match(/s-(\\w+)/) || [])[1]`);
const clickTile = async (aid) => { await ev(`document.querySelector('.tile[data-id="${aid}"]').click()`); await sleep(100); };
const clickAndReload = async (sel) => { await ev(`document.querySelector('${sel}').click()`); await sleep(600); await loaded(); };

await send("Page.enable");
await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 1000, deviceScaleFactor: 1, mobile: false });

await go(mapUrl);
check("map shows 11 areas plus the unmapped files", (await ev("document.querySelectorAll('.tile').length")) === 12);
check("unchecked areas start as Not checked, not Gap", (await ev("document.querySelectorAll('.tile.s-unknown').length")) === 9 &&
  (await ev("document.querySelectorAll('.tile.s-gap').length")) === 0);
check("low-stakes areas are Covered", (await status("ui")) === "ok" && (await status("tests")) === "ok");
check("banner counts the 2 open calls", ((await ev("document.querySelector('.banner-text').textContent")) || "").includes("2 decisions need your judgment"));
check("banner counts agent changes", ((await ev("document.querySelector('.banner-text').textContent")) || "").includes("1 agent session changed 5 files"));
check("tiles don't overlap the map's edges", await ev(`(() => { const m = document.getElementById('treemap').getBoundingClientRect();
  return [...document.querySelectorAll('.tile')].every(t => { const r = t.getBoundingClientRect(); return r.left >= m.left - 1 && r.right <= m.right + 1 && r.top >= m.top - 1 && r.bottom <= m.bottom + 1; }); })()`));
await clickTile("webhooks");
check("webhooks panel offers the waiting question", ((await ev("document.querySelector('#panel .actions').textContent")) || "").includes("Check my understanding"));
check("webhooks panel counts its call", ((await ev("document.getElementById('panel').textContent")) || "").includes("Decisions waiting1 call"));
await shot("map-desktop.png");

await clickTile("refunds");
await clickAndReload('[data-level="2"]');
check("saying you know refunds at shape makes it Thin", (await status("refunds")) === "thin");
check("the selected area survives the reload", (await ev("document.querySelector('.tile[aria-pressed=\"true\"]').dataset.id")) === "refunds");
check("the panel says it's self-reported", ((await ev("document.getElementById('panel').textContent")) || "").includes("(you said)"));

await go(briefUrl);
check("briefing links back to the map", await ev("!document.getElementById('map-link').hidden && document.getElementById('map-link').getAttribute('href').endsWith('/map')"));
await ev("document.querySelector('.opt[data-item=\"0\"][data-opt=\"0\"]').click()");
await sleep(300);
await ev("document.getElementById('open-question').click()");
await sleep(100);
await ev("document.querySelector('.answer[data-key=\"B\"]').click()");
await sleep(400);
check("a right answer points to the map", ((await ev("document.querySelector('.to-map')?.textContent")) || "").includes("Your map now counts this"));
await ev("localStorage.clear()");
await go(briefUrl);
check("pick and answer come back from the server", await ev("document.querySelector('.opt[data-item=\"0\"][data-opt=\"0\"]').getAttribute('aria-pressed') === 'true' && !!document.querySelector('.answer.is-right[data-key=\"B\"]')"));
const answers = JSON.parse(readFileSync(join(mapFile, "..", "answers.json"), "utf8"));
check("answers.json has the pick and the answer", answers.briefings[bid].picks["0"] === 0 && answers.briefings[bid].answer.key === "B");

await go(mapUrl);
check("a right shape answer makes webhooks Thin", (await status("webhooks")) === "thin");
check("its call no longer counts", ((await ev("document.querySelector('.banner-text').textContent")) || "").includes("1 decision needs your judgment"));
await clickTile("webhooks");
await clickAndReload('[data-need="2"]');
check("lowering what webhooks needs to shape makes it Solid", (await status("webhooks")) === "solid");
check("the POST guard rejects a missing token", (await ev(`fetch('/api/need', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}).then(r => r.status)`)) === 403);

await go("file://" + mapFile);
check("the map also opens as a plain file", (await ev("document.querySelectorAll('.tile').length")) === 12);
check("as a file, depth buttons are read-only", await ev("[...document.querySelectorAll('[data-need]')].every(b => b.disabled)"));
check("as a file, briefing links point at the files", ((await ev("document.querySelector('.banner .btn')?.getAttribute('href')")) || "").startsWith("briefings/"));

await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
await go(mapUrl);
const w = await ev("[innerWidth, document.documentElement.scrollWidth]");
check("fits a 390px phone", w[1] <= w[0], `viewport ${w[0]}, content ${w[1]}`);
check("on a phone the map is a list, worst first", (await ev("document.getElementById('treemap').classList.contains('as-grid')")) &&
  (await ev("document.querySelector('.tile').dataset.id")) !== "ui");
await shot("map-phone.png");

check("no script errors", problems.length === 0, problems.join(" | "));
console.log(failures ? `\n${failures} check(s) failed` : "\nAll checks passed");
ws.close();
chrome.kill();
try { process.kill(server.pid); } catch { /* already stopped */ }
await sleep(300);
rmSync(work, { recursive: true, force: true });
process.exit(failures ? 1 : 0);
