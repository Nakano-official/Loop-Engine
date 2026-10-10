// The boot check for a browser-dom app: open the HTML in happy-dom (no screen
// needed), let it draw, press every enabled button once, let a moment pass.
// It checks what a machine can check about the output -- that it opens, draws
// something and survives its own buttons. How it looks and feels is a person's.
//
//   node boot.mjs <app.html> <path to happy-dom's lib/index.js>
//
// Prints one JSON object: {"ok": bool, "title", "nodes", "buttons", "pressed",
// "errors": [...]}.
//
// The app's code runs here, so this runs as exec (window.py, build-app): no
// network, nothing writable but its own out/. happy-dom warns that its VM
// context is not an isolation boundary, and it is right -- the boundary is the
// exec account, the same one the generated tests run under. The warning is
// turned off for that reason, not because the risk is gone.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [, , htmlPath, happyDom] = process.argv;
// As a file URL: a bare Windows path (C:\...) is not something import() accepts.
const { Window } = await import(pathToFileURL(happyDom).href);
const html = readFileSync(htmlPath, "utf-8");
const errors = [];
const w = new Window({
  url: "http://localhost/",
  settings: { enableJavaScriptEvaluation: true, suppressInsecureJavaScriptEnvironmentWarning: true },
});
w.addEventListener("error", (e) => errors.push(String(e?.error?.message ?? e?.message ?? e)));
w.console.error = (...a) => errors.push(a.map(String).join(" "));

// Never waitUntilComplete: the shell's setInterval never completes, and the
// wait would last forever. A short pause is enough for a script that runs on
// insertion and draws synchronously.
const settle = () => new Promise((r) => setTimeout(r, 50));

w.document.write(html);
await settle();
// If writing the document did not run its script, insert it again as a node.
if (!(w.document.getElementById("app")?.children.length > 0)) {
  for (const old of [...w.document.querySelectorAll("script")]) {
    const s = w.document.createElement("script");
    s.textContent = old.textContent;
    old.replaceWith(s);
  }
  await settle();
}

const root = w.document.getElementById("app");
const nodes = root ? root.children.length : 0;
const labels = root ? [...root.querySelectorAll("button")].map((b) => b.textContent) : [];
let pressed = 0;
for (const label of labels) {
  // Each press redraws, so find the button again by its label.
  const b = [...w.document.querySelectorAll("#app button")].find((x) => x.textContent === label);
  if (b && !b.disabled) {
    b.click();
    pressed += 1;
  }
}
await settle();
const after = w.document.getElementById("app")?.children.length ?? 0;
const title = w.document.title;

const ok = errors.length === 0 && nodes > 0 && after > 0;
console.log(JSON.stringify({ ok, title, nodes, buttons: labels.length, pressed, errors }));
// Exit here: the app's interval would keep the process alive, and closing a
// window with a live interval is not something to wait on either.
process.exit(0);
