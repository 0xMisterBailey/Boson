// Boson app shell: the frame. The real ComfyUI canvas (same-origin iframe of `/`) fills the screen and stays live;
// Boson's layer covers it (rail, view, status line). One toggle brings the canvas forward and back. Picking a studio or scene loads its graph into the canvas (stored modes:
// nothing is queued) and hands the view to room.js or set.js. ComfyUI also imports this file on its own page: there
// it does nothing (no #boson-app).
//
// ---- the frame contract (wave 2: `room` owns room.js, `set` owns set.js; neither edits this file) ----
//   export async function renderStudio(view, boson, entry)   // room.js
//   export async function renderScene(view, boson, entry)    // set.js
//     view   the <main id="boson-view"> panel, already emptied of the idle hint; fill it, nothing outside it.
//     boson  bosonClient (../client.js), its graph = the canvas iframe's app. Reads, URL helpers, write verbs.
//     entry  { kind: "studio" | "scene", name, label, repo, row }: name = registry name (architecture-real),
//            label = the plain name shown (Architecture), repo = path for every client call, row = the
//            /boson/studios or /boson/scenes row as is (taste, sha, takes, slots...), so no refetch is needed.
//   The shell routes by hash (#studio/NAME, #scene/NAME), marks the picked rail row, and before calling render starts
//   loading the graph: studios -> boson.ensureStudio(repo) (workflows/studio.json, its Load Studio aimed at repo);
//   scenes -> boson.ensureScene(repo, "scene-NAME" if shipped, else "scene-street"). To wait for it yourself:
//   `await graphReady()` then call the client verb. A throw from render lands on the status line.
//   Helpers (./ui.js, import-side-effect-free): el(tag, text, parent, attrs); say(text, "info"|"ok"|"error") = the
//   status line; act(fn, doneWord) runs a verb and reports it; spendButton(parent, label, cost, verb) = a spend action
//   shown disabled with its cost (zero-spend rule); isPrivatePiece(piece) + PRIVATE_LABEL for found refs
//   (studio@sha:refs/...): show them on this box, always labelled; graphReady(); canvasApp(); canvasForward(on);
//   The toggle: the Graph button or the ` key (from the layer or the canvas).
//   frameGraph() = fit the graph into the screen space the layer leaves open (the shell calls it after each load).
//   Theme (theme.css, CSS variables only, no new colours): surfaces --b-surface, --b-surface-2, --b-surface-3, --b-line,
//   --b-blur; text --b-text, --b-text-2, --b-text-3; the one accent --b-accent (+ --b-accent-ink on it); --b-cost
//   (orange, spend labels only); --b-danger; type --b-font, --b-mono, --b-fs-xs/sm/md/lg/xl/2xl; space --b-s1..--b-s6;
//   --b-radius, --b-radius-sm, --b-shadow. Shared classes: .b-h1 .b-h2 .b-lede .b-meta .b-grid .b-card .b-cap .b-btn
//   .b-primary .b-cost .b-input .b-private .b-panel. Pictures are never tinted: dark frame, bright images.
import { bosonClient } from "../client.js";
import { el, say, graphReady, canvasApp, canvasForward, frameGraph, loadPrivateRefs, hideChrome } from "./ui.js";
import { tell, refusal, words } from "./messages.js";
import { renderStudio, plainName as plain } from "./room.js";
import { renderScene } from "./set.js";

const root = document.getElementById("boson-app");
if (root) main();

/** architecture-real -> Architecture, cars-s4471-real -> Cars s4471, tram-stop -> Tram stop. */

function main() {
  const view = document.getElementById("boson-view");
  const boson = bosonClient({ app: canvasApp });
  loadPrivateRefs().catch(() => {});   // licence labels; until it lands every ref reads as private
  const entries = new Map();          // "studio/NAME" | "scene/NAME" -> entry
  let picking = 0;                    // the newest pick wins when picks overlap

  document.getElementById("boson-toggle").onclick = () => canvasForward();
  // one keystroke, ` (backquote), toggles from either side (the canvas iframe is same-origin); never while typing
  const key = (e) => {
    const t = e.target, typing = /INPUT|TEXTAREA|SELECT/.test(t?.tagName) || t?.isContentEditable;
    if (e.key === "`" && !e.ctrlKey && !e.metaKey && !e.altKey && !typing) { e.preventDefault(); e.stopPropagation(); canvasForward(); }
  };
  document.addEventListener("keydown", key);
  const frame = document.getElementById("boson-canvas");
  // ComfyUI opens its templates browser on a first visit; under the layer it only covers the canvas. Close it once with
  // its own button (what a new user would click), watching the first 20 s of the canvas page; ComfyUI then remembers it
  // (Comfy.TutorialCompleted), as after that user's own click.
  const closeTemplates = (doc) => {
    const t0 = Date.now(), tick = () => {
      const x = doc.querySelector('[aria-labelledby="global-workflow-template-selector"] button[aria-label="Close dialog"]');
      if (x) x.click(); else if (Date.now() - t0 < 20000) setTimeout(tick, 250);
    };
    tick();
  };
  const hook = () => {
    frame.contentWindow?.addEventListener("keydown", key, true);
    if (!frame.contentDocument) return;
    closeTemplates(frame.contentDocument);
    hideChrome(frame.contentDocument, !document.body.classList.contains("boson-canvas-forward"));   // Graph view shows it again
  };
  frame.addEventListener("load", hook);
  if (frame.contentDocument?.readyState === "complete" && frame.contentWindow.location.href !== "about:blank") hook();

  const row = (ul, key, entry, note) => {
    entries.set(key, entry);
    const b = el("button", null, el("li", null, ul), { type: "button", className: "b-row", onclick: () => { location.hash = key; } });
    b.dataset.key = key;
    el("span", entry.label, b);
    if (note) el("small", note, b);
  };

  // a refusal naming pending casts (they live only in the graph): amber, Uncast buttons, then `again` once none is
  // left; any other failure to load the graph stays red
  const held = (e, again) => tell({ ...refusal(e), tone: e?.slots?.length ? "warn" : "error" }, { uncast: (slot) => {
    try { boson.uncast(slot); say(`${words(slot)}: uncast`, "ok"); } catch (x) { say(String(x.message ?? x), "error"); }
    if (!pendingSlots().length) again();
  } });
  const pendingSlots = () => { try { return canvasApp()?.graph ? boson.graphState().map((c) => c.slot) : []; } catch { return []; } };

  async function loadGraph(entry, n) {
    try {
      const app = await graphReady();
      if (n !== picking) return;
      if (entry.kind === "studio") await boson.ensureStudio(entry.repo);
      else {
        const wf = `scene-${entry.name}`;
        const own = await boson.hasWorkflow(wf);
        await boson.ensureScene(entry.repo, own ? wf : "scene-street");
        if (!own) say(`${entry.label} has no graph of its own yet: it uses the street scene's, so its slots are the street's.`, "info");
      }
      frameGraph(app);
    } catch (e) {
      if (n !== picking) return;
      held(e, () => loadGraph(entry, picking));
    }
  }

  let shown = null;                   // the key whose view is open
  async function open(key) {
    const entry = entries.get(key);
    // pending casts would be dropped by the new graph: refuse before anything moves (the hash goes back, the view stays)
    const pend = shown && shown !== key ? pendingSlots() : [];
    if (entry && pend.length) {
      history.replaceState(null, "", `#${shown}`);
      const what = pend.map(words).join(", ");
      held(Object.assign(new Error(`You have ${pend.length > 1 ? `${pend.length} unapplied swaps` : "an unapplied swap"} (${what}). ` +
        `Swap or Uncast ${pend.length > 1 ? "them" : "it"} before opening ${entry.label}.`), { slots: pend }), () => { location.hash = key; });
      return;
    }
    for (const b of document.querySelectorAll(".b-row")) b.setAttribute("aria-current", String(b.dataset.key === key));
    if (!entry) return;
    shown = key;
    const n = ++picking;
    if (entry.kind === "studio" && entry.older) document.getElementById("boson-older").open = true;
    document.getElementById("boson-where").textContent = `${entry.kind} · ${entry.label}`;
    view.classList.remove("b-idle");
    view.replaceChildren(el("p", `opening ${entry.label}...`, null, { className: "b-meta" }));
    say("");
    loadGraph(entry, n);
    try { await (entry.kind === "studio" ? renderStudio : renderScene)(view, boson, entry); }
    catch (e) { if (n === picking) say(`${entry.label}: ${e.message ?? e}`, "error"); }
  }

  async function rail() {
    try {
      const [studios, scenes, shelf] = await Promise.all([boson.studios(), boson.scenes(), boson.shelf()]);
      const ok = studios.filter((s) => !s.error);
      const real = ok.filter((s) => s.name.endsWith("-real")), older = ok.filter((s) => !s.name.endsWith("-real"));
      const mk = (s, extra = {}) => ({ kind: "studio", name: s.name, label: plain(s.name), repo: s.repo, row: s, ...extra });
      for (const s of real) row(document.getElementById("boson-studios"), `studio/${s.name}`, mk(s));
      for (const s of older) row(document.getElementById("boson-studios-older"), `studio/${s.name}`, mk(s, { older: true }));
      if (!older.length) document.getElementById("boson-older").hidden = true;
      const sc = document.getElementById("boson-scenes");
      for (const s of scenes.filter((x) => !x.error))
        row(sc, `scene/${s.name}`, { kind: "scene", name: s.name, label: plain(s.name), repo: s.repo, row: s }, `${s.takes} takes`);
      const sh = document.getElementById("boson-shelf");
      if (!shelf.length) el("p", "nothing kept yet", sh, { className: "b-empty" });
      else {
        const g = el("div", null, sh, { className: "b-shelf" });
        for (const p of shelf) el("img", null, g, { src: p.image, alt: p.piece, title: `${p.piece}${p.note ? `\n${p.note}` : ""}`, loading: "lazy" });
      }
      const broken = [...studios, ...scenes].filter((x) => x.error);
      if (broken.length) say(`not shown (broken): ${broken.map((x) => x.name).join(", ")}`, "error");
    } catch (e) { say(`could not read the floor: ${e.message ?? e}`, "error"); }
    window.addEventListener("hashchange", () => open(location.hash.slice(1)));
    if (location.hash.length > 1) open(location.hash.slice(1));
  }
  // a view's count changed (set.js: a take landed): its rail row says so at once
  view.addEventListener("boson-takes", (e) => {
    const { name, takes } = e.detail ?? {};
    const en = entries.get(`scene/${name}`);
    if (en) en.row.takes = takes;
    const s = document.querySelector(`.b-row[data-key="scene/${name}"] small`);
    if (s) s.textContent = `${takes} takes`;
  });
  rail();
}
