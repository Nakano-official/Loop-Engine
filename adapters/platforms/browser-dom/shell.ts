// The generic shell for browser-dom (REDESIGN 1). Machine-provided: no app
// writes its own. It calls the app's five functions and draws the Screen they
// return; everything an app does is in those functions, where the examples
// check it.
//
//   start(now, saved) once, with what localStorage held
//   step(state, now)  every second
//   act(state, action, now) when a button is pressed
//   screen(state)     after every change, drawn as a vertical list
//   save(state)       after every change, into localStorage
//
// An error from step or act leaves the state as it was: an action that is not
// allowed (not enough resource, say) does nothing. An error from start with
// saved data starts fresh -- a save that cannot be read must not lock the app.

type Node = { kind: "heading" | "text" | "button"; text: string; action: string; enabled: boolean };
type Screen = { title: string; nodes: ReadonlyArray<Node> };
type App = {
  start(now: number, saved: string | null): unknown;
  step(state: unknown, now: number): unknown;
  act(state: unknown, action: string, now: number): unknown;
  screen(state: unknown): Screen;
  save(state: unknown): string;
};

const now = () => Date.now() / 1000;

function read(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

function write(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* private mode, full: keep playing */ }
}

export function mount(app: App, key: string, root: HTMLElement): void {
  let state: unknown;
  const saved = read(key);
  try {
    state = app.start(now(), saved);
  } catch {
    state = app.start(now(), null);
  }

  const change = (next: () => unknown) => {
    try {
      state = next();
    } catch {
      return;                           // not allowed: nothing happens
    }
    write(key, app.save(state));
    draw();
  };

  const draw = () => {
    const screen = app.screen(state);
    document.title = screen.title;
    const els = screen.nodes.map((n) => {
      if (n.kind === "heading") {
        const h = document.createElement("h1");
        h.textContent = n.text;
        return h;
      }
      if (n.kind === "button") {
        const b = document.createElement("button");
        b.textContent = n.text;
        b.disabled = !n.enabled;
        b.dataset.action = n.action;
        b.addEventListener("click", () => change(() => app.act(state, n.action, now())));
        return b;
      }
      const p = document.createElement("p");
      p.textContent = n.text;
      return p;
    });
    root.replaceChildren(...els);
  };

  write(key, app.save(state));
  draw();
  setInterval(() => change(() => app.step(state, now())), 1000);
}
