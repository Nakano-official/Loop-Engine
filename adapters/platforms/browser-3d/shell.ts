// The generic shell for browser-3d (DESIGN 1 and 7, platform 2). Machine-provided:
// no app writes its own. It calls the app's five functions and draws the Scene
// they return with three.js; everything an app does is in those functions,
// where the examples check it.
//
//   start(now, saved) once, with what localStorage held
//   step(state, now, input) every animation frame, with what is being pressed
//   act(state, action, now) on a click ("click") or a HUD button
//   screen(state)     every frame: the camera, the objects, the HUD
//   save(state)       once a second and after every act, into localStorage
//
// Two halves, kept apart: the loop that calls the app (frame) and the renderer
// that draws. Where there is no WebGL -- the boot check, in happy-dom -- the
// renderer is absent and every frame is still run and its Scene still checked.

import * as THREE from "three";

type Vec3 = { x: number; y: number; z: number };
type Obj = { id: string; shape: string; position: Vec3; size: Vec3; rotation_y: number; color: string };
type Node = { kind: string; text: string; action: string; enabled: boolean };
type Scene = { title: string; camera: { position: Vec3; yaw: number; pitch: number; fov: number };
               objects: ReadonlyArray<Obj>; hud: ReadonlyArray<Node> };
type Input = { keys: string[]; mouse_dx: number; mouse_dy: number; locked: boolean };
type App = {
  start(now: number, saved: string | null): unknown;
  step(state: unknown, now: number, input: Input): unknown;
  act(state: unknown, action: string, now: number): unknown;
  screen(state: unknown): Scene;
  save(state: unknown): string;
};

const SHAPES = new Set(["box", "sphere", "plane", "cylinder"]);
const finite = (n: unknown) => typeof n === "number" && Number.isFinite(n);
const vec = (v: Vec3 | undefined) => !!v && finite(v.x) && finite(v.y) && finite(v.z);

// The Scene must be well formed before anything is drawn: an app that returns
// NaN for a position, or a shape that does not exist, is reported -- not drawn
// as an invisible object nobody notices.
export function check(s: Scene): void {
  if (!s || typeof s.title !== "string") throw new Error("scene: no title");
  const c = s.camera;
  if (!c || !vec(c.position) || !finite(c.yaw) || !finite(c.pitch) || !finite(c.fov) || c.fov <= 0 || c.fov >= 180)
    throw new Error("scene: the camera is not well formed");
  const ids = new Set<string>();
  for (const o of s.objects) {
    if (typeof o.id !== "string" || ids.has(o.id)) throw new Error(`scene: object id ${o.id} is missing or repeated`);
    ids.add(o.id);
    if (!SHAPES.has(o.shape)) throw new Error(`scene: ${o.id} has an unknown shape ${o.shape}`);
    if (!vec(o.position) || !vec(o.size) || !finite(o.rotation_y)) throw new Error(`scene: ${o.id} has a number that is not finite`);
    if (!/^#[0-9a-fA-F]{6}$/.test(o.color)) throw new Error(`scene: ${o.id} has a color that is not #rrggbb`);
  }
}

function read(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function write(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* private mode, sandboxed: keep playing */ }
}

class Renderer {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(70, 1, 0.05, 1000);
  private meshes = new Map<string, { mesh: THREE.Mesh; key: string }>();
  private geometries = new Map<string, THREE.BufferGeometry>();
  private materials = new Map<string, THREE.Material>();

  constructor(host: HTMLElement) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    host.appendChild(this.renderer.domElement);
    this.scene.background = new THREE.Color("#9fc3e6");
    this.scene.add(new THREE.HemisphereLight("#ffffff", "#5a6b55", 1.1));
    const sun = new THREE.DirectionalLight("#ffffff", 1.4);
    sun.position.set(4, 10, 6);
    this.scene.add(sun);
    this.camera.rotation.order = "YXZ";
    const fit = () => {
      this.renderer.setSize(window.innerWidth, window.innerHeight);
      this.camera.aspect = window.innerWidth / Math.max(1, window.innerHeight);
      this.camera.updateProjectionMatrix();
    };
    window.addEventListener("resize", fit);
    fit();
  }

  get canvas(): HTMLCanvasElement { return this.renderer.domElement; }

  private geometry(o: Obj): THREE.BufferGeometry {
    const key = `${o.shape}:${o.size.x}:${o.size.y}:${o.size.z}`;
    let g = this.geometries.get(key);
    if (!g) {
      if (o.shape === "box") g = new THREE.BoxGeometry(o.size.x, o.size.y, o.size.z);
      else if (o.shape === "sphere") g = new THREE.SphereGeometry(o.size.x / 2, 24, 16);
      else if (o.shape === "cylinder") g = new THREE.CylinderGeometry(o.size.x / 2, o.size.x / 2, o.size.y, 24);
      else { g = new THREE.PlaneGeometry(o.size.x, o.size.z); g.rotateX(-Math.PI / 2); }
      this.geometries.set(key, g);
    }
    return g;
  }

  private material(color: string): THREE.Material {
    let m = this.materials.get(color);
    if (!m) { m = new THREE.MeshStandardMaterial({ color, side: THREE.DoubleSide }); this.materials.set(color, m); }
    return m;
  }

  draw(s: Scene): void {
    const seen = new Set<string>();
    for (const o of s.objects) {
      seen.add(o.id);
      const key = `${o.shape}:${o.size.x}:${o.size.y}:${o.size.z}:${o.color}`;
      let entry = this.meshes.get(o.id);
      if (!entry || entry.key !== key) {
        if (entry) this.scene.remove(entry.mesh);
        entry = { mesh: new THREE.Mesh(this.geometry(o), this.material(o.color)), key };
        this.meshes.set(o.id, entry);
        this.scene.add(entry.mesh);
      }
      entry.mesh.position.set(o.position.x, o.position.y, o.position.z);
      entry.mesh.rotation.y = o.rotation_y;
    }
    for (const [id, entry] of this.meshes) {
      if (!seen.has(id)) { this.scene.remove(entry.mesh); this.meshes.delete(id); }
    }
    const c = s.camera;
    this.camera.position.set(c.position.x, c.position.y, c.position.z);
    this.camera.rotation.y = c.yaw;
    this.camera.rotation.x = c.pitch;
    if (this.camera.fov !== c.fov) { this.camera.fov = c.fov; this.camera.updateProjectionMatrix(); }
    this.renderer.render(this.scene, this.camera);
  }
}

function webgl(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl")));
  } catch {
    return false;
  }
}

export function mount(app: App, key: string, root: HTMLElement) {
  const now = () => performance.now() / 1000 + performance.timeOrigin / 1000;
  let state: unknown;
  try { state = app.start(now(), read(key)); } catch { state = app.start(now(), null); }

  const view = document.createElement("div");
  view.className = "view";
  const hud = document.createElement("div");
  hud.className = "hud";
  root.replaceChildren(view, hud);
  const renderer = webgl() ? new Renderer(view) : null;

  // ---- input -----------------------------------------------------------
  const keys = new Set<string>();
  let dx = 0, dy = 0;
  window.addEventListener("keydown", (e) => keys.add(e.key.toLowerCase()));
  window.addEventListener("keyup", (e) => keys.delete(e.key.toLowerCase()));
  window.addEventListener("blur", () => keys.clear());
  const locked = () => !!renderer && document.pointerLockElement === renderer.canvas;
  document.addEventListener("mousemove", (e) => { if (locked()) { dx += e.movementX; dy += e.movementY; } });
  (renderer?.canvas ?? view).addEventListener("click", () => {
    if (renderer && !locked()) renderer.canvas.requestPointerLock?.();
    act("click");
  });

  // ---- the app -----------------------------------------------------------
  let hudDrawn = "";
  const drawHud = (nodes: ReadonlyArray<Node>) => {
    const sig = JSON.stringify(nodes);
    if (sig === hudDrawn) return;               // rebuilding every frame would eat clicks
    hudDrawn = sig;
    hud.replaceChildren(...nodes.map((n) => {
      if (n.kind === "button") {
        const b = document.createElement("button");
        b.textContent = n.text;
        b.disabled = !n.enabled;
        b.addEventListener("click", (e) => { e.stopPropagation(); act(n.action); });
        return b;
      }
      const el = document.createElement(n.kind === "heading" ? "h1" : "p");
      el.textContent = n.text;
      return el;
    }));
  };

  function act(action: string): void {
    try { state = app.act(state, action, now()); } catch { return; }   // not allowed: nothing happens
    write(key, app.save(state));
  }

  // A step that throws keeps the state, so the player is not stuck on a blank
  // page -- but it is a bug, not a refusal like act's, so it is reported (each
  // message once) and the boot check sees it.
  const reported = new Set<string>();
  let lastSave = 0;
  function frame(t: number, input: Input): Scene {
    try { state = app.step(state, t, input); } catch (e) {
      const m = "step: " + String((e as Error)?.message ?? e);
      if (!reported.has(m)) { reported.add(m); console.error(m); }
    }
    const scene = app.screen(state);
    check(scene);
    document.title = scene.title;
    drawHud(scene.hud);
    renderer?.draw(scene);
    if (t - lastSave >= 1) { lastSave = t; write(key, app.save(state)); }
    return scene;
  }

  const loop = () => {
    const input: Input = { keys: [...keys], mouse_dx: dx, mouse_dy: dy, locked: locked() };
    dx = dy = 0;
    try { frame(now(), input); } catch (e) { console.error(String((e as Error)?.message ?? e)); }
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
  window.addEventListener("beforeunload", () => write(key, app.save(state)));

  // A handle for the boot check: run frames with a given input, press actions.
  return { frame, act, rendering: !!renderer };
}
