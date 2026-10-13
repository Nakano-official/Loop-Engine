// One picture, drawn inside a sandbox of its own (server.py, DIAGRAM_CSP):
// an opaque origin with no network. The page sends the Mermaid source it built
// from the run's records; this draws it and answers with its height, and with
// which node was clicked. Nothing here can read the dashboard or its token, so
// whatever a label says -- the labels are text a model wrote -- stays here.
"use strict";

const box = document.getElementById("d");
const dark = matchMedia("(prefers-color-scheme: dark)").matches;
mermaid.initialize({
  startOnLoad: false,
  securityLevel: "strict",
  theme: dark ? "dark" : "default",
  fontFamily: "system-ui, sans-serif",
  flowchart: { htmlLabels: false, curve: "basis" },
});

let count = 0;
let current = null;

function tell(message) { parent.postMessage({ loop: true, ...message }, "*"); }
// The frame takes the picture's height, so it never scrolls inside the page.
function size() { tell({ kind: "size", height: Math.ceil(box.getBoundingClientRect().height) + 2 }); }
new ResizeObserver(size).observe(box);

// nodes: {mermaid node id: key}. A click on one of them tells the page the key;
// the page decides whether it means anything.
function clickable(nodes) {
  for (const g of box.querySelectorAll("g.node")) {
    const m = /flowchart-([A-Za-z0-9_]+)-\d+$/.exec(g.id || "");
    const key = m && nodes[m[1]];
    if (!key) continue;
    g.classList.add("pick");
    g.addEventListener("click", () => tell({ kind: "select", key }));
  }
}

addEventListener("message", async (e) => {
  if (e.source !== parent) return;
  const m = e.data;
  if (!m || m.loop !== true || m.kind !== "draw" || typeof m.source !== "string") return;
  if (m.source === current) return;
  current = m.source;
  box.textContent = "描いています…";
  try {
    const { svg } = await mermaid.render(`g${++count}`, m.source);
    box.innerHTML = svg;            // only here: this frame has nothing to protect
    clickable(m.nodes && typeof m.nodes === "object" ? m.nodes : {});
  } catch (err) {
    console.error("diagram:", (err && err.message) || err);
    box.replaceChildren(Object.assign(document.createElement("div"),
      { className: "err", textContent: `図を描けませんでした: ${(err && err.message) || err}` }));
  }
  size();
});

tell({ kind: "ready" });
