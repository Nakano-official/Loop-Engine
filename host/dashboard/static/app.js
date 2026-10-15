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
  running: ["実行中", "info"], done: ["完了", "ok"], partial: ["指定の段まで", "ok"], failed: ["戻り先あり", "bad"],
  stopped: ["停止", "warn"],
  interrupted: ["中断", "warn"],
};
const MODULE = {
  green: ["緑", "ok"], reused: ["使い回し（緑）", "ok"], trying: ["試行中", "info"], red: ["赤の関門", "info"],
  exhausted: ["使い切り", "bad"], engine: ["エンジン", "bad"],
};
function doing(now) {
  const m = now.module, n = now.n;
  switch (now.step) {
    case "start": return "通しを始めたところです";
    case "analyst": return `analyst が要求を分析して概念ファイルを書いています（${n} 回目）`;
    case "definer": return `definer が概念ファイルから、何を作るかを決めて定義を書いています（${n} 回目）`;
    case "tester": return `tester が定義の項目ごとに、確かめる例を書いています（${n} 回目）`;
    case "designer": return `designer が定義から設計を書いています（${n} 回目）`;
    case "red_gate": return `${m} のテストを用意して、スタブで赤になることを確かめています`;
    case "attempt": return `モデルが ${m} を実装しています（${n} 回目）`;
    case "reuse": return `${m} は前の設計で緑になった実装が使えるか、テストで確かめています`;
    case "build": return "アプリを1つの HTML にまとめて、起動を確かめています";
    default: return `${now.after || ""}${m ? `（${m}）` : ""} のあと、次の段へ進むところです`;
  }
}

// Elapsed time, counted on the page every second from a start time the server
// gave -- so the clock moves even between polls, and a pane that is not being
// redrawn still shows that time is passing.
function elapsed(since) {
  return h("span", { class: "elapsed", "data-since": String(since) }, fmt(Date.now() / 1000 - since));
}
function fmt(sec) {
  sec = Math.max(0, Math.floor(sec));
  const m = Math.floor(sec / 60), s = sec % 60;
  return m ? `${m}分${String(s).padStart(2, "0")}秒` : `${s}秒`;
}
setInterval(() => {
  for (const el of document.querySelectorAll(".elapsed")) {
    el.textContent = fmt(Date.now() / 1000 - Number(el.dataset.since));
  }
}, 1000);

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
        latest ? [" · ", chip(STATUS[latest.status] || [latest.status, "info"])] : ""),
      latest && latest.now ? h("div", { class: "sub live" }, h("span", { class: "dot" }), doing(latest.now)) : null);
  }));
  if (session.can_start) {
    nav.append(h("button", {
      class: selected.app === null && selected.creating ? "on" : "",
      onclick: () => { selected = { app: null, run: null, creating: true }; drawnFrom = ""; refresh(); },
    }, h("div", { class: "title" }, "＋ 新しいアプリ"), h("div", { class: "sub" }, "要求から作る")));
  }
  if (!data.apps.length) nav.append(h("p", { class: "muted" }, "アプリがまだありません。"));
  return data.running;
}

// ---- one app ----------------------------------------------------------------------

function drawCreate() {
  const box = document.getElementById("detail");
  if (drawnFrom === "create") return;           // never redraw over what is being typed
  drawnFrom = "create";
  const name = h("input", { placeholder: "idlegame2（小文字・数字・- _）", pattern: "[a-z0-9][a-z0-9_-]*" });
  const title = h("input", { placeholder: "放置ゲーム" });
  const req = h("textarea", { class: "req", placeholder: "作りたいアプリの要求を書きます。箇条書きで、できること・画面に出すもの・保存など。" });
  const PLATFORM_LABEL = { "browser-dom": "画面（ボタンと文字）", "browser-3d": "3D（歩いて見回す）" };
  const platform = h("select", {}, ...(session.platforms || ["browser-dom"]).map((p) =>
    h("option", { value: p }, `${PLATFORM_LABEL[p] || p} — ${p}`)));
  const msg = h("p", { class: "note" });
  box.replaceChildren(
    h("h2", {}, "新しいアプリ"),
    h("p", { class: "muted" }, "要求から、definer が定義を、designer が設計を書き、ローカルのモデルが実装して、開けば動く1つの HTML を出します。"),
    h("label", {}, "名前", name), h("label", {}, "題名", title), h("label", {}, "形", platform),
    h("label", {}, "要求", req),
    h("div", { class: "row" }, h("button", {
      class: "act primary",
      onclick: async () => {
        try {
          const made = await post("/api/apps", { name: name.value.trim(), title: title.value.trim(), platform: platform.value, requirements: req.value });
          selected = { app: made.name, run: null };
          drawnFrom = "";
          refresh();
        } catch (e) { msg.textContent = e.message; }
      },
    }, "作る"), msg));
}


// ---- pictures -----------------------------------------------------------------------
//
// Every picture is built here, by the machine, from the run's records -- never
// by a model -- as Mermaid source, and drawn in a sandboxed frame of its own
// (diagram.html): the labels are text a model wrote, so the drawing happens
// where it can reach nothing.

function diagramFrame(title, onselect) {
  const f = h("iframe", { class: "diagram", sandbox: "allow-scripts", src: "/diagram.html", title });
  f._ready = false;
  f._want = null;
  f._onselect = onselect || null;
  return f;
}

function drawIn(frame, source, nodes = {}) {
  frame._want = { source, nodes };
  if (frame._ready && frame.contentWindow) {
    frame.contentWindow.postMessage({ loop: true, kind: "draw", source, nodes }, "*");
  }
}

addEventListener("message", (e) => {
  const frame = [...document.querySelectorAll("iframe.diagram")].find((f) => f.contentWindow === e.source);
  const m = e.data;
  if (!frame || !m || m.loop !== true) return;
  if (m.kind === "ready") {
    frame._ready = true;
    if (frame._want) drawIn(frame, frame._want.source, frame._want.nodes);
  } else if (m.kind === "size" && Number.isFinite(m.height)) {
    frame.style.height = `${Math.min(Math.max(m.height, 60), 2400)}px`;
  } else if (m.kind === "select" && typeof m.key === "string" && frame._onselect) {
    frame._onselect(m.key);
  }
});

// Text into a Mermaid label or message: no quotes, brackets or statement
// separators survive as syntax.
const esc = (s) => String(s ?? "").replace(/[\r\n]+/g, " ").replace(/"/g, "#quot;").replace(/</g, "#lt;")
  .replace(/>/g, "#gt;").replace(/;/g, "；").replace(/`/g, "'").slice(0, 200);

// ---- the flow: one card per stage ---------------------------------------------------
//
// The stages never change, so they are drawn here as they are -- in HTML, with
// textContent, no picture library -- and only their state comes from the run:
// what is done, what is running now and for how long, what each produced, and
// where the run went back.

const STAGES = [
  { id: "req", name: "要求", who: "人が書く" },
  { id: "ana", name: "分析", who: "analyst（Claude・箱）", step: "analyst", fault: "要求分析" },
  { id: "def", name: "定義", who: "definer（Claude・箱）", step: "definer", fault: "要件定義" },
  { id: "ex", name: "例", who: "tester（Claude・箱）", step: "tester", fault: "定義の例" },
  { id: "des", name: "設計", who: "designer（Claude・箱）", step: "designer", fault: "モジュール設計" },
  { id: "imp", name: "実装", who: "solver（9B）と exec・箱", fault: "実装" },
  { id: "out", name: "出力", who: "build-app と起動確認・箱" },
];
const STAGE_STATE = {
  done: "済み", now: "いま", wait: "待ち", skip: "使わない", bad: "ここで止まった", held: "指定で止めた",
};
const JUMP = { ana: "sec-upstream", def: "sec-upstream", ex: "sec-upstream", des: "sec-upstream", imp: "sec-modules", out: "sec-out" };

const sum = (xs) => xs.reduce((a, b) => a + (b || 0), 0);
const kTokens = (n) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n));
// Tokens a set of Claude rounds used, from the usage each round put on the
// ledger. "in" counts everything the model read: new input, and the cache it
// read from or wrote. The local 9B spends no quota and is not in it.
function usageOf(steps) {
  const u = { out: 0, in: 0, cached: 0, usd: 0, rounds: 0 };
  for (const s of steps) {
    if (!s.usage) continue;
    u.rounds += 1;
    u.out += s.usage.output_tokens || 0;
    u.cached += s.usage.cache_read_input_tokens || 0;
    u.in += (s.usage.input_tokens || 0) + (s.usage.cache_read_input_tokens || 0) + (s.usage.cache_creation_input_tokens || 0);
    u.usd += s.usage.total_cost_usd || 0;
  }
  return u;
}
const usageText = (u) => `出力 ${kTokens(u.out)}・入力 ${kTokens(u.in)}（うちキャッシュ読み ${kTokens(u.cached)}）`
  + (u.usd ? `・API 換算 $${u.usd.toFixed(2)}` : "");

const QUIET_WARN = 90;           // seconds without a word from the agent before it is called quiet

// A Claude role at work, from its trace (the window's progress): thinking,
// writing, or silent. Thinking sends a word every few seconds; a long silence
// is what an agent that stopped answering looks like.
function liveLines(live) {
  if (!live) return { lines: [], badges: [] };
  if (live.error) return { lines: [], badges: [`経過を読めない: ${live.error}`] };
  if (!live.running) return { lines: [], badges: [] };
  const lines = [], badges = [];
  const last = live.tools && live.tools.length ? live.tools[live.tools.length - 1] : null;
  lines.push(`考えた量 約 ${kTokens(live.thinking_tokens || 0)} トークン（この手番）`);
  if (last) lines.push(`直近の道具: ${last.name}${last.file ? ` ${last.file}` : ""}（計 ${live.tool_count} 回）`);
  const quiet = Math.round(live.quiet_seconds || 0);
  if (quiet >= QUIET_WARN) badges.push(`応答なし ${quiet} 秒 ⚠`);
  else lines.push(`最後の経過 ${quiet} 秒前`);
  // A failed tool call (a Read of a file that is not there yet) is the agent's
  // own business and it carries on: a quiet note. An API retry or error can
  // stop a role: a warning.
  if (live.tool_errors) lines.push(`道具の失敗 ${live.tool_errors} 件（ファイルが無い、など。役はそのまま続ける）`);
  if (live.api_errors) badges.push(`API のエラー・再試行 ${live.api_errors} 件 ⚠`);
  if (live.rate_limit && live.rate_limit !== "allowed") badges.push(`利用枠: ${live.rate_limit}`);
  return { lines, badges };
}

// How much of its file a role has written so far (the window's progress reads
// the file as it grows; the roles write in parts).
function draftText(step, d) {
  const t = {
    analyst: () => `書きかけ: 概念 ${d.concepts}・性質 ${d.properties}・必要なこと ${d.requirements}`,
    definer: () => `書きかけ: 項目 ${d.written} / ${d.items} を記入`,
    tester: () => `書きかけ: 例 ${d.examples}（項目 ${d.with_examples} / ${d.items}）`,
    designer: () => `書きかけ: モジュール ${d.written} / ${d.modules} を記入・例 ${d.examples}`,
  }[step];
  return t ? t() + (d.stale ? "（書き換えの途中）" : "") : null;
}

function stageFacts(run) {
  const step = run.now ? run.now.step : null;
  const ended = run.status !== "running";
  const fromRequirements = Boolean(run.has_concepts)
    || run.steps.some((s) => ["analyst", "definer", "tester"].includes(s.step))
    || ["analyst", "definer", "tester"].includes(step);
  const until = run.ledger.find((e) => e.event === "UNTIL");
  const heldAfter = until ? { analysis: "ana", definition: "ex", design: "des" }[until.stage] : null;
  const order = STAGES.map((s) => s.id);
  const p = run.products || {};
  const facts = { req: { state: "done", lines: [] } };

  for (const st of STAGES.filter((s) => s.step)) {
    const rounds = run.steps.filter((s) => s.step === st.step);
    const f = { state: "wait", lines: [], badges: [], seconds: sum(rounds.map((r) => r.seconds)) };
    const last = rounds[rounds.length - 1];
    if (!fromRequirements) f.state = "skip";
    else if (step === st.step) {
      f.state = "now";
      f.since = run.now.since;
      f.lines.push(`${run.now.n} 回目`);
      const live = liveLines(run.live);
      f.lines.push(...live.lines);
      f.badges.push(...live.badges);
      const draft = run.live && run.live.draft ? draftText(st.step, run.live.draft) : null;
      if (draft) f.lines.push(draft);
    } else if (last && !(last.findings || []).length) f.state = "done";
    else if (last && ended) f.state = "bad";
    else if (last) f.state = "now";
    const used = usageOf(rounds);
    if (used.rounds) f.lines.push(`トークン: 出力 ${kTokens(used.out)}・入力 ${kTokens(used.in)}`);
    const refused = rounds.filter((r) => (r.findings || []).length).length;
    if (refused) f.badges.push(`関門の指摘で書き直し ${refused} 回`);
    if (st.id === "ana" && p.analysis) {
      f.lines.push(`概念 ${p.analysis.concepts}・性質 ${p.analysis.properties}（例で確かめる ${p.analysis.by_example}）`,
        `必要なこと ${p.analysis.requirements}`);
    }
    if (st.id === "def" && p.definition) f.lines.push(`項目 ${p.definition.items}`);
    if (st.id === "ex" && p.definition) {
      const j = p.definition.judged || {};
      f.lines.push(`例 ${p.definition.examples}`);
      if (p.definition.examples) {
        f.lines.push(`値 ${j.equals || 0}・一部 ${j.matches || 0}・条件 ${j.holds || 0}・エラー ${j.raises || 0}`);
      }
    }
    if (st.id === "des") {
      if (p.design) f.lines.push(`モジュール ${p.design.modules}`);
      const back = (run.upstream || []).filter((e) => e.event === "BACK_TO_DESIGN").length;
      if (back) f.badges.push(`実装から設計へ戻った ${back} 回`);
    }
    facts[st.id] = f;
  }

  // The modules: green out of all, the one being worked on, the retries.
  const total = p.design ? p.design.modules : null;
  const green = run.modules.filter((m) => m.state === "green" || m.state === "reused").length;
  const work = run.steps.filter((s) => s.step === "attempt" || s.step === "red_gate");
  const imp = { state: "wait", lines: [], badges: [], seconds: sum(work.map((s) => s.seconds)) };
  if (step === "attempt" || step === "red_gate") {
    imp.state = "now";
    imp.since = run.now.since;
    imp.lines.push(step === "attempt" ? `いま ${run.now.module} の ${run.now.n} 回目` : `いま ${run.now.module} のテストを準備`);
  } else if (total && green === total) imp.state = "done";
  else if (run.modules.length && ended) imp.state = "bad";
  else if (run.modules.length) imp.state = "now";
  if (total != null || run.modules.length) imp.lines.unshift(`緑 ${green}${total != null ? ` / ${total}` : ""}`);
  const retries = sum(run.modules.map((m) => Math.max((m.attempts || 0) - 1, 0)));
  if (retries) imp.badges.push(`やり直し ${retries} 回`);
  facts.imp = imp;

  const out = { state: "wait", lines: [], badges: [] };
  if (step === "build") {
    out.state = "now";
    out.since = run.now.since;
    out.lines.push("束ねて、起動を確かめています");
  } else if (run.output) {
    out.state = "done";
    out.lines.push("app.html・起動確認 ✓");
  } else if (ended && run.ledger.some((e) => e.event === "OUTPUT_FAILED")) {
    out.state = "bad";
    out.lines.push("起動確認で落ちた");
  }
  facts.out = out;

  // A run that started at the design, from what an earlier run left: those
  // stages are done, by that run.
  const from = run.ledger.find((e) => e.event === "FROM" && e.stages);
  if (from) {
    const ids = { analysis: "ana", definition: "def", examples: "ex" };
    for (const stage of from.stages) {
      const f = facts[ids[stage]];
      if (f && f.state !== "now") { f.state = "done"; f.lines.unshift(`前の通し ${from.run} のものを使う`); }
    }
  }

  // A run told to stop after a stage: what comes after it was never meant to run.
  if (heldAfter) for (const id of order.slice(order.indexOf(heldAfter) + 1)) facts[id].state = "held";
  // A run that ended by going back somewhere: that stage is where it stopped.
  if (run.status === "failed") {
    const at = STAGES.find((s) => s.fault === run.stage);
    if (at) facts[at.id].state = "bad";
  }
  return facts;
}

function stageCards(run) {
  const facts = stageFacts(run);
  const cards = [];
  STAGES.forEach((st, i) => {
    const f = facts[st.id];
    if (i) cards.push(h("span", { class: "stage-arrow", "aria-hidden": "true" }, "→"));
    const time = f.state === "now" && f.since ? elapsed(f.since) : f.seconds ? fmt(f.seconds) : null;
    cards.push(h("button", {
      class: `stage ${f.state}`, title: `${st.name}: ${STAGE_STATE[f.state]}`,
      onclick: () => {
        const el = JUMP[st.id] && document.getElementById(JUMP[st.id]);
        if (el) el.scrollIntoView({ behavior: "smooth" });
      },
    },
      h("div", { class: "stage-top" }, h("span", { class: "stage-name" }, st.name),
        h("span", { class: "stage-state" }, f.state === "now" ? h("span", { class: "dot" }) : null, STAGE_STATE[f.state])),
      h("div", { class: "stage-who" }, st.who),
      ...f.lines.map((l) => h("div", { class: "stage-line" }, l)),
      ...(f.badges || []).map((b) => h("div", { class: "stage-badge" }, b)),
      time ? h("div", { class: "stage-time" }, time) : null));
  });
  return h("div", { class: "stages" }, ...cards);
}

// ---- the outer loop: the rounds, on one rail ------------------------------------
//
// The rounds are fixed too (DESIGN 6): the MVP, then one round per topic in a
// fixed order, then a person looks. Only the rail is shown; a round opens to
// the stages inside it. A round of the definition goes evaluation -> improvement
// file -> the definition as it now stands -> design -> implementation -> output;
// the round of the design (maintainability) goes from the reviewer's note to a
// new design. The outer loop is not built yet: until it is, the first round is
// this run and the others show what they will run.

const ROUNDS = [
  { id: "r1", mark: "1", name: "1周目", sub: "MVP", kind: "要求から一通り" },
  { id: "t1", mark: "①", name: "機能適合性", kind: "定義の周" },
  { id: "t2", mark: "②", name: "信頼性", kind: "定義の周" },
  { id: "t3", mark: "③", name: "保守性", kind: "設計の周" },
  { id: "t4", mark: "④", name: "インタラクション能力", kind: "定義の周" },
  { id: "t5", mark: "⑤", name: "性能効率性", kind: "定義の周" },
  { id: "end", mark: "✓", name: "一通り完成", kind: "人が見る" },
];
const ROUND_STAGES = {
  "定義の周": [["評価", "評価役（critic・箱）"], ["改良ファイル", "レビュアー（definer・箱）"], ["今の定義", "機械が重ねる"],
    ["設計", "designer（Claude・箱）"], ["実装", "solver（9B）と exec・箱"], ["出力", "build-app と起動確認・箱"]],
  "設計の周": [["指摘", "レビュアー（definer・箱）"], ["設計", "designer（Claude・箱）"], ["実装", "solver（9B）と exec・箱"],
    ["出力", "build-app と起動確認・箱"]],
  "人が見る": [["実物を見る", "人"]],
};
const RUN_ROUND_STATE = { running: "now", done: "done", partial: "held", failed: "bad", stopped: "bad", interrupted: "bad" };
const ROUND_LABEL = { now: "いま", done: "済み", held: "指定で止めた", bad: "止まった", todo: "未着手" };

function openRound() {
  try { return localStorage.getItem("loop:round") || ""; } catch { return ""; }
}
function setOpenRound(id) {
  try { localStorage.setItem("loop:round", id); } catch { /* private mode: only for this page */ }
  view.round = id;
}

function roundTrack(run) {
  const open = view.round ?? openRound();
  const states = ROUNDS.map((r) => (r.id === "r1" ? RUN_ROUND_STATE[run.status] || "todo" : "todo"));
  // How far the rail is filled: up to the last round done, half into the one running.
  const doneUpTo = states.lastIndexOf("done");
  const nowAt = states.indexOf("now");
  const reach = nowAt >= 0 ? nowAt : Math.max(doneUpTo, 0);
  const fill = ROUNDS.length > 1 ? (reach / (ROUNDS.length - 1)) * 100 : 0;

  const nodes = ROUNDS.map((r, i) => h("button", {
    class: `round ${states[i]}${open === r.id ? " open" : ""}`,
    title: `${r.name}（${r.kind}）: ${ROUND_LABEL[states[i]]}`,
    onclick: () => {
      setOpenRound(open === r.id ? "" : r.id);
      view.justOpened = open !== r.id;
      view.sig.flow = null;
      refresh();
    },
  },
    h("span", { class: "knob" }, states[i] === "done" ? "✓" : r.mark),
    h("span", { class: "round-name" }, r.name),
    h("span", { class: "round-kind" }, r.sub ? `${r.sub} · ${r.kind}` : r.kind),
    h("span", { class: "round-state" }, ROUND_LABEL[states[i]])));

  const rail = h("div", { class: "rail", style: `--fill: ${fill}%; --flow-at: ${nowAt >= 0 ? fill : -1}%` },
    h("div", { class: "rail-line" }), h("div", { class: "rail-fill" }),
    nowAt >= 0 ? h("div", { class: "rail-flow" }) : null,
    h("div", { class: "rail-nodes" }, ...nodes));

  const out = [rail];
  const at = ROUNDS.findIndex((r) => r.id === open);
  if (at >= 0) {
    const r = ROUNDS[at];
    const panel = h("div", {
      class: `round-panel${view.justOpened ? " opening" : ""}`,
      style: `--at: ${((at + 0.5) / ROUNDS.length) * 100}%`,
    },
      h("div", { class: "round-panel-head" }, h("span", { class: "round-tag" }, r.id === "r1" ? r.name : `${r.mark} ${r.name}`),
        h("span", { class: "note" }, r.kind)),
      r.id === "r1" ? stageCards(run) : plannedStages(r));
    out.push(panel);
  }
  view.justOpened = false;
  return h("div", { class: "rounds" }, ...out);
}

// A round the outer loop has not run yet: the stages it will go through, idle.
function plannedStages(r) {
  const stages = ROUND_STAGES[r.kind] || [];
  const cards = [];
  stages.forEach(([name, who], i) => {
    if (i) cards.push(h("span", { class: "stage-arrow", "aria-hidden": "true" }, "→"));
    cards.push(h("div", { class: "stage skip" },
      h("div", { class: "stage-top" }, h("span", { class: "stage-name" }, name), h("span", { class: "stage-state" }, "未着手")),
      h("div", { class: "stage-who" }, who)));
  });
  return h("div", {},
    h("div", { class: "stages" }, ...cards),
    h("p", { class: "note" }, "外側の輪はまだ動いていません。評価役と改良ファイルができると、この周の流れがここに出ます。"));
}

const MODULE_TEXT = {
  green: (m) => `緑（${m.attempts} 回目）`, reused: () => "使い回し（緑）", trying: (m) => `試行中（${m.attempts} 回目）`, red: () => "赤の関門",
  exhausted: () => "使い切り", engine: () => "エンジン",
};

// 2. The design: its modules, what each needs, and how far each has got.
// The design being written, before its gate: the designer's file as far as
// it has got. Shown while the designer writes -- the first design, or the
// next one after the implementation sent the loop back.
function draftDesign(run) {
  const d = run.now && run.now.step === "designer" && run.live && run.live.draft;
  return d && d.design && d.design.modules.length ? d.design : null;
}

function mapSource(run, design = run.design) {
  const mods = design.modules;
  const drafting = design !== run.design;
  const ids = new Map(mods.map((m, i) => [m.name, `m${i}`]));
  const state = new Map(run.modules.map((m) => [m.module, m]));
  const lines = ["flowchart TD"];
  const nodes = {};
  for (const m of mods) {
    const id = ids.get(m.name);
    nodes[id] = m.name;
    const s = drafting ? null : state.get(m.name);
    const text = drafting ? (m.functions.length ? `書いた（例 ${m.examples}）` : "まだ")
      : s ? (MODULE_TEXT[s.state] || (() => s.state))(s) : "待ち";
    const label = `${esc(m.name)}${m.assembly ? "（組み立て）" : ""}<br/>${text}`;
    lines.push(m.assembly ? `  ${id}[["${label}"]]` : `  ${id}["${label}"]`);
    lines.push(`  class ${id} ${s ? s.state : drafting && m.functions.length ? "drafted" : "wait"}`);
  }
  if (drafting) lines.push('  note["書きかけの設計（関門の前）"]', "  class note wait");
  for (const m of mods) {
    for (const dep of m.depends_on) if (ids.has(dep)) lines.push(`  ${ids.get(dep)} --> ${ids.get(m.name)}`);
  }
  lines.push(
    "  classDef green fill:#e3f3e6,stroke:#1a7f37,color:#14532d",
    "  classDef reused fill:#e3f3e6,stroke:#1a7f37,color:#14532d,stroke-dasharray:4 3",
    "  classDef trying fill:#2457c5,stroke:#2457c5,color:#fff",
    "  classDef red fill:#e8eefc,stroke:#2457c5,color:#1e3a8a",
    "  classDef exhausted fill:#fde7e7,stroke:#c62828,color:#7f1d1d",
    "  classDef engine fill:#fde7e7,stroke:#c62828,color:#7f1d1d",
    "  classDef wait fill:none,stroke:#999,color:#777",
    "  classDef drafted fill:none,stroke:#2457c5,color:#1e3a8a,stroke-dasharray:4 3");
  return { source: lines.join("\n"), nodes };
}

// 3. One module's story: the tests against its stub, then every attempt --
//    what went to the solver, what came back, what the checks said.
function sequenceSource(run, name) {
  const steps = run.steps.filter((s) => s.module === name);
  const lines = ["sequenceDiagram",
    "  participant P as pipeline（ホスト）", "  participant W as 窓口（runner）",
    "  participant S as solver（9B）", "  participant E as exec"];
  const secs = (s) => (s.seconds != null ? `（${s.seconds} 秒）` : "");
  for (const s of steps) {
    if (s.step === "red_gate") {
      lines.push("  P->>W: prepare-tests：設計の例からテストとスタブを生成",
        "  W->>E: スタブに対してテストを走らせる",
        `  E-->>P: ${s.stage === "red" ? "赤（関門を通った）" : "エンジンの誤り"}${secs(s)}`);
      continue;
    }
    if (s.step !== "attempt") continue;
    const code = s.files.find((f) => /\.(ts|py)$/.test(f));
    lines.push(`  P->>W: attempt ${s.n} 回目：ブリーフ`);
    if (s.files.includes("brief.md")) lines.push("  W->>S: ブリーフ", `  S-->>W: 候補 ${esc(code || "")}`);
    const refused = [...(s.forbidden || []), ...(s.undeclared || [])];
    lines.push(`  W->>W: 参照の検査${refused.length ? `：棄却 ${esc(refused.join(", "))}` : "：通過"}`);
    if (!refused.length) lines.push("  W->>E: このモジュールと緑のモジュールのテスト");
    const result = s.stage === "green" ? "緑"
      : refused.length ? "実装へ戻す（使ってはいけないもの）"
      : `赤 ${esc([...(s.failed || []), ...(s.broke || [])].join(", "))}`;
    lines.push(`  ${refused.length ? "W" : "E"}-->>P: ${result}${secs(s)}`);
    if (s.stage !== "green") lines.push("  Note over P: 落ちた例と指摘を次の試行へ渡す");
  }
  if (!steps.length) lines.push("  Note over P: まだ始まっていません");
  return lines.join("\n");
}

// ---- files the ledger points at -------------------------------------------------------

const FILE_LABEL = {
  "brief.md": "ブリーフ（渡した指示）", "records.json": "例ごとの結果", "feedback.txt": "次の試行へ渡した指摘",
  "solver.log": "solver のログ", "output.txt": "テストや役の出力", "concepts.json": "書いた概念ファイル",
  "definition.json": "書いた定義",
  "design.json": "書いた設計",
};

function fileUrl(app, run, rel) {
  return `/api/apps/${encodeURIComponent(app.name)}/runs/${encodeURIComponent(run.id)}/file?path=${encodeURIComponent(rel)}`;
}

// A file, opened only when asked for: <details> fetches it the first time.
function lazy(label, load) {
  const body = h("div", { class: "file" }, h("span", { class: "note" }, "読み込み中…"));
  const d = h("details", { class: "lazy" }, h("summary", {}, label), body);
  d.addEventListener("toggle", async () => {
    if (!d.open || d._loaded) return;
    d._loaded = true;
    try { body.replaceChildren(await load()); }
    catch (e) { body.replaceChildren(h("p", { class: "error" }, e.message)); }
  });
  return d;
}

const text = (t) => h("pre", { class: "code" }, t);

function recordsTable(raw) {
  const checks = JSON.parse(raw).filter((r) => r.t === "check");
  const started = JSON.parse(raw).filter((r) => r.t === "start").map((r) => r.id);
  const crashed = started.filter((id) => !checks.some((c) => c.id === id));
  if (!checks.length && !crashed.length) return h("p", { class: "note" }, "テストは走っていません（棄却されたか、組み立てられなかった）。");
  const show = (v) => (typeof v === "string" ? v : JSON.stringify(v));
  return h("table", { class: "records" },
    h("tr", {}, h("th", {}, "例"), h("th", {}, "結果"), h("th", {}, "期待値"), h("th", {}, "実際の値")),
    ...checks.map((c) => h("tr", { class: c.ok ? "" : "bad-row" },
      h("td", {}, c.id), h("td", {}, chip(c.ok ? ["一致", "ok"] : ["不一致", "bad"])),
      h("td", {}, h("code", {}, show(c.expected))), h("td", {}, h("code", {}, show(c.actual))))),
    ...crashed.map((id) => h("tr", { class: "bad-row" }, h("td", {}, id), h("td", {}, chip(["比べる前に例外", "bad"])),
      h("td", {}), h("td", {}))));
}

// Line diff (longest common subsequence). The files are one module each.
function diffLines(a, b) {
  const x = a.split("\n"), y = b.split("\n");
  if (x.length * y.length > 4_000_000) return h("p", { class: "note" }, "大きすぎて差分を出せません。");
  const L = Array.from({ length: x.length + 1 }, () => new Uint32Array(y.length + 1));
  for (let i = x.length - 1; i >= 0; i--) {
    for (let j = y.length - 1; j >= 0; j--) {
      L[i][j] = x[i] === y[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    }
  }
  const out = [];
  let i = 0, j = 0;
  while (i < x.length || j < y.length) {
    if (i < x.length && j < y.length && x[i] === y[j]) { out.push(h("span", { class: "same" }, `  ${x[i]}\n`)); i++; j++; }
    else if (j < y.length && (i >= x.length || L[i][j + 1] >= L[i + 1][j])) { out.push(h("span", { class: "add" }, `+ ${y[j]}\n`)); j++; }
    else { out.push(h("span", { class: "del" }, `- ${x[i]}\n`)); i++; }
  }
  return h("pre", { class: "code diff" }, ...out);
}

function fileViews(app, run, step, previous) {
  const get1 = async (rel) => (await get(fileUrl(app, run, rel))).text;
  const views = [];
  const code = step.files.find((f) => /\.(ts|py)$/.test(f));
  const order = ["brief.md", code, "records.json", "feedback.txt", "concepts.json", "definition.json", "design.json",
    "solver.log", "output.txt"];
  for (const f of order) {
    if (!f || !step.files.includes(f)) continue;
    const rel = `${step.dir}/${f}`;
    if (f === code) {
      views.push(lazy(`書いたコード（${f}）`, async () => text(await get1(rel))));
      const before = previous && previous.files.find((g) => /\.(ts|py)$/.test(g));
      if (before) {
        views.push(lazy(`前の試行（${previous.n} 回目）との差分`, async () =>
          diffLines(await get1(`${previous.dir}/${before}`), await get1(rel))));
      }
    } else if (f === "records.json") {
      views.push(lazy(FILE_LABEL[f], async () => recordsTable(await get1(rel))));
    } else {
      // output.txt is what a Claude role printed, or what the test framework did.
      const label = f === "output.txt" ? (["analyst", "definer", "tester", "designer"].includes(step.step) ? "役の出力" : "テストの出力")
        : FILE_LABEL[f] || f;
      views.push(lazy(label, async () => text(await get1(rel))));
    }
  }
  return views.length ? h("div", { class: "files" }, ...views) : h("p", { class: "note" }, "この回の記録はありません（記録を残す前の通しです）。");
}

// ---- one app ----------------------------------------------------------------------

function appParts(app, running, shown) {
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
      class: `pick ${r.id === shown ? "on" : ""}`,
      // The newest run is followed: picking it means "always the newest".
      // Picking an older one keeps the page on it.
      onclick: () => { selected.run = r.id === app.runs[0].id ? null : r.id; refresh(); },
    },
      h("td", {}, r.id),
      h("td", {}, chip(STATUS[r.status] || [r.status, "info"])),
      h("td", {}, r.reason || ""),
      h("td", {}, decisionChip(r.decision) || ""))));
  return [
    h("h2", {}, app.title, h("span", { class: "muted" }, `  ${app.name}`)),
    app.requirements ? h("details", {}, h("summary", {}, "要求"), h("pre", { class: "req" }, app.requirements)) : null,
    h("div", { class: "row" }, start,
      busy ? h("span", { class: "note" }, `実行中の通しがあります（${running.app}）。同時に1つだけです。`) : null,
      !session.can_start ? h("span", { class: "note" }, "通しはこの PC から始めます。") : null),
    h("h3", {}, "通し", app.runs.length ? h("span", { class: "note" }, selected.run
      ? "  選んだ通しを表示しています（一番上を押すと、最新の通しを追いかける表示に戻ります）"
      : "  最新の通しを追いかけて表示しています") : null),
    app.runs.length ? runs : h("p", { class: "muted" }, "まだ通していません。"),
  ];
}

function headParts(app, run) {
  const now = run.now ? h("div", { class: "now" },
    h("div", { class: "row" }, h("span", { class: "dot" }), h("strong", {}, "いま"), doing(run.now)),
    run.live ? h("div", { class: "row note" }, liveLines(run.live).lines.join(" ・ "),
      ...liveLines(run.live).badges.map((b) => h("span", { class: "chip warn" }, b))) : null,
    h("div", { class: "row note" },
      "この段の経過 ", elapsed(run.now.since), " ・ 通しの開始から ", elapsed(run.started),
      " ・ プロセスは動いています（止まれば「中断」と出ます）")) : null;
  const total = usageOf(run.steps);
  const spent = total.rounds ? h("p", { class: "note" }, `この通しで Claude の役が使ったトークン（${total.rounds} 回分）: `,
    usageText(total), run.status === "running" && run.live && run.live.running ? " ＋ いま動いている役の分" : "") : null;
  return [h("h3", {}, `通し ${run.id}`), now, spent,
    h("div", { class: "row" }, chip(STATUS[run.status] || [run.status, "info"]),
      run.stage ? h("span", {}, `戻り先・結果: ${run.stage}`) : null,
      run.status === "running" ? h("button", {
        class: "act danger",
        onclick: async () => { try { await post("/api/runs/stop", { app: app.name, run: run.id }); refresh(); }
                               catch (e) { alert(e.message); } },
      }, "止める") : null),
    run.reason ? h("p", {}, run.reason) : null];
}

function drawInspector(app, run, name) {
  const mod = run.design ? run.design.modules.find((m) => m.name === name) : null;
  const attempts = run.steps.filter((s) => s.module === name && s.step === "attempt");
  const seq = diagramFrame(`${name} の試行`);
  drawIn(seq, sequenceSource(run, name));
  const state = run.modules.find((m) => m.module === name);
  return h("div", { class: "inspector" },
    h("div", { class: "row" }, h("h3", {}, `モジュール ${name}`),
      state ? chip(MODULE[state.state] || [state.state, "info"]) : chip(["待ち", "info"]),
      h("button", { class: "act", onclick: () => { selected.module = null; refresh(); } }, "閉じる")),
    mod ? h("p", { class: "note" },
      `関数: ${mod.functions.join(", ") || "なし"}`,
      mod.depends_on.length ? ` ・ 依存: ${mod.depends_on.join(", ")}` : " ・ 依存なし") : null,
    mod ? lazy("設計に書かれたこのモジュール", async () => {
      const design = JSON.parse((await get(fileUrl(app, run, "design.json"))).text);
      return text(JSON.stringify(design.modules.find((m) => m.name === name), null, 1));
    }) : null,
    seq,
    attempts.length ? h("div", {}, ...attempts.map((s, i) => h("details", { class: "attempt" },
      h("summary", {}, `${s.n} 回目 `, chip(s.stage === "green" ? ["緑", "ok"] : [s.stage, "bad"]),
        s.seconds != null ? ` ${s.seconds} 秒 ` : " ", h("span", { class: "note" }, s.reason || "")),
      fileViews(app, run, s, attempts[i - 1])))) : h("p", { class: "note" }, "まだ試行していません。"));
}

const UPSTREAM = { ANALYST: "概念ファイル（analyst）", DEFINER: "定義（definer）", TESTER: "例（tester）", DESIGNER: "設計（designer）" };

function drawUpstream(app, run) {
  if (!run.upstream || !run.upstream.length) return null;
  const rows = run.upstream.map((e) => {
    if (e.event === "BACK_TO_DESIGN") {
      return h("li", {}, chip(["設計へ戻した", "warn"]),
        ` ${e.module}: ${e.reason || ""}`, e.examples && e.examples.length ? `（${e.examples.join(", ")}）` : "");
    }
    if (e.event === "DESIGN_ROUND") return h("li", {}, chip(["設計で実装へ", "info"]), ` ${e.round + 1} 回目の設計`);
    const ok = !e.findings || !e.findings.length;
    const step = e.dir ? run.steps.find((s) => s.dir === e.dir) : null;
    return h("li", {}, chip([UPSTREAM[e.event] || e.event, ok ? "ok" : "bad"]),
      ` ${e.n} 回目: `, ok ? "関門を通った" : `関門の指摘 ${e.findings.length} 件`,
      step && step.seconds != null ? h("span", { class: "note" }, `（${step.seconds} 秒）`) : null,
      ok ? null : h("ul", {}, ...e.findings.slice(0, 5).map((f) => h("li", { class: "note" }, f))),
      step ? fileViews(app, run, step, null) : null);
  });
  return h("div", { id: "sec-upstream" }, h("h3", {}, "上流"), h("ul", { class: "upstream" }, ...rows));
}

function restParts(app, run) {
  const modules = h("table", {},
    h("tr", {}, h("th", {}, "モジュール"), h("th", {}, "状態"), h("th", {}, "試行"), h("th", {}, "判定")),
    ...run.modules.map((m) => h("tr", {
      class: `pick ${m.module === selected.module ? "on" : ""}`,
      onclick: () => { selected.module = m.module; refresh(); },
    },
      h("td", {}, m.module),
      h("td", {}, chip(MODULE[m.state] || [m.state, "info"])),
      h("td", {}, String(m.attempts)),
      h("td", {}, m.reason || ""))));
  const docs = run.design ? h("div", { class: "files" },
    run.has_concepts ? lazy("この通しの概念ファイル（concepts.json）", async () =>
      text((await get(fileUrl(app, run, "concepts.json"))).text)) : null,
    lazy("この通しの定義（definition.json）", async () => text((await get(fileUrl(app, run, "definition.json"))).text)),
    lazy("この通しの設計（design.json）", async () => text((await get(fileUrl(app, run, "design.json"))).text))) : null;
  return [drawUpstream(app, run),
    run.modules.length ? h("h3", { id: "sec-modules" }, "モジュール", h("span", { class: "note" }, "  行を押すと、試行の中身を開きます")) : null,
    run.modules.length ? modules : null,
    docs ? h("h3", {}, "文書") : null, docs];
}

function outParts(app, run) {
  const out = [];
  if (run.output) {
    const src = `/play/${encodeURIComponent(app.name)}/${encodeURIComponent(run.id)}`;
    const note = h("textarea", { placeholder: "気づいたこと（差し戻しの理由など）" });
    const decide = (verdict) => async () => {
      try { await post("/api/decision", { app: app.name, run: run.id, verdict, note: note.value }); refresh(); }
      catch (e) { alert(e.message); }
    };
    out.push(
      h("h3", { id: "sec-out" }, "出力されたアプリ"),
      // sandbox="allow-scripts": runs, but with an opaque origin -- no access to
      // this page, its token, or its storage. The server's CSP says the same.
      h("iframe", { class: "play", src, sandbox: "allow-scripts", title: "出力されたアプリ" }),
      h("div", { class: "row" },
        h("a", { href: src, target: "_blank", rel: "noopener" }, "新しいタブで開く"),
        h("span", { class: "note" }, "ここでは保存（localStorage）は効きません。開いて動きを確かめるための表示です。")),
      h("h3", {}, "判断"),
      note,
      h("div", { class: "row" },
        h("button", { class: "act primary", disabled: !session.can_approve, onclick: decide("approve") }, "承認する"),
        h("button", { class: "act", onclick: decide("reject") }, "差し戻す"),
        !session.can_approve ? h("span", { class: "note" }, "承認はこの PC の前からだけです（実際に開いて確かめられる場所で決めるため）。") : null),
    );
  }
  if (run.decisions.length) {
    out.push(h("ul", {}, ...run.decisions.map((d) => h("li", {},
      decisionChip(d), ` ${new Date(d.t * 1000).toLocaleString()} ${d.user}（${d.scope === "local" ? "この PC" : "遠隔"}）`,
      d.note ? ` — ${d.note}` : ""))));
  }
  return out;
}

// The detail pane is in parts, each redrawn only when what it shows changed:
// redrawing a picture's frame would reload it, and redrawing the output would
// restart the app being tried.
let view = { run: null, frames: null, names: [], sig: {}, round: null, justOpened: false };

function skeleton(box) {
  if (box._parts) return box._parts;
  const p = { app: h("div"), head: h("div"), flow: h("div"), pics: h("div", { class: "pics" }), inspector: h("div"),
    rest: h("div"), out: h("div") };
  box.replaceChildren(p.app, p.head, p.flow, p.pics, p.inspector, p.rest, p.out);
  box._parts = p;
  view = { run: null, frames: null, names: [], sig: {}, round: view.round, justOpened: false };
  return p;
}

// replaceChildren would write a null out as the text "null".
const put = (el, parts) => el.replaceChildren(...parts.flat().filter((x) => x != null && x !== false));

function changed(key, value) {
  const j = JSON.stringify(value);
  if (view.sig[key] === j) return false;
  view.sig[key] = j;
  return true;
}

async function drawApp(running) {
  const box = document.getElementById("detail");
  if (selected.creating) { box._parts = null; drawCreate(); return; }
  if (!selected.app) return;
  drawnFrom = "";
  const app = await get(`/api/apps/${encodeURIComponent(selected.app)}`);
  // No run picked means the newest one, whichever that is now -- a run started
  // from the terminal or another device appears here without a reload.
  if (selected.run && !app.runs.some((r) => r.id === selected.run)) selected.run = null;
  const shown = selected.run || (app.runs.length ? app.runs[0].id : null);
  const run = shown
    ? await get(`/api/apps/${encodeURIComponent(app.name)}/runs/${encodeURIComponent(shown)}`) : null;
  const p = skeleton(box);
  if (changed("app", [app, running, selected.run, shown])) put(p.app, appParts(app, running, shown));
  if (!run) {
    for (const k of ["head", "flow", "pics", "inspector", "rest", "out"]) p[k].replaceChildren();
    view.run = null;
    return;
  }

  const key = `${app.name}/${run.id}`;
  if (view.run !== key) {
    if (view.run !== null) selected.module = null;     // another run: nothing is open in it yet
    view.run = key;
    view.sig = { app: view.sig.app };
    const map = diagramFrame("設計の依存図", (name) => {
      if (view.names.includes(name)) { selected.module = name; refresh(); }
    });
    view.frames = { map };
    p.pics.replaceChildren(
      h("h3", {}, "設計の依存図", h("span", { class: "note" }, "  モジュールを押すと、試行の中身を開きます")), map);
  }
  view.names = run.design ? run.design.modules.map((m) => m.name) : [];

  if (changed("head", [run.status, run.now, run.reason, run.stage, run.started, run.live, usageOf(run.steps)])) {
    put(p.head, headParts(app, run));
  }
  if (changed("flow", [run.status, run.stage, run.now, run.steps, run.modules, run.products, run.output, run.live,
    run.upstream, run.has_concepts, run.ledger.filter((e) => ["UNTIL", "OUTPUT_FAILED"].includes(e.event))])) {
    put(p.flow, [h("h3", {}, "ループ", h("span", { class: "note" }, "  周を押すと、その中の流れが開きます")), roundTrack(run)]);
  }
  const draft = draftDesign(run);
  if (run.design || draft) {
    const { source, nodes } = mapSource(run, draft || run.design);
    drawIn(view.frames.map, source, draft ? {} : nodes);
  } else {
    drawIn(view.frames.map, 'flowchart TD\n  w["設計はまだありません"]');
  }
  const mine = selected.module ? run.steps.filter((s) => s.module === selected.module) : null;
  if (changed("inspector", [selected.module, mine, run.modules.find((m) => m.module === selected.module)])) {
    p.inspector.replaceChildren(...(selected.module ? [drawInspector(app, run, selected.module)] : []));
  }
  if (changed("rest", [run.modules, run.upstream, run.steps.filter((s) => s.step !== "attempt").map((s) => s.files),
    Boolean(run.design), selected.module])) {
    put(p.rest, restParts(app, run));
  }
  if (changed("out", [run.output, run.decisions, session.can_approve])) put(p.out, outParts(app, run));
}

// ---- the loop ---------------------------------------------------------------------

// What is open is in the address (#app=…&run=…&module=…), so a link opens the
// same place -- and reloading keeps it.
function fromAddress() {
  const q = new URLSearchParams(location.hash.slice(1));
  if (q.get("app")) selected = { app: q.get("app"), run: q.get("run") || null, module: q.get("module") || null };
  if (q.has("round")) setOpenRound(q.get("round"));
}
function toAddress() {
  const q = new URLSearchParams();
  for (const k of ["app", "run", "module"]) if (selected[k]) q.set(k, selected[k]);
  if (view.round) q.set("round", view.round);
  const hash = q.toString() ? `#${q}` : "";
  if (location.hash !== hash) history.replaceState(null, "", hash || location.pathname);
}

async function refresh() {
  try {
    const running = await drawApps();
    await drawApp(running);
    toAddress();
  } catch (e) {
    const box = document.getElementById("detail");
    box._parts = null;
    box.replaceChildren(h("p", { class: "error" }, e.message));
  }
}

(async () => {
  session = await get("/api/session");
  fromAddress();
  drawWho();
  drawBox();
  await refresh();
  setInterval(refresh, 3000);
  setInterval(drawBox, 10000);
})();
