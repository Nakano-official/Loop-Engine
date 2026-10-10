// The dashboard page. Everything shown is read from the server's JSON and put
// into the page with textContent -- never innerHTML -- so nothing a run wrote
// (a reason, a note, a module name) can become markup here. The apps a run
// produced are shown only in a sandboxed iframe; the server adds a CSP sandbox
// as well, so they get an opaque origin either way.
"use strict";

let session = null;
let selected = { app: null, run: null };
// What the detail pane was last drawn from. It is redrawn only when that
// changes: a redraw would reload the app's iframe -- resetting a game being
// played -- and drop a note being typed.
let drawnFrom = "";

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

async function get(path) {
  const r = await fetch(path, { cache: "no-store" });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  return r.json();
}

async function post(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Loop-Token": session.token },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

const STATUS = {
  running: ["実行中", "info"], done: ["完了", "ok"], failed: ["戻り先あり", "bad"], stopped: ["停止", "warn"],
  interrupted: ["中断", "warn"],
};
const MODULE = {
  green: ["緑", "ok"], trying: ["試行中", "info"], red: ["赤の関門", "info"],
  exhausted: ["使い切り", "bad"], engine: ["エンジン", "bad"],
};
const chip = (pair, extra) => h("span", { class: `chip ${pair[1]}` }, pair[0], extra ? ` ${extra}` : "");

function decisionChip(d) {
  if (!d) return null;
  return d.verdict === "approve" ? chip(["承認済み", "ok"]) : chip(["差し戻し", "warn"]);
}

// ---- the header ---------------------------------------------------------------

async function drawBox() {
  const el = document.getElementById("box");
  try {
    const b = await get("/api/box");
    const up = (v) => (v === "active" || v === "ok" ? "ok" : "bad");
    el.replaceChildren(
      chip(["窓口", up(b.window)], b.window === "ok" ? "" : "×"),
      chip(["モデル", up(b.llm)], b.llm || "?"),
      chip(["通信制限", up(b.egress)], b.egress || "?"),
      b.work ? chip(["空き", "info"], b.work) : null,
    );
    if (b.error) el.append(h("span", { class: "note" }, b.error));
  } catch (e) {
    el.replaceChildren(chip(["箱", "bad"], "応答なし"));
  }
}

function drawWho() {
  const who = document.getElementById("who");
  who.textContent = session.scope === "local" ? "この PC から" : `遠隔: ${session.user}（承認と起動はできません）`;
}

// ---- the apps -------------------------------------------------------------------

async function drawApps() {
  const data = await get("/api/apps");
  const nav = document.getElementById("apps");
  nav.replaceChildren(...data.apps.map((a) => {
    const latest = a.latest;
    return h("button", {
      class: a.name === selected.app ? "on" : "",
      onclick: () => { selected = { app: a.name, run: null }; refresh(); },
    },
      h("div", { class: "title" }, a.title),
      h("div", { class: "sub" }, a.name, " · ", `${a.runs} 回`,
        latest ? [" · ", chip(STATUS[latest.status] || [latest.status, "info"])] : ""));
  }));
  if (!data.apps.length) nav.append(h("p", { class: "muted" }, "アプリがまだありません。engine/cli.py new で作ります。"));
  return data.running;
}

// ---- one app ----------------------------------------------------------------------

async function drawApp(running) {
  const box = document.getElementById("detail");
  if (!selected.app) return;
  const app = await get(`/api/apps/${encodeURIComponent(selected.app)}`);
  if (!selected.run && app.runs.length) selected.run = app.runs[0].id;
  const run = selected.run
    ? await get(`/api/apps/${encodeURIComponent(app.name)}/runs/${encodeURIComponent(selected.run)}`) : null;
  const from = JSON.stringify([app, run, running, selected]);
  if (from === drawnFrom) return;
  drawnFrom = from;
  const busy = Boolean(running);
  const start = h("button", {
    class: "act primary", disabled: !session.can_start || busy,
    onclick: async () => {
      try { await post("/api/runs/start", { app: app.name }); setTimeout(refresh, 1500); }
      catch (e) { alert(e.message); }
    },
  }, "通しを始める");

  const runs = h("table", {},
    h("tr", {}, h("th", {}, "通し"), h("th", {}, "状態"), h("th", {}, "結果"), h("th", {}, "判断")),
    ...app.runs.map((r) => h("tr", {
      class: `pick ${r.id === selected.run ? "on" : ""}`,
      onclick: () => { selected.run = r.id; refresh(); },
    },
      h("td", {}, r.id),
      h("td", {}, chip(STATUS[r.status] || [r.status, "info"])),
      h("td", {}, r.reason || ""),
      h("td", {}, decisionChip(r.decision) || ""))));

  const parts = [
    h("h2", {}, app.title, h("span", { class: "muted" }, `  ${app.name}`)),
    h("div", { class: "row" }, start,
      busy ? h("span", { class: "note" }, `実行中の通しがあります（${running.app}）。同時に1つだけです。`) : null,
      !session.can_start ? h("span", { class: "note" }, "通しはこの PC から始めます。") : null),
    h("h3", {}, "通し"),
    app.runs.length ? runs : h("p", { class: "muted" }, "まだ通していません。"),
  ];
  if (run) parts.push(drawRun(app, run));
  box.replaceChildren(...parts);
}

function drawRun(app, run) {
  const modules = h("table", {},
    h("tr", {}, h("th", {}, "モジュール"), h("th", {}, "状態"), h("th", {}, "試行"), h("th", {}, "判定")),
    ...run.modules.map((m) => h("tr", {},
      h("td", {}, m.module),
      h("td", {}, chip(MODULE[m.state] || [m.state, "info"])),
      h("td", {}, String(m.attempts)),
      h("td", {}, m.reason || ""))));

  const out = [h("h3", {}, `通し ${run.id}`),
    h("div", { class: "row" }, chip(STATUS[run.status] || [run.status, "info"]),
      run.stage ? h("span", {}, `戻り先・結果: ${run.stage}`) : null,
      run.status === "running" ? h("button", {
        class: "act danger",
        onclick: async () => { try { await post("/api/runs/stop", { app: app.name, run: run.id }); refresh(); }
                               catch (e) { alert(e.message); } },
      }, "止める") : null),
    run.reason ? h("p", {}, run.reason) : null,
    modules];

  if (run.output) {
    const src = `/play/${encodeURIComponent(app.name)}/${encodeURIComponent(run.id)}`;
    const note = h("textarea", { placeholder: "気づいたこと（差し戻しの理由など）" });
    const decide = (verdict) => async () => {
      try { await post("/api/decision", { app: app.name, run: run.id, verdict, note: note.value }); refresh(); }
      catch (e) { alert(e.message); }
    };
    out.push(
      h("h3", {}, "出力されたアプリ"),
      // sandbox="allow-scripts": runs, but with an opaque origin -- no access to
      // this page, its token, or its storage. The server's CSP says the same.
      h("iframe", { class: "play", src, sandbox: "allow-scripts", title: "出力されたアプリ" }),
      h("div", { class: "row" },
        h("a", { href: src, target: "_blank", rel: "noopener" }, "新しいタブで開く"),
        h("span", { class: "note" }, "ここでは保存（localStorage）は効きません。遊んで確かめるための表示です。")),
      h("h3", {}, "判断"),
      note,
      h("div", { class: "row" },
        h("button", { class: "act primary", disabled: !session.can_approve, onclick: decide("approve") }, "承認する"),
        h("button", { class: "act", onclick: decide("reject") }, "差し戻す"),
        !session.can_approve ? h("span", { class: "note" }, "承認はこの PC の前からだけです（遊べる場所で決めるため）。") : null),
    );
  }
  if (run.decisions.length) {
    out.push(h("ul", {}, ...run.decisions.map((d) => h("li", {},
      decisionChip(d), ` ${new Date(d.t * 1000).toLocaleString()} ${d.user}（${d.scope === "local" ? "この PC" : "遠隔"}）`,
      d.note ? ` — ${d.note}` : ""))));
  }
  return h("div", {}, ...out);
}

// ---- the loop ---------------------------------------------------------------------

async function refresh() {
  try {
    const running = await drawApps();
    await drawApp(running);
  } catch (e) {
    document.getElementById("detail").replaceChildren(h("p", { class: "error" }, e.message));
  }
}

(async () => {
  session = await get("/api/session");
  drawWho();
  drawBox();
  await refresh();
  setInterval(refresh, 3000);
  setInterval(drawBox, 10000);
})();
