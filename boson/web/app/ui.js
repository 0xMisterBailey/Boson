// Boson app helpers shared by shell.js, room.js and set.js (the frame contract: top of shell.js). Exports only:
// ComfyUI imports every .js under web/ into its own page, so nothing here touches the document on import.

/** Make an element: el("button", "Keep", parent, { className: "b-btn", onclick }). */
export function el(tag, text, parent, attrs = {}) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  Object.assign(e, attrs);
  parent?.appendChild(e);
  return e;
}

/** The status line at the foot of the layer. tone: "info" | "ok" | "error". */
export function say(text, tone = "info") {
  const s = document.getElementById("boson-status");
  if (!s) return;
  s.textContent = text ?? "";
  s.dataset.tone = tone;
}

/** Run a write verb and report it on the status line: act(() => boson.keep(repo, file), "kept"). */
export async function act(fn, done = "queued") {
  try { const r = await fn(); say(`${done}${r != null ? `: ${r}` : ""}`, "ok"); return r; }
  catch (e) { say(String(e.message ?? e), "error"); }
}

/** A spend action, shown disabled with why, in words, and its cost (zero-spend rule): the label, the reason, the cost
 *  line, and the verb it would run (kept on the button as .verb so a test or a later "live" switch can call it). */
export function spendButton(parent, label, cost, verb, why = "off on this page: it spends") {
  const b = el("button", label, parent, { type: "button", className: "b-btn", disabled: true, title: `${why} (costs ${cost})` });
  b.verb = verb;
  el("span", why, parent, { className: "b-why" });
  el("span", cost, parent, { className: "b-cost" });
  return b;
}

/** True when a piece (studio@sha:path) is a found reference photo: private on this box, never redistributed. */
// Private = a studio reference whose refs.jsonl licence says "found reference" (GET /boson/private-refs, loaded once by
// the shell). Until that answer arrives every refs/ piece counts as private: the safe side.
export const privateRefs = { map: null };
export async function loadPrivateRefs(base = "") {
  const r = await fetch(`${base}/boson/private-refs`);
  if (r.ok) privateRefs.map = await r.json();
}
export const isPrivatePiece = (piece) => {
  const m = /^([^@]+)@[^:]+:refs\/([^/]+)$/.exec(String(piece ?? ""));
  if (!m) return false;
  const known = privateRefs.map;
  return known ? (known[m[1]] ?? []).includes(m[2]) : true;
};
export const PRIVATE_LABEL = "found reference, private, not redistributed";

/** The live ComfyUI app inside the canvas iframe, once its graph exists. */
export function canvasApp() {
  return document.getElementById("boson-canvas")?.contentWindow?.app;
}

/** Resolves with the canvas app when its graph is ready (the iframe loads ComfyUI in a few seconds). */
export function graphReady(timeoutMs = 60000) {
  const t0 = Date.now();
  return new Promise((ok, no) => {
    const tick = () => {
      const a = canvasApp();
      if (a?.graph && a.canvas) return ok(a);
      if (Date.now() - t0 > timeoutMs) return no(new Error("the ComfyUI canvas did not load"));
      setTimeout(tick, 200);
    };
    tick();
  });
}

/** Bring the real canvas forward (the Boson layer hides) or send it back. Returns the new state. */
export function canvasForward(on) {
  const forward = on ?? !document.body.classList.contains("boson-canvas-forward");
  document.body.classList.toggle("boson-canvas-forward", forward);
  const t = document.getElementById("boson-toggle");
  if (t) { t.setAttribute("aria-pressed", String(forward)); t.textContent = forward ? "Back to Boson" : "Graph"; }
  if (forward) document.getElementById("boson-canvas")?.focus();
  hideChrome(document.getElementById("boson-canvas")?.contentDocument, !forward);
  frameGraph(canvasApp(), { forward });
  return forward;
}

/** ComfyUI's own chrome that shows around and through the Boson layer (frontend 1.57: the Run bar and its issues
 *  panel, the right sidebar, the minimap, the workflow tabs, toasts): hidden while the layer is up, back in Graph view. */
export const CHROME_CSS = ["#last-side-panel", "#main-panel > :first-child:not(:has(.graph-canvas-panel))", ".actionbar-container",
  ".minimap-main-container", ".workflow-tabs-container", ".p-toast"].map((x) => `html.boson-under ${x}`).join(",\n") + " { display: none !important; }";
export function hideChrome(doc, on = true) {
  if (!doc?.documentElement) return false;
  if (!doc.getElementById("boson-chrome")) {
    const st = doc.createElement("style");
    st.id = "boson-chrome"; st.textContent = CHROME_CSS;
    (doc.head ?? doc.documentElement).appendChild(st);
  }
  doc.documentElement.classList.toggle("boson-under", on);
  return true;
}

/** Below this zoom ComfyUI draws nodes as blank boxes (rehearsal 1: scene graphs opened at 45%). */
export const READABLE_ZOOM = 0.65;

/** Fit the canvas graph right of the rail, right-aligned, so it reads in the space the view leaves open and through
 *  the view's translucent panel. forward (the graph brought forward): the whole screen, never below READABLE_ZOOM;
 *  a graph too big for that shows from its top-left, where the main chain starts. Best effort: a frontend without
 *  LiteGraph's ds keeps its view. */
export function frameGraph(app = canvasApp(),
  { forward = typeof document !== "undefined" && document.body?.classList.contains("boson-canvas-forward") } = {}) {
  try {
    const ns = app?.graph?._nodes ?? [];
    const ds = app?.canvas?.ds;
    if (!ns.length || !ds) return false;
    const x0 = Math.min(...ns.map((n) => n.pos[0])), y0 = Math.min(...ns.map((n) => n.pos[1] - 30));
    const x1 = Math.max(...ns.map((n) => n.pos[0] + n.size[0])), y1 = Math.max(...ns.map((n) => n.pos[1] + n.size[1]));
    const W = innerWidth, H = innerHeight, pad = 24;
    if (forward) {
      const w = W - 2 * pad, h = H - 2 * pad - 80;
      const fit = Math.min(1, w / (x1 - x0), h / (y1 - y0));
      const scale = Math.max(READABLE_ZOOM, fit);
      ds.scale = scale;
      const side = 72;                                              // ComfyUI's own left toolbar
      ds.offset[0] = fit >= READABLE_ZOOM ? (side + (W - side - (x1 - x0) * scale) / 2) / scale - x0 : (side + pad) / scale - x0;
      ds.offset[1] = fit >= READABLE_ZOOM ? (pad + 80 + (h - (y1 - y0) * scale) / 2) / scale - y0 : (pad + 80) / scale - y0;
      app.canvas.setDirty(true, true);
      return true;
    }
    const left = document.getElementById("boson-rail")?.getBoundingClientRect().right ?? 0;
    const w = W - left - 2 * pad, h = H - 2 * pad - 80;          // 80: ComfyUI's own top bars
    const scale = Math.max(0.15, Math.min(1, w / (x1 - x0), h / (y1 - y0)));
    ds.scale = scale;
    ds.offset[0] = (W - pad - (x1 - x0) * scale) / scale - x0;   // right-aligned
    ds.offset[1] = (pad + 80 + (h - (y1 - y0) * scale) / 2) / scale - y0;
    app.canvas.setDirty(true, true);
    return true;
  } catch { return false; }
}
