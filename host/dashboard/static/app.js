let session;

async function api(path, options = {}) {
  const headers = {"Content-Type": "application/json", ...(options.headers || {})};
  if (options.method === "POST") headers["X-Loop-Token"] = session.token;
  const response = await fetch(path, {...options, headers, cache: "no-store"});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
  return value;
}

function button(label, decision, item, note) {
  const element = document.createElement("button");
  element.textContent = label;
  element.onclick = async () => {
    element.disabled = true;
    try {
      await api("/api/decision", {method: "POST", body: JSON.stringify({kind: item.kind, request_id: item.id, decision, note: note.value})});
      await refresh();
    } catch (error) { alert(error.message); element.disabled = false; }
  };
  return element;
}

async function refresh() {
  const state = await api("/api/state");
  document.querySelector("#project").textContent = state.project;
  document.querySelector("#phase").textContent = state.phase;
  document.querySelector("#progress").textContent = `${state.steps.green} / ${state.steps.total}`;
  document.querySelector("#last-event").textContent = state.last_event?.event || "—";
  const pending = document.querySelector("#pending"); pending.replaceChildren();
  if (!state.pending.length) pending.textContent = "現在、人間の対応を待っている項目はありません。";
  for (const item of state.pending) {
    const card = document.querySelector("#request-template").content.cloneNode(true);
    card.querySelector(".badge").textContent = item.kind === "review" ? "予定レビュー" : "エスカレーション";
    card.querySelector("h3").textContent = item.title;
    card.querySelector("pre").textContent = item.detail;
    const note = card.querySelector("textarea"), actions = card.querySelector(".request-actions");
    if (item.kind === "review") {
      actions.append(button("承認", "approve", item, note), button("修正を依頼", "revise", item, note));
    } else {
      actions.append(button("回答を記録", "respond", item, note), button("停止", "stop", item, note));
    }
    pending.append(card);
  }
  const events = document.querySelector("#events"); events.replaceChildren();
  for (const event of [...state.recent_events].reverse()) {
    const row = document.createElement("tr");
    for (const value of [event.ts || "", event.event || "", event.step || ""]) { const cell = document.createElement("td"); cell.textContent = value; row.append(cell); }
    events.append(row);
  }
}

async function start() {
  session = await api("/api/session");
  const launchers = document.querySelector("#launchers");
  if (!session.launchers.length) launchers.textContent = "config.json に起動可能な成果物を設定してください。";
  for (const item of session.launchers) {
    const element = document.createElement("button"); element.textContent = `${item.label}を起動`;
    element.onclick = async () => { try { await api("/api/launch", {method: "POST", body: JSON.stringify({launcher_id: item.id})}); } catch (error) { alert(error.message); } };
    launchers.append(element);
  }
  await refresh();
}

document.querySelector("#refresh").onclick = refresh;
start().catch(error => { document.querySelector("#phase").textContent = error.message; });
