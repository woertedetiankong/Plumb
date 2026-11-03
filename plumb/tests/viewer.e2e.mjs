// Drives a rendered briefing page in headless Chrome over the DevTools protocol. No dependencies (Node 22+).
// Run: node plumb/tests/viewer.e2e.mjs
import { spawn, execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const skill = join(here, "..", "skills", "brief");
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
if (!existsSync(CHROME)) { console.log("SKIP: Chrome not found (set CHROME)"); process.exit(0); }

// Render the example, plus a copy whose text tries to inject HTML.
const work = mkdtempSync(join(tmpdir(), "plumb-e2e-"));
const example = JSON.parse(readFileSync(join(skill, "examples", "shopfront.json"), "utf8"));
const evil = structuredClone(example);
evil.id = "evil";
evil.items[3].title = "<img src=x onerror=\"window.pwned=1\"> tests";
evil.items[3].body = "`<b>code</b>` and **bold** </script><script>window.pwned=2</script>";
writeFileSync(join(work, "example.json"), JSON.stringify(example));
writeFileSync(join(work, "evil.json"), JSON.stringify(evil));
for (const f of ["example.json", "evil.json"]) {
  execFileSync("python3", [join(skill, "scripts", "plumb.py"), "render", join(work, f), "--out", join(work, "out")]);
}
const page = (id) => "file://" + join(work, "out", `${id}.html`);

const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  "--remote-debugging-port=9334", `--user-data-dir=${join(work, "profile")}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let wsUrl;
for (let i = 0; i < 60 && !wsUrl; i++) {
  try { wsUrl = (await (await fetch("http://127.0.0.1:9334/json/list")).json()).find((t) => t.type === "page")?.webSocketDebuggerUrl; } catch { /* starting */ }
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
const go = async (url) => {
  await send("Page.navigate", { url });
  for (let i = 0; i < 50; i++) { if (await ev(`location.href === ${JSON.stringify(url)} && document.readyState === "complete"`)) break; await sleep(100); }
  await sleep(200);
};
let failures = 0;
const check = (label, ok, detail = "") => { console.log(`${ok ? "PASS" : "FAIL"} ${label}${detail ? "  (" + detail + ")" : ""}`); if (!ok) failures++; };

await send("Page.enable");
await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

await go(page(example.id));
check("renders all 5 items", (await ev("document.querySelectorAll('.item').length")) === 5);
check("sections in order", (await ev("[...document.querySelectorAll('.section-head h2')].map(h => h.textContent).join('|')")) ===
  "Needs your call|Decided without asking|Worth knowing|Not checked");
check("urgent item comes first and is tagged", await ev("document.querySelector('.section .item').classList.contains('urgent') && !!document.querySelector('.item .tag')"));
check("inline code is formatted", await ev("!!document.querySelector('.item .body code')"));

await ev("document.querySelector('.opt[data-item=\"0\"][data-opt=\"0\"]').click()");
await sleep(300);
check("picking an option presses it", (await ev("document.querySelector('.opt[data-item=\"0\"][data-opt=\"0\"]').getAttribute('aria-pressed')")) === "true");
check("picked line shows the call", ((await ev("document.getElementById('picked-0').textContent")) || "").startsWith("Your call: Restore the check"));
check("toast appears", await ev("!document.getElementById('toast').hidden"));

await ev("document.querySelector('.answer[data-key=\"A\"]').click()");
await sleep(200);
check("wrong answer says the right one", (await ev("document.getElementById('fb-title').textContent")) === "Not quite: the answer is B.");
check("wrong choice's note is shown", ((await ev("document.querySelector('.feedback').textContent")) || "").includes("Nothing ignores it any more"));
check("path has 5 steps, 2 marked bad", (await ev("[document.querySelectorAll('.path li').length, document.querySelectorAll('.path li.bad').length].join()")) === "5,2");
check("answers lock after answering", await ev("[...document.querySelectorAll('.answer')].every(b => b.disabled)"));
check("focus moves to the feedback", (await ev("document.activeElement.id")) === "fb-title");

await go(page(example.id));
check("answer survives a reload", await ev("!!document.querySelector('.answer.is-wrong[data-key=\"A\"]')"));
check("pick survives a reload", (await ev("document.querySelector('.opt[data-item=\"0\"][data-opt=\"0\"]').getAttribute('aria-pressed')")) === "true");
await ev("document.getElementById('reset').click()");
await sleep(100);
check("clearing resets answer and picks", await ev("!document.querySelector('.feedback') && !document.querySelector('.opt[aria-pressed=\"true\"]')"));

await go(page("evil"));
check("HTML in text stays text", await ev("!document.querySelector('.item img') && !window.pwned && document.body.textContent.includes('<img src=x')"));
check("data block not broken by </script>", (await ev("document.querySelectorAll('.item').length")) === 5);

await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
await go(page(example.id));
const w = await ev("[innerWidth, document.documentElement.scrollWidth]");
check("fits a 390px phone", w[1] <= w[0], `viewport ${w[0]}, content ${w[1]}`);
const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
if (process.env.PLUMB_SHOTS) writeFileSync(join(process.env.PLUMB_SHOTS, "phone.png"), Buffer.from(shot.result.data, "base64"));

check("no script errors", problems.length === 0, problems.join(" | "));
console.log(failures ? `\n${failures} check(s) failed` : "\nAll checks passed");
ws.close();
chrome.kill();
await sleep(300);
rmSync(work, { recursive: true, force: true });
process.exit(failures ? 1 : 0);
