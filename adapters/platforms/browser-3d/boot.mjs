// The boot check for a browser-3d app. happy-dom has no WebGL, so nothing is
// drawn here: the shell runs without its renderer and every Scene is still
// checked for shape (shell.ts, check). Through the handle the shell returns
// (window.__loop), the app is run for 300 frames at 60 per second with a
// player holding "w", then "d", moving the mouse, and clicking every 50
// frames. It must survive all of it and keep returning a well-formed Scene.
// How it looks and how it feels to play are a person's to judge.
//
//   node boot.mjs <app.html> <path to happy-dom's lib/index.js>
//
// Prints one JSON object: {"ok", "title", "frames", "objects", "hud",
// "moved", "errors"}. Runs as exec: the app's code runs here, and the exec
// account is the boundary (see the browser-dom boot check).
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [, , htmlPath, happyDom] = process.argv;
const { Window } = await import(pathToFileURL(happyDom).href);
const html = readFileSync(htmlPath, "utf-8");
const errors = [];
const w = new Window({
  url: "http://localhost/",
  settings: { enableJavaScriptEvaluation: true, suppressInsecureJavaScriptEnvironmentWarning: true },
});
w.addEventListener("error", (e) => errors.push(String(e?.error?.message ?? e?.message ?? e)));
w.console.error = (...a) => errors.push(a.map(String).join(" "));
const settle = () => new Promise((r) => setTimeout(r, 50));

w.document.write(html);
await settle();
if (!w.__loop) {
  for (const old of [...w.document.querySelectorAll("script")]) {
    const s = w.document.createElement("script");
    s.textContent = old.textContent;
    old.replaceWith(s);
  }
  await settle();
}

const loop = w.__loop;
let frames = 0, first = null, last = null;
if (!loop) {
  errors.push("the shell did not start (no window.__loop)");
} else {
  const t0 = 1000;
  for (let i = 0; i < 300; i++) {
    const input = { keys: i < 150 ? ["w"] : ["d"], mouse_dx: 3, mouse_dy: i % 2 ? 1 : -1, locked: true };
    try {
      last = loop.frame(t0 + i / 60, input);
      if (!first) first = JSON.parse(JSON.stringify(last.camera));
      frames += 1;
    } catch (e) {
      errors.push(`frame ${i}: ${e?.message ?? e}`);
      break;
    }
    if (i % 50 === 25) loop.act("click");
  }
}
await settle();

const cam = last?.camera;
const moved = !!(first && cam && (first.position.x !== cam.position.x || first.position.z !== cam.position.z
                                   || first.yaw !== cam.yaw));
const ok = errors.length === 0 && frames === 300 && !!last;
console.log(JSON.stringify({ ok, title: last?.title ?? w.document.title, frames,
                             objects: last?.objects.length ?? 0, hud: last?.hud.length ?? 0, moved, errors }));
process.exit(0);
