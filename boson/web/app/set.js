// Boson set: the scene view. A scene is a base studio's view plus slots other studios fill, re-shot take by take
// (SPEC §1, docs/APP-API.md); the operator's picture (round 32): "a full scene editor where you can click on different
// elements, each of which has its own studio". So: the take large, its slots as HUD boxes over the picture (hover names
// the slot and its studio, click opens it: its piece, that studio's pieces to cast, Cast), the takes as a timeline, a
// take's clips with playback, and "Set in motion" (loads the motion graph into the canvas; queueing it spends).
// Contract (top of shell.js): renderScene(view, boson, entry) fills `view`; the shell has already started loading the
// scene graph. Exports only (ComfyUI imports every .js under web/ into its own page); pure helpers are exported so
// tests/set_harness.mjs can check them without a browser.
import { el, say, act, spendButton, isPrivatePiece, PRIVATE_LABEL, graphReady, canvasApp, canvasForward, frameGraph } from "./ui.js";
import { run, tell, refusal, words as slotWords, usd, IMAGE_USD, WRITER_USD, KEYLESS } from "./messages.js";

export const SHOOT_COST = "one image call + one vision call";
export const SWAP_COST = "one image call (none if only flats) + one vision call";
export const MOTION_COST = "$0.14-0.87 per 6 s clip, Comfy credits";

/** Where each slot sits in a take: [{id, role, studio, kind, rects: [[x, y, w, h]], quads: [[[x, y] x4]], seen,
 *  swapped}], fractions of the frame. From the take's boxes.json (Locate's readout), else the slot's planned place. */
export function slotShapes(slots, take) {
  const located = take?.boxes?.slots ?? {};
  return slots.map((s) => {
    const b = located[s.id];
    const items = b?.items ?? (b?.box ? [b] : []);
    const rects = items.filter((i) => !i.quad && i.box).map((i) => i.box);
    const quads = items.filter((i) => i.quad).map((i) => i.quad);
    if (!rects.length && !quads.length && s.place?.box) rects.push(s.place.box);
    return { id: s.id, role: s.role ?? s.id, studio: s.studio, kind: s.kind, rects, quads,
             seen: Boolean(b) && b.visible !== false, swapped: (take?.swapped ?? []).includes(s.id) };
  });
}

/** What the base shows that no slot holds yet, where a take's Locate saw it: [{name, desc, rect}] (round 49: any of
 *  these can be made a slot, e.g. the taqueria). Only anchors still in base.anchors, with a box in this take, and not
 *  placing a slot. The shelter places the outfit and the poster (4ee2688): it stays an anchor that scene.promote
 *  refuses, so it gets no "make it a slot" tag; its own slots' tags already mark it. */
export function anchorShapes(base, take, slots = []) {
  const seen = take?.boxes?.anchors ?? {};
  const placing = new Set(slots.map((s) => s.place?.anchor).filter(Boolean));
  return Object.entries(base?.anchors ?? {}).filter(([n]) => seen[n]?.box && !placing.has(n))
    .map(([name, desc]) => ({ name, desc, rect: seen[name].box }));
}

/** A new slot's id from what it is ("the corner building" -> "corner-building"), unique among the slots. */
export function slotIdFor(noun, slots) {
  const base = String(noun ?? "").toLowerCase().replace(/^(the|a|an) /, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "slot";
  const ids = new Set(slots.map((s) => s.id));
  let id = base, k = 2;
  while (ids.has(id)) id = `${base}-${k++}`;
  return id;
}

/** The top-left of a slot's first shape (where its HUD tag hangs), as fractions. */
export function shapeAnchor(sh) {
  if (sh.rects.length) return [sh.rects[0][0], sh.rects[0][1]];
  if (sh.quads.length) return [Math.min(...sh.quads[0].map((p) => p[0])), Math.min(...sh.quads[0].map((p) => p[1]))];
  return [0, 0];
}

/** Where a slot's HUD tag goes: above its shape, or below it when an earlier tag already sits there; a shape in the
 *  right half hangs its tag from its right edge (right, a fraction), so the open tag grows left, never past the
 *  picture. Pushes onto placed. -> [x, y, below, right | null]. */
export function tagSpot(sh, placed) {
  const [x, y] = shapeAnchor(sh);
  const bottom = Math.max(...sh.rects.map((r) => r[1] + r[3]), ...sh.quads.flat().map((p) => p[1]), y);
  const edge = Math.max(...sh.rects.map((r) => r[0] + r[2]), ...sh.quads.flat().map((p) => p[0]), x);
  const right = (x + edge) / 2 > 0.5 ? edge : null;
  const clash = placed.some(([px, py]) => Math.abs(px - x) < 0.09 && Math.abs(py - y) < 0.05);
  const spot = clash ? [x, bottom, true, right] : [x, y, false, right];
  placed.push(spot);
  return spot;
}

/** One short line per take, for the strip: "21 · outfit, poster swap", "01 · shoot". */
export function takeLine(t) {
  const what = t.op === "swap" ? `${(t.swapped ?? []).map(slotWords).join(", ")} swap`.trim() : (t.op ?? "take");
  return `${t.id} · ${what}`;
}

/** Local models by their plain names (boson/local_render.py MODEL, scene.local_json's Locate model). */
export const LOCAL_MODELS = { "flux3-image-klein-bf16": "FLUX 3 Klein", "qwen3.8-27b": "Qwen3.8 27B" };

/** A renderer id as its plain name: "boson-nanobanana:comfy-api:gemini-nano-banana-2.1" -> "Nano Banana 2.1",
 *  "comfy-api:ltx-2.5-pro" -> "LTX 2.5 Pro", "boson-nanobanana:local:flux3-image-klein-bf16" -> "FLUX 3 Klein (local)"
 *  (any model run on this machine says so); none recorded -> "". */
export function rendererName(r) {
  const parts = String(r ?? "").split(":"), id = parts.pop().replace(/^gemini-/, "");
  const name = LOCAL_MODELS[id] ?? id.split(/[-_]+/).filter(Boolean)
    .map((w) => (/^(ltx|gpt|sd|xl)$/i.test(w) ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1))).join(" ");
  return name && parts.includes("local") ? `${name} (local)` : name;
}

/** A take's picture in plain words: "take 21 · edit of take 01 · made with Nano Banana 2.1" (the renderer only when
 *  recorded). Given the scene's takes, an edit whose parent another model drew names that one too, so a local edit
 *  never hides a cloud-drawn input (memory feedback--local-claims-name-every-input-origin): "take 14 · edit of take 12
 *  (Nano Banana 2.1) · made with FLUX 3 Klein (local)"; a parent with no renderer -> "(model not recorded)", never a
 *  guess. */
export function takeProvenance(t, takes = []) {
  const by = rendererName(t.renderer);
  const parent = t.op === "swap" ? takes.find((p) => p.id === t.parent) : null;
  const from = parent && by ? rendererName(parent.renderer) || "model not recorded" : "";
  const edit = `edit of take ${t.parent}${from && from !== by ? ` (${from})` : ""}`;
  return [`take ${t.id}`, t.op === "swap" ? edit : t.op, by && `made with ${by}`].filter(Boolean).join(" · ");
}

/** The same take as Boson stores it (behind a details toggle): its renderer id and the scene commit. */
export function takeDetails(t, sha) {
  return [t.renderer ?? "renderer not recorded", `scene @${sha}`].join(" · ");
}

/** A piece ref (studio@sha:path) as provenance: {studio, sha, path, private}. */
export function pieceParts(piece) {
  const m = /^([^@]+)@([^:]+):(.+)$/.exec(String(piece ?? ""));
  return m ? { studio: m[1], sha: m[2].slice(0, 8), path: m[3], private: isPrivatePiece(piece) }
    : { studio: "", sha: "", path: String(piece ?? ""), private: false };
}

/** A piece's name in plain words, from its file: "...rmake-6c59/crosswalk-over-rails__d0__nbn.png" -> "crosswalk over
 *  rails"; a numbered reference -> "reference 02". */
export function pieceName(piece) {
  const path = pieceParts(piece).path;
  const f = path.split("/").pop().replace(/\.[a-z0-9]+$/i, "").replace(/__.*$/, "").replace(/[-_]+/g, " ").trim();
  return /^\d+$/.test(f) ? `reference ${f}` : f || path;
}

/** The take a Swap edits (scene.swap_parent): the chosen take, or the newest shoot when that is newer. */
export function swapBase(takes, chosen) {
  const shoot = [...(takes ?? [])].reverse().find((t) => t.op === "shoot") ?? null;
  const ch = (takes ?? []).find((t) => t.id === chosen);
  return ch && (!shoot || Number(ch.id) > Number(shoot.id)) ? ch : shoot;
}

/** A swap's readiness (one row of GET /boson/ready swaps) -> {state, short, text}: ready = its picture is stored and
 *  so is where its slots are (located); stored but located unknown (null) = maybe; stored only for a take made after
 *  other swaps (later) = not yet, and which swaps come first; else it needs live calls, and what they cost. */
export function swapBadge(r, live = false) {
  if (!r) return { state: "checking", short: "", text: "checking what is stored…" };
  if (r.error) return { state: "unknown", short: "", text: "can't tell if this one is stored" };
  if (r.same) return { state: "same", short: "in take", text: "already in this take" };
  if (r.stored && r.located) return { state: "ready", short: "ready", text: "ready (replays instantly)" };
  if (r.stored && r.located == null) return { state: "maybe", short: "stored", text: "picture stored · finding its slots may need one look",
    cost: "one look to find the slots (a vision call), if Boson never found them in this picture" };
  if (!r.stored && r.later?.after?.length) {
    const after = r.later.after.map((a) => `the ${slotWords(a.slot)} swap (${pieceName(a.piece)})`).join(" and ");
    return { state: "later", short: "not yet", text: `not yet: replays after ${after}`, after,
             cost: `one picture and one look to find the slots, about ${usd(IMAGE_USD)}` };
  }
  const cost = r.stored ? "one look to find the slots" : `about ${usd(IMAGE_USD)}`;
  return { state: "live", short: live ? "spends" : "live", text: live ? `live calls on: made now, ${cost}` : `needs live calls (${cost}) · off: replays only`,
           cost: r.stored ? "one look to find the slots (a vision call)" : `one picture and one look to find the slots, about ${usd(IMAGE_USD)}` };
}

/** A Make for this spot (one row of ready makes, or none yet) -> {state, short, text}, as swapBadge. */
export function makeBadge(m, live = false, n = 4) {
  if (m === undefined) return { state: "checking", short: "", text: "checking what is stored…" };
  if (m?.stored) return { state: "ready", short: "ready", text: "ready (replays instantly)" };
  const cost = `about ${usd(WRITER_USD[0] + n * IMAGE_USD)}-${usd(WRITER_USD[1] + n * IMAGE_USD)}`;
  return { state: "live", short: live ? "spends" : "live", text: live ? `live calls on: made now, ${cost}` : `needs live calls (${cost}) · off: replays only` };
}

/** The shelf with what a Make made for this spot first, each marked made: (castable rows, [piece refs]) -> rows. */
export function madeFirst(list, made = []) {
  const at = (x) => { const p = pieceParts(x); return `${p.studio}:${p.path}`; };   // one piece, whichever commit names it
  const have = new Map(list.map((p) => [at(p.piece), p]));
  const mine = new Set(made.map(at));
  return [...made.map((x) => ({ ...(have.get(at(x)) ?? { piece: x, title: pieceName(x), kept: false }), made: true })),
          ...list.filter((p) => !mine.has(at(p.piece)))];
}

/** Which of the slot panel's four steps is lit: 1 pick a thing (done once open), 2 who makes it, 3 pick one, 4 swap. */
export const STEPS = ["Pick a thing", "Who makes it", "Pick one", "Swap"];
export const stepOf = ({ studio = false, piece = false } = {}) => (piece ? 4 : studio ? 3 : 2);

/** The slots a graph can cast: the slot widget of each Cast node. */
export function castSlots(graph) {
  return (graph?._nodes ?? []).filter((n) => n.type === "BosonCast").map((n) => n.widgets?.find((w) => w.name === "slot")?.value);
}

/** A slot studio's pieces to cast: what it kept on the shelf first, then its makes, newest first, one per piece. */
export function castable(studioState, shelf, studioName, limit = 24) {
  const out = new Map();
  for (const p of shelf.filter((x) => x.studio === studioName))
    out.set(p.piece, { piece: p.piece, title: p.note || pieceParts(p.piece).path, kept: true, image: p.image });
  for (const m of [...(studioState?.makes ?? [])].reverse())
    for (const p of m.pieces) if (!out.has(p.piece)) out.set(p.piece, { piece: p.piece, title: p.title, file: p.file, kept: false, make: m.idea || m.frame || "" });
  return [...out.values()].slice(0, limit);
}

/** What a slot holds, as words a studio's field would use (the slot's id or short noun -> a pattern). */
export const KIND_WORDS = { outfit: /fashion|menswear|womenswear|streetwear|cloth|outfit/i, car: /\bcars?\b|vehicle|automo/i,
  building: /architect|building/i, poster: /poster|graphic design/i };

/** The studios that can fill a slot: its own studio first, then every studio whose field names what the slot holds,
 *  then the rest (any studio may fill any slot; fits only orders the list). -> [{...studio, fits}]. */
export function studiosFor(slot, studios) {
  const ok = (studios ?? []).filter((s) => !s.error);
  const word = String(slot.short ?? slot.noun ?? slot.id).replace(/^(the|a|an) /i, "").split(" ").pop().toLowerCase();
  const re = KIND_WORDS[word] ?? KIND_WORDS[slot.id] ?? new RegExp(`\\b${word.replace(/[^a-z0-9]/g, "")}`, "i");
  const fits = (s) => s.name === slot.studio || re.test(`${s.field ?? ""} ${s.name}`);
  const own = ok.filter((s) => s.name === slot.studio);
  return [...own, ...ok.filter((s) => s.name !== slot.studio && fits(s)), ...ok.filter((s) => !fits(s))]
    .map((s) => ({ ...s, fits: fits(s) }));
}

export async function renderScene(view, boson, entry) {
  const d = await boson.scene(entry.repo);
  const repo = d.repo ?? entry.repo;
  const slots = d.spec.slots;
  const clips = d.clips ?? [];
  const wf = (await boson.hasWorkflow(`scene-${entry.name}`)) ? `scene-${entry.name}` : "scene-street";
  const chosen = () => d.takes.find((t) => t.id === d.spec.chosen);   // SCENE.json chosen: the take the scene stands on
  let current = chosen() ?? d.takes[d.takes.length - 1];
  let opened = null;                                   // the slot id whose panel is open
  let sinceFirst = false;                              // the compare slider: this take vs the take its swaps started from
  const studioCache = new Map();
  let shelf = null, studios = null;
  const from = new Map();                              // slot id -> the studio its shelf shows (default: the slot's own)
  const picked = new Map();                            // slot id -> the piece picked on its shelf (not cast yet)
  const made = new Map();                              // slot id -> {studio, take, pieces} its last Make for this spot made
  const readyCache = new Map();                        // a slot's ready read (GET /boson/ready), per scene commit and ask
  let live = false;                                    // the set's spend switch: off = stored replays only, no call
  let keyless = false;                                 // this box has no keys (GET /boson/ready has_key): replay only
  boson.ready(entry.name).then((r) => { keyless = r?.has_key === false; actions.keyless = keyless; }, () => {});

  view.replaceChildren();
  style(view);
  el("h1", entry.label, view, { className: "b-h1" });
  const base = d.spec.base;
  const basePiece = `${base.studio}@${base.ref}:${base.view}`;   // what a slot made from the frame holds until a swap (scene.base_piece)
  const meta = el("p", null, view, { className: "b-meta" });
  const drawMeta = () => {                             // again after each reload: a new take, a new commit (the rail too)
    meta.textContent = `${d.takes.length} takes · ${clips.length} clip${clips.length === 1 ? "" : "s"} · base photo: ${pieceName(`x@y:${base.view}`)} from the ${base.studio} studio`;
    meta.title = `base ${base.studio}@${base.ref}:${base.view} · scene @${d.sha}`;
    if (isPrivatePiece(`${base.studio}@${base.ref}:${base.view}`)) el("span", ` · ${PRIVATE_LABEL}`, meta, { className: "b-private" });
    view.dispatchEvent(new CustomEvent("boson-takes", { bubbles: true, detail: { name: entry.name, takes: d.takes.length } }));
  };
  const spend = el("label", null, view, { className: "bs-live", title: "off: Make and Swap replay what was made before (no key, no call). on: what was never made is made now, and paid" });
  const liveBox = el("input", null, spend, { type: "checkbox", checked: live, role: "switch" });
  el("b", "Live calls", spend);
  const liveSays = el("span", null, spend);
  const liveLine = () => { liveSays.textContent = live ? "On: what was never made is made now, and paid" : "Off: replays what was made before, free"; };
  liveLine();
  liveBox.onchange = () => { live = liveBox.checked; liveLine(); if (opened) openSlot(opened); };

  // the next steps a status line can offer (messages.js tell): the live switch, Uncast a pending cast
  const actions = {
    live: { label: "Turn on live calls", run: () => { liveBox.checked = true; liveBox.onchange(); } },
    replay: { label: "Turn live calls off", run: () => { liveBox.checked = false; liveBox.onchange(); } },
    uncast: (slot) => { try { boson.uncast(slot); say(`${slotWords(slot)}: uncast, nothing pending for it`, "ok"); } catch (e) { say(String(e.message ?? e), "error"); }
      if (opened && !opened.startsWith("anchor:")) openSlot(opened); else drawCast(); },
  };
  // a verb that queues nothing (Cast, load a graph): its line, or the refusal with Uncast for the casts it names
  const acted = async (fn, done) => { try { const r = await fn(); say(`${done}${r != null ? `: ${r}` : ""}`, "ok"); return r; }
    catch (e) { tell(refusal(e), actions); } };
  // a write: queue it, hear every node of the run (progress, Cancel), say the outcome, then the scene again
  const go = async (label, verb, { busy, then = (o) => reload(undefined, o?.take) } = {}) => run(label, verb, {
    app: await graphReady().catch(() => canvasApp()), upstream: (ids) => boson.upstream(ids), interrupt: (p) => boson.interrupt(p),
    actions, busy, then });
  const reload = async (slot, take) => {               // the scene again (a new take, else the chosen one, becomes current)
    const n = await boson.scene(entry.repo);
    Object.assign(d, n); slots.splice(0, slots.length, ...n.spec.slots);
    clearCommitted();
    readyCache.clear();
    current = d.takes.find((t) => t.id === take) ?? chosen() ?? d.takes[d.takes.length - 1] ?? current;
    opened = slot ?? opened;
    if (opened?.startsWith("anchor:") && !d.spec.base.anchors?.[opened.slice(7)]) opened = null;
    drawAll();
    if (take) { picked.delete(opened); view.scrollTo?.({ top: 0 }); }   // a new take shows at once, no scrolling
  };
  /** Use this take (Undo swap = the swap's parent): the scene stands on it, one commit, nothing deleted. Picks staged
   *  on the graph are cleared first: they were picked against the take the scene stood on. */
  async function useTake(tid, what) {
    try {
      try { for (const c of boson.graphState()) boson.uncast(c.slot); } catch { /* no scene graph: nothing staged */ }
      await boson.useTake(entry.name, tid);
      await reload(opened, tid);
      const edits = swapBase(d.takes, d.spec.chosen);
      say(`${what}: the scene stands on take ${tid}, so the next Swap edits it.` +
        (edits && edits.id !== tid ? ` (Swap still edits take ${edits.id}: a newer shoot.)` : ""), "ok");
    } catch (e) { tell(refusal(e), actions); }
  }

  /** Remove this slot (one made from the frame): part of the base again, one commit, every take stays. */
  async function removeSlot(id) {
    try {
      await boson.removeSlot(entry.name, id);
      opened = null; from.delete(id); picked.delete(id); made.delete(id);
      await reload();
      say(`The ${slotWords(id)} is part of the picture again, not a slot. Every take stays.`, "ok");
    } catch (e) { tell(refusal(e), actions); }
  }

  // ---- the set: the take large with its slots as HUD boxes, the cast (or the opened slot) beside it ----
  const setRow = el("div", null, view, { className: "bs-set" });
  const left = el("div", null, setRow, { className: "bs-left" });
  const stage = el("figure", null, left, { className: "bs-stage" });
  const side = el("aside", null, setRow, { className: "bs-side" });

  // ---- takes timeline (under the picture), clips, motion ----
  el("h2", "Takes", left, { className: "b-h2" });
  const line = el("div", null, left, { className: "bs-line", role: "list" });
  const clipBox = el("section", null, view);
  const motion = el("section", null, view);

  /** Place a HUD tag at its spot (tagSpot): from the shape's left, or its right edge in the picture's right half. */
  const hang = (tag, [x, y, below, right]) => {
    if (right == null) tag.style.left = `${x * 100}%`; else tag.style.right = `${(1 - right) * 100}%`;
    tag.style.top = `${y * 100}%`;
    if (below) tag.classList.add("bs-below");
  };

  /** The open slot's tag never covers another slot's tag or box when a spot avoids it (beats 4-6): tried above, below,
   *  then inside its own shape; the spot covering least wins (another tag counts more than a box). */
  function clear(tag, g, pic) {
    const R = (e) => e.getBoundingClientRect();
    const hit = (a, b) => Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) * Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
    const tags = [...pic.querySelectorAll(".bs-tag")].filter((t) => t !== tag).map(R);
    const boxes = [...pic.querySelectorAll(".bs-slot, .bs-anchor")].filter((x) => x !== g).map(R);
    const top = tag.style.top, gb = R(g), pb = R(pic);
    const spots = [[top, tag.classList.contains("bs-below")], [`${((gb.bottom - pb.top) / pb.height) * 100}%`, true], [`${((gb.top - pb.top) / pb.height) * 100}%`, true]];
    let best = null;
    for (const [y, below] of spots) {
      tag.style.top = y; tag.classList.toggle("bs-below", below);
      const r = R(tag);
      const cost = 4 * tags.reduce((a, t) => a + hit(r, t), 0) + boxes.reduce((a, b) => a + hit(r, b), 0) + (r.bottom > pb.bottom || r.top < pb.top ? 1e9 : 0);
      if (!best || cost < best[0]) best = [cost, y, below];
      if (!cost) break;
    }
    tag.style.top = best[1]; tag.classList.toggle("bs-below", best[2]);
  }

  function drawStage() {
    stage.replaceChildren();
    if (!current) { el("p", "No takes yet: Shoot the first one.", stage, { className: "b-meta" }); return; }
    const pic = el("div", null, stage, { className: "bs-pic" });
    const parentOf = (t) => (t?.op === "swap" ? d.takes.find((x) => x.id === t.parent) : null);
    const edited = parentOf(current);                  // the take this swap edited
    let first = edited;                                // the take the chain of swaps started from (its shoot)
    for (let p = parentOf(first); p; p = parentOf(p)) first = p;
    const before = sinceFirst && first ? first : edited;
    if (before) el("img", null, pic, { src: before.image, alt: `take ${before.id}`, className: "bs-before" });
    const after = el("img", null, pic, { src: current.image, alt: `take ${current.id}`, className: "bs-after" });
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 1 1"); svg.setAttribute("preserveAspectRatio", "none"); svg.classList.add("bs-hud");
    pic.appendChild(svg);
    try {                                                // the slot boxes pulse once, on a scene's first visit
      const k = `boson-pulsed-${entry.name}`;
      if (!sessionStorage.getItem(k)) { sessionStorage.setItem(k, "1"); svg.classList.add("bs-pulse"); }
    } catch { /* no session storage: no pulse */ }
    const placed = [];
    let openTag = null;
    for (const sh of slotShapes(slots, current)) {
      const g = document.createElementNS(NS, "g");
      g.classList.add("bs-slot"); g.dataset.slot = sh.id;
      if (sh.swapped) g.classList.add("bs-swapped");
      if (sh.id === opened) g.classList.add("bs-open");
      for (const [x, y, w, h] of sh.rects) {
        const r = document.createElementNS(NS, "rect");
        Object.entries({ x, y, width: w, height: h }).forEach(([k, v]) => r.setAttribute(k, v));
        g.appendChild(r);
      }
      for (const q of sh.quads) {
        const p = document.createElementNS(NS, "polygon");
        p.setAttribute("points", q.map((pt) => pt.join(",")).join(" "));
        g.appendChild(p);
      }
      for (const s of g.children) s.setAttribute("vector-effect", "non-scaling-stroke");
      svg.appendChild(g);
      const spot = tagSpot(sh, placed);
      const tag = el("button", null, pic, { type: "button", className: "bs-tag" + (sh.swapped ? " bs-swapped" : "") + (sh.id === opened ? " bs-open" : "") });
      hang(tag, spot);
      tag.dataset.slot = sh.id;
      el("b", sh.role, tag);
      el("span", ` · ${sh.studio} studio${sh.kind === "flat" ? " · flat" : ""}${sh.swapped ? " · swapped in this take" : ""}`, tag);
      const hot = (on) => { g.classList.toggle("bs-hot", on); tag.classList.toggle("bs-hot", on); };
      if (sh.id === opened) openTag = [tag, g];
      for (const t of [g, tag]) {
        t.addEventListener("mouseenter", () => hot(true));
        t.addEventListener("mouseleave", () => hot(false));
        t.addEventListener("click", () => openSlot(sh.id));
      }
      const title = document.createElementNS(NS, "title");
      title.textContent = `${sh.role}: ${sh.studio} studio. Click to open.`;
      g.appendChild(title);
    }
    for (const a of anchorShapes(d.spec.base, current, slots)) {   // the base's own things: click one to make it a slot
      const g = document.createElementNS(NS, "g");
      g.classList.add("bs-anchor"); g.dataset.anchor = a.name;
      if (`anchor:${a.name}` === opened) g.classList.add("bs-open");
      const [x, y, w, h] = a.rect;
      const r = document.createElementNS(NS, "rect");
      Object.entries({ x, y, width: w, height: h }).forEach(([k, v]) => r.setAttribute(k, v));
      r.setAttribute("vector-effect", "non-scaling-stroke");
      g.appendChild(r);
      svg.appendChild(g);
      const tag = el("button", null, pic, { type: "button", className: "bs-tag bs-atag" + (`anchor:${a.name}` === opened ? " bs-open" : "") });
      hang(tag, tagSpot({ rects: [a.rect], quads: [] }, placed));
      el("b", a.name, tag);
      el("span", " · part of the base · make it a slot", tag);
      const hot = (on) => { g.classList.toggle("bs-hot", on); tag.classList.toggle("bs-hot", on); };
      for (const e of [g, tag]) {
        e.addEventListener("mouseenter", () => hot(true));
        e.addEventListener("mouseleave", () => hot(false));
        e.addEventListener("click", () => openAnchor(a));
      }
    }
    if (openTag) clear(...openTag, pic);
    if (before) {                                        // before/after: drag right to show the take it edited
      const cmp = el("div", null, stage, { className: "bs-compare" });
      const bar = el("i", null, pic, { className: "bs-divider" });
      if (first !== edited)                              // compare with the last edit only, or with every swap since the shot
        el("button", sinceFirst ? `last swap only (take ${edited.id})` : `every swap since take ${first.id}`, cmp, {
          type: "button", className: "b-btn bs-inline bs-since",
          title: sinceFirst ? `compare with take ${edited.id}, the take this swap edited`
                            : `compare with take ${first.id}, the take every swap since started from`,
          onclick: () => { sinceFirst = !sinceFirst; drawStage(); } });
      el("span", `before: take ${before.id}`, cmp);
      const range = el("input", null, cmp, { type: "range", min: 0, max: 100, value: 0, step: 0.5,
        title: `drag to compare take ${current.id} with take ${before.id}, ${before === edited ? "the take it edited" : "the take its swaps started from"}`,
        ariaLabel: `compare with take ${before.id}` });
      el("span", `after: take ${current.id}`, cmp);
      const at = () => { after.style.clipPath = `inset(0 0 0 ${range.value}%)`; bar.style.left = `${range.value}%`; bar.hidden = Number(range.value) === 0; };
      range.oninput = at; at();
    }
    const cap = el("figcaption", null, stage, { className: "bs-prov bs-takecap" });
    el("span", takeProvenance(current, d.takes), cap);
    const on = chosen();
    if (current === on) el("span", " · the take the scene stands on", cap);
    else el("span", ` · ${Number(current.id) < Number(on?.id) ? "an older take" : "a take"}: viewing only`, cap);
    if (current !== on)
      el("button", "Use this take", cap, { type: "button", className: "b-btn bs-inline", title: "the scene stands on this take again and the next Swap edits it (one commit, nothing deleted)",
        onclick: () => useTake(current.id, "Use this take") });
    else if (current.op === "swap" && edited)
      el("button", `Undo swap (back to take ${edited.id})`, cap, { type: "button", className: "b-btn bs-inline",
        title: `the scene stands on take ${edited.id} again; take ${current.id} stays in the history`, onclick: () => useTake(edited.id, "Undo swap") });
    const det = el("details", null, cap, { className: "bs-details bs-inline" });
    el("summary", "details", det);
    el("span", takeDetails(current, d.sha), det);
  }

  // the cast: one row per slot (what fills it in this take); a click opens the slot
  function drawCast() {
    side.replaceChildren();
    el("h2", "Cast", side, { className: "b-h2 bs-first" });
    el("p", "Each slot is filled by its own studio. Click a box on the picture, or a row.", side, { className: "b-meta" });
    const inTake = new Map(Object.entries(current?.cast ?? {}));
    for (const s of slots) {
      const piece = inTake.get(s.id) ?? s.piece;
      const b = el("button", null, side, { type: "button", className: "bs-castrow", onclick: () => openSlot(s.id) });
      b.dataset.slot = s.id;
      el("img", null, b, { src: boson.pieceUrl(piece), alt: s.role, loading: "lazy" });
      const t = el("span", null, b);
      el("b", s.role, t);
      el("small", `${s.studio} studio${(current?.swapped ?? []).includes(s.id) ? " · swapped" : ""}`, t);
      if (isPrivatePiece(piece)) el("small", PRIVATE_LABEL, t, { className: "b-private" });
    }
    const pend = pendingCasts();
    if (pend.length) el("p", `Ready to swap: ${pend.map((c) => slotWords(c.slot)).join(", ")}. Press Swap to make the new take, or Uncast.`, side, { className: "bs-pending" });
    nextTake(side);
  }

  /** Casts on the graph the scene does not hold yet (a cast a take already committed is not pending). */
  function pendingCasts() {
    try { return (canvasApp()?.graph ? boson.graphState() : []).filter((c) => slots.find((s) => s.id === c.slot)?.piece !== c.piece); }
    catch { return []; }
  }
  /** After a commit: Cast widgets still holding what the scene now holds are cleared (casting the same piece again
   *  changes nothing, so the next swap's request is the same either way). */
  function clearCommitted() {
    try {
      if (!canvasApp()?.graph) return;
      for (const c of boson.graphState()) if (slots.find((s) => s.id === c.slot)?.piece === c.piece) boson.uncast(c.slot);
    } catch { /* no scene graph in the canvas: nothing to clear */ }
  }
  /** "Swap 2: car, outfit", and which take it edits when that is not the one on screen. */
  const swapLabel = (list) => {
    const edits = swapBase(d.takes, d.spec.chosen);
    return (list.length ? `Swap${list.length > 1 ? ` ${list.length}` : ""}: ${list.map(slotWords).join(", ")}` : "Swap") +
      (edits && edits.id !== current?.id ? ` (edits take ${edits.id})` : "");
  };
  /** The live switch's state next to a button with no ready badge of its own: stored is free; live names the spend. */
  const costLine = (parent, spend) => el("span", live ? `live calls on · ${spend}` : "off: replays what was made before, free", parent, { className: "bs-ready" });

  function nextTake(parent) {
    el("h2", "Next take", parent, { className: "b-h2" });
    const take = el("textarea", null, parent, { placeholder: "the day: hour, weather, street life", rows: 2, className: "b-input bs-wide" });
    const row = el("div", null, parent, { className: "bs-spend" });
    spendButton(row, "Shoot", SHOOT_COST, () => boson.shoot({ take: take.value }), "off on this page: a Shoot re-renders the whole set");
    const row2 = el("div", null, parent, { className: "bs-spend" });
    const staged = pendingCasts().map((c) => c.slot);
    const all = el("button", swapLabel(staged), row2, { type: "button", className: "b-btn", disabled: !staged.length,
      title: staged.length ? `applies every staged cast in one edit: ${staged.map(slotWords).join(", ")}` : "pick a piece for a slot and press Cast first" });
    all.onclick = () => go(`Swap${staged.length ? ` ${staged.map(slotWords).join(", ")}` : ""}${live ? "" : " (stored)"}`, async () => {
      await sceneGraph();
      return boson.swap(undefined, undefined, undefined, { live });
    }, { busy: all });
    if (!staged.length) el("span", "nothing staged yet: open a slot, pick a piece, press Cast", row2, { className: "b-why" });
    costLine(row2, SWAP_COST);
    const edits = swapBase(d.takes, d.spec.chosen);
    el("p", `A Swap is one edit of take ${edits?.id ?? "-"}; with live calls off it only replays ` +
      "what was made before.", parent, { className: "b-meta" });
  }

  async function slotStudio(name) {
    studios ??= await boson.studios();
    shelf ??= await boson.shelf();
    if (!studioCache.has(name)) {
      const row = studios.find((x) => x.name === name);
      studioCache.set(name, row && !row.error ? boson.studio(row.repo).then((s) => ({ ...s, repo: row.repo })) : Promise.resolve(null));
    }
    return studioCache.get(name);
  }

  /** The scene graph in the canvas (Cast nodes), reloaded if the motion graph replaced it. */
  async function sceneGraph() {
    const app = await graphReady();
    await boson.ensureScene(repo, wf, { casts: true });
    await boson.syncScene(repo, slots.map((s) => s.id));
    frameGraph(app);
  }

  /** Something the base shows (an anchor): what it is, and Make it a slot (Add Slot: a commit, no call). */
  async function openAnchor(a) {
    opened = `anchor:${a.name}`;
    drawStage();
    side.replaceChildren();
    const head = el("div", null, side, { className: "bs-head" });
    el("h2", `${a.name} · part of the base`, head, { className: "b-h2 bs-first" });
    el("button", "Close", head, { type: "button", className: "b-btn", onclick: () => { opened = null; drawStage(); drawCast(); } });
    el("p", `${a.desc}. It belongs to the base view (${base.studio} studio). Make it a slot and any studio can make its own version for this spot.`, side, { className: "b-meta" });
    const noun = el("input", null, side, { className: "b-input bs-wide", placeholder: "what it is, e.g. the corner building", value: "" });
    const where = el("input", null, side, { className: "b-input bs-wide", placeholder: "where it stands, e.g. on the left corner of the street" });
    const fromRow = el("div", null, side, { className: "bs-head" });
    el("h2", "Filled by", fromRow, { className: "b-h2" });
    const pickStudio = el("select", null, fromRow, { className: "b-input bs-studio" });
    studios ??= await boson.studios();
    const sel = () => studiosFor({ id: "", short: noun.value || a.name, studio: "" }, studios);
    const fill = () => { const v = pickStudio.value; pickStudio.replaceChildren();
      for (const x of sel()) el("option", `${x.name} studio${x.field ? ` · ${x.field}` : ""}${x.fits ? "" : " (other field)"}`, pickStudio, { value: x.name, selected: x.name === v }); };
    fill();
    noun.onchange = fill;
    const row = el("div", null, side, { className: "bs-spend" });
    const mk = el("button", "Make it a slot", row, { type: "button", className: "b-btn b-primary" });
    mk.onclick = () => {
      if (!noun.value.trim()) return say("say what it is first (the corner building)", "error");
      const slot = slotIdFor(noun.value, slots);
      go(`Make ${a.name} a slot`, async () => {
        await sceneGraph();
        return boson.addSlot({ anchor: a.name, slot, noun: noun.value.trim(), studio: pickStudio.value, where: where.value.trim() });
      }, { busy: mk, then: () => reload(slot) });
    };
    el("span", "free, makes no picture", row, { className: "b-cost" });
  }

  async function openSlot(id) {
    opened = id;
    drawStage();
    const s = slots.find((x) => x.id === id);
    side.replaceChildren();
    const head = el("div", null, side, { className: "bs-head" });
    el("h2", `${s.role} · ${s.studio} studio`, head, { className: "b-h2 bs-first" });
    el("button", "Close", head, { type: "button", className: "b-btn", onclick: () => { opened = null; drawStage(); drawCast(); } });
    const src = from.get(id) ?? s.studio;
    const steps = el("ol", null, side, { className: "bs-steps" });
    const stepEls = STEPS.map((w, i) => el("li", `${i + 1} ${w}`, steps));
    const lightStep = () => {
      const k = stepOf({ studio: from.has(id) || (made.get(id)?.studio === src), piece: picked.has(id) });
      stepEls.forEach((x, i) => { x.classList.toggle("bs-done", i + 1 < k); x.classList.toggle("bs-now", i + 1 === k); });
    };
    lightStep();
    el("p", s.desc ?? s.place?.line ?? "", side, { className: "b-meta" });
    if (s.from && s.piece === basePiece) {               // made from the frame here, still the base's pixels: the way back out
      const rmRow = el("div", null, side, { className: "bs-spend" });
      el("button", "Remove this slot", rmRow, { type: "button", className: "b-btn", onclick: () => removeSlot(id),
        title: `the ${slotWords(id)} becomes part of the picture again, as before you made it a slot; every take stays` });
      el("span", "part of the picture again · free", rmRow, { className: "bs-ready" });
    } else if (s.from)                                   // its own piece is in the take the scene stands on (N11)
      el("p", `The ${s.short ?? slotWords(id)} with ${pieceName(s.piece)} stays in the picture until you Undo or swap it, ` +
        "so this slot can be removed once it shows the base photo again.", side, { className: "b-meta" });

    const inTake = current?.cast?.[id] ?? s.piece;
    el("h2", `In take ${current?.id ?? "-"}`, side, { className: "b-h2" });
    piecePanel(side, inTake);
    const pend = pendingCasts().find((c) => c.slot === id);
    if (pend) {
      const pp = pieceParts(pend.piece);
      const row = el("p", `Staged for the next swap: ${pieceName(pend.piece)}${pp.studio ? ` (${pp.studio} studio)` : ""} `, side, { className: "bs-pending", title: pend.piece });
      el("button", "Uncast", row, { type: "button", className: "b-btn bs-inline", onclick: () => actions.uncast(id) });
    }

    const fromRow = el("div", null, side, { className: "bs-head" });
    el("h2", "From", fromRow, { className: "b-h2" });
    const pickStudio = el("select", null, fromRow, { className: "b-input bs-studio", title: "any studio can fill this slot; the ones whose field fits come first" });
    el("option", `${src} studio`, pickStudio, { value: src });
    pickStudio.disabled = true;
    const shelfBox = el("div", null, side, { className: "bs-pieces" });
    fitShelf = () => {                                   // two whole rows in view, never a row cut mid-picture
      const t = shelfBox.querySelectorAll(".bs-piece")[8];
      shelfBox.style.maxHeight = t ? `${t.offsetTop - shelfBox.offsetTop - 4}px` : "none";
    };
    el("p", "reading the studio...", shelfBox, { className: "b-meta" });

    const spot = el("div", null, side, { className: "bs-spot" });
    const idea = el("textarea", null, spot, { rows: 2, className: "b-input bs-wide",
      placeholder: `your idea for ${s.noun ?? id} (optional; the studio makes it for this spot)` });
    idea.value = made.get(id)?.idea ?? "";
    const makeRow = el("div", null, spot, { className: "bs-spend" });
    const makeBtn = el("button", `Make 4 for this spot`, makeRow, { type: "button", className: "b-btn",
      title: `the ${src} studio makes 4 for this spot, from a crop of take ${current?.id}` });
    const makeTag = el("span", makeBadge(undefined).text, makeRow, { className: "bs-ready" });
    makeBtn.onclick = () => go(`Make 4: ${src} for the ${s.short ?? slotWords(id)} spot in take ${current.id}${live ? "" : " (stored)"}`, async () => {
      await sceneGraph();
      return boson.commissionNew(entry.name, current.id, id, { studio: src, idea: idea.value, live });
    }, { busy: makeBtn, then: (o) => {
      studioCache.delete(src); readyCache.clear();
      if (o && o.tone !== "error") made.set(id, { studio: src, take: current.id, idea: idea.value });
      if (opened === id) openSlot(id);
    } });

    const tiles = new Map();                             // piece -> its shelf tile
    const pick = el("div", null, side, { className: "bs-pickbox" });
    const pickRow = el("div", null, pick, { className: "bs-pickrow" });
    const pickImg = el("img", null, pickRow, { alt: "", hidden: true });
    const pickLine = el("p", null, pickRow, { className: "bs-picked" });
    const note = el("p", null, pick, { className: "bs-note", hidden: true });
    const row = el("div", null, pick, { className: "bs-pick" });
    const det = el("details", null, pick, { className: "bs-details" });
    el("summary", "details", det);
    const inp = el("input", null, det, { value: picked.get(id) ?? inTake, className: "b-input bs-wide", title: `the piece for ${slotWords(id)}, as Boson stores it` });
    const castIt = async () => {
      await sceneGraph();
      const here = castSlots(canvasApp().graph);
      if (!here.includes(id)) throw new Error(`This scene's graph can't swap the ${slotWords(id)} yet (it has: ${here.map(slotWords).join(", ") || "nothing"}). Reopen the scene.`);
      return boson.cast(id, inp.value);
    };
    const castBtn = el("button", "Cast", row, { type: "button", className: "b-btn", title: "stage this piece for the next Swap: free, nothing is made until you press Swap" });
    castBtn.onclick = () => acted(async () => {
      await castIt();
      openSlot(id);
      return `${slotWords(id)}. Press Swap to make the new take, or Uncast.`;
    }, "Ready to swap");
    const others = pendingCasts().map((c) => c.slot).filter((x) => x !== id);
    const swapBtn = el("button", swapLabel(others.length ? [id, ...others] : []), row, { type: "button", className: "b-btn b-primary",
      title: `Cast, then one edit of the take the scene stands on: the whole frame re-rendered, relit, the rest kept (${SWAP_COST})` +
        (others.length ? `. Also staged, so this Swap applies them too: ${others.map(slotWords).join(", ")}` : "") });
    swapBtn.onclick = () => go(`Swap ${[id, ...others].map(slotWords).join(", ")} with ${pieceParts(inp.value).studio || "this piece"}${live ? "" : " (stored)"}`, async () => {
      await castIt();
      return boson.swap(undefined, undefined, undefined, { live });
    }, { busy: swapBtn, then: (o) => {
      // nothing made: the cast this click set is undone (a cast staged before, with Cast, stays), so a miss never rides
      // along on the next Swap
      if (!o?.take && !pend) try { boson.uncast(id); } catch { /* no scene graph */ }
      return reload(id, o?.take);
    } });
    const swapTag = el("span", null, row, { className: "bs-ready" });

    let rd = null;                                       // the ready read, once it lands
    const readyOf = (piece) => rd ? (rd.swaps.find((x) => x.piece === piece) ?? { error: "not asked" }) : null;
    const showPick = () => {
      const piece = inp.value.trim(), pp = pieceParts(piece);
      const b = piece === inTake ? { state: "same", text: "already in this take" } : swapBadge(readyOf(piece), live);
      pickLine.textContent = `${piece === inTake ? "In this take" : "Picked"}: ${pieceName(piece)}${pp.studio ? ` · ${pp.studio} studio` : ""}`;
      pickImg.hidden = piece === inTake || !piece;       // the picked piece itself (the take's own is shown above)
      if (!pickImg.hidden) { pickImg.src = tiles.get(piece)?.querySelector("img")?.src ?? boson.pieceUrl(piece); pickImg.alt = pieceName(piece); }
      const idle = b.state === "same" && !others.length;
      swapBtn.textContent = idle ? "Already in this take" : swapLabel(others.length ? [id, ...others] : []);
      swapBtn.classList.toggle("b-primary", !idle); swapBtn.disabled = idle;
      swapTag.textContent = idle ? "" : b.text; swapTag.dataset.state = b.state;
      note.replaceChildren(); note.hidden = !["live", "later", "maybe"].includes(b.state);
      if (!note.hidden) {
        const base = swapBase(d.takes, d.spec.chosen)?.id ?? "-";
        const why = b.state === "later" ? `${pieceName(piece)} was made on a later take: it replays once ${b.after} is done, so make that swap first. `
          : b.state === "maybe" ? `${pieceName(piece)} was swapped in before, but Boson may need one look to find the slots in that picture. `
          : readyOf(piece)?.stored ? `${pieceName(piece)} was swapped in before, but Boson never found this scene's current slots in that picture on this box. `
          : `${pieceName(piece)} was never swapped into take ${base} on this box, so there is nothing stored to replay. `;
        el("span", why + (keyless && !live ? KEYLESS : live ? `Swap makes it now: ${b.cost}.`
          : `With live calls on, Swap makes it now: ${b.cost}.${b.state === "live" ? " Or pick one marked ready." : ""}`), note);
        if (!live && !keyless) el("button", "Turn on live calls", note, { type: "button", className: "b-btn bs-inline", onclick: actions.live.run });
      }
      lightStep();
    };
    inp.onchange = () => { picked.set(id, inp.value.trim()); showPick(); };
    showPick();
    nextTake(side);

    try {
      studios ??= await boson.studios();
      if (opened !== id) return;
      pickStudio.replaceChildren();
      for (const x of studiosFor(s, studios))
        el("option", `${x.name} studio${x.field ? ` · ${x.field}` : ""}${x.fits ? "" : " (other field)"}`, pickStudio, { value: x.name, selected: x.name === src });
      pickStudio.disabled = false;
      pickStudio.onchange = () => { from.set(id, pickStudio.value); picked.delete(id); openSlot(id); };
      const st = await slotStudio(src);
      if (opened !== id) return;
      let list = castable(st, shelf, src);
      const drawShelf = () => {
        shelfBox.replaceChildren(); tiles.clear();
        if (!list.length) el("p", `no ${src} pieces on this box yet: Make 4 for this spot`, shelfBox, { className: "b-meta" });
        for (const p of list) {
          const b = el("button", null, shelfBox, { type: "button", className: "bs-piece" + (p.piece === inTake ? " bs-current" : "") +
            (p.piece === picked.get(id) ? " bs-chosen" : "") + (p.made ? " bs-made" : "") });
          b.title = [pieceName(p.piece), p.made ? "made for this spot" : "", p.kept ? "kept on the shelf" : "", p.make ? `made for: ${p.make}` : ""].filter(Boolean).join("\n");
          el("img", null, b, { src: p.image ?? (p.file && st?.repo ? boson.plateUrl(st.repo, p.file) : boson.pieceUrl(p.piece)), alt: pieceName(p.piece), loading: "lazy" });
          if (p.kept) el("small", "kept", b);
          b.onclick = () => { inp.value = p.piece; picked.set(id, p.piece); for (const x of shelfBox.children) x.classList.toggle("bs-chosen", x === b); showPick();
            const r = row.getBoundingClientRect(), sr = side.getBoundingClientRect();   // Swap in view right after a pick (N15):
            if (r.bottom > sr.bottom) side.scrollBy({ top: r.bottom - sr.bottom + 8, behavior: "smooth" }); };   // the panel only, never the page
          tiles.set(p.piece, b);
        }
        if (list.some((p) => p.made)) shelfBox.prepend(el("p", `made for this spot (take ${made.get(id)?.take}), first:`, null, { className: "bs-madenote" }));
        fitShelf();
      };
      drawShelf();
      const ask = async (pieces) => {                    // what replays with no call, for these pieces (and every Make)
        const k = JSON.stringify([d.sha, current.id, id, idea.value, pieces]);
        if (!readyCache.has(k)) readyCache.set(k, boson.ready(entry.name, current.id, id, { words: idea.value, pieces }).catch((e) => { readyCache.delete(k); throw e; }));
        return readyCache.get(k);
      };
      const wanted = [...new Set([inTake, inp.value.trim(), ...list.map((p) => p.piece)].filter(Boolean))];
      rd = await ask(wanted);
      if (opened !== id || !shelfBox.isConnected) return;
      const mine = made.get(id), m = rd.makes?.find((x) => x.studio === src);
      if (mine?.studio === src && mine.take === current.id && m?.pieces?.length) {
        list = madeFirst(list, m.pieces);
        const more = list.filter((p) => p.made && !rd.swaps.some((x) => x.piece === p.piece)).map((p) => p.piece);
        if (more.length) { const r2 = await ask(more); rd = { ...rd, swaps: [...rd.swaps, ...r2.swaps] }; }
        if (opened !== id || !shelfBox.isConnected) return;
        drawShelf();
      }
      const mb = makeBadge(m ?? null, live);
      makeTag.textContent = mb.text; makeTag.dataset.state = mb.state;
      let any = mb.state === "ready";
      for (const [piece, b] of tiles) {
        const r = piece === inTake ? { state: "same", short: "in take", text: "already in this take" } : swapBadge(readyOf(piece), live);
        if (r.short) el("small", r.short, b, { className: "bs-badge" }).dataset.state = r.state;
        b.title += `\n${r.text}`;
        any ||= r.state === "ready";
      }
      showPick();
      const fresh = (current?.swapped ?? []).includes(id);   // just swapped in: the take answers it, no hint
      if (!any && !live && !fresh) {                     // a shelf of "live" alone never stands without a hint
        const hint = el("p", "checking the other studios…", null, { className: "bs-hint" });
        shelfBox.before(hint);
        const there = await elsewhere(s, src, rd, ask).catch(() => null);
        if (opened !== id || !hint.isConnected) return;
        hint.replaceChildren(document.createTextNode(there
          ? `Nothing from the ${src} studio replays here at take ${current.id}; the ${there.studio} studio's ${there.what} does. `
          : `Nothing for the ${s.short ?? slotWords(id)} replays at take ${current.id} from any studio on this box: each piece needs live calls.`));
        if (there) el("button", `Show ${there.studio}`, hint, { type: "button", className: "b-btn bs-inline",
          onclick: () => { from.set(id, there.studio); picked.delete(id); openSlot(id); } });
      }
    } catch (e) {
      if (!shelfBox.isConnected) return;
      if (rd) return;
      if (!tiles.size) shelfBox.replaceChildren(el("p", `could not read ${src}: ${e.message ?? e}`, null, { className: "b-meta" }));
      makeTag.textContent = "can't tell if it is stored"; makeTag.dataset.state = "unknown";
    }
  }

  /** The first fitting studio with something that replays for this slot at this take: its stored Make for the spot,
   *  else a piece on its shelf. -> {studio, what} or null. */
  async function elsewhere(s, src, rd, ask) {
    const others = studiosFor(s, studios).filter((x) => x.name !== src && x.fits);
    const mk = (rd.makes ?? []).find((x) => x.stored && others.some((o) => o.name === x.studio));
    if (mk) return { studio: mk.studio, what: "Make 4 for this spot" };
    const lists = await Promise.all(others.map(async (o) => [o.name, castable(await slotStudio(o.name), shelf, o.name).map((p) => p.piece)]));
    const by = new Map(lists.flatMap(([n, ps]) => ps.map((p) => [p, n])));
    if (!by.size) return null;
    const hit = (await ask([...by.keys()])).swaps.find((x) => swapBadge(x).state === "ready");
    return hit ? { studio: by.get(hit.piece), what: `${pieceName(hit.piece)}` } : null;
  }

  function piecePanel(parent, piece) {
    const f = el("figure", null, parent, { className: "bs-piecefig" });
    el("img", null, f, { src: boson.pieceUrl(piece), alt: pieceName(piece) });
    const pp = pieceParts(piece);
    const cap = el("figcaption", null, f, { className: "bs-prov" });
    el("span", `${pieceName(piece)}${pp.studio ? ` · ${pp.studio} studio` : ""}`, cap, { className: "bs-name" });
    if (pp.private) el("span", ` · ${PRIVATE_LABEL}`, cap, { className: "b-private" });
    const det = el("details", null, cap, { className: "bs-details" });
    el("summary", "details", det);
    el("span", `${pp.studio}@${pp.sha} · ${pp.path}`, det);
  }

  function drawLine() {
    line.replaceChildren();
    const clipTakes = new Set(clips.map((c) => c.take));
    for (const t of d.takes) {
      const b = el("button", null, line, { type: "button", className: "bs-take" + (t.id === current?.id ? " bs-current" : ""), role: "listitem" });
      b.dataset.take = t.id;
      el("img", null, b, { src: t.image, alt: `take ${t.id}`, loading: "lazy" });
      el("small", takeLine(t) + (clipTakes.has(t.id) ? " · clip" : ""), b);
      b.title = takeProvenance(t, d.takes) + ((t.swapped ?? []).length ? `\nswapped: ${t.swapped.map(slotWords).join(", ")}` : "");
      b.onclick = () => { current = t; drawAll(); };
    }
    fitLine();
  }
  /** The take strip shows whole thumbnails only: as many as fit, sized to fill the row, scrolled (not the page) so
   *  the current take is the last whole one in view, or the first page when it fits there. */
  function fitLine() {
    const tiles = [...line.children], w = line.clientWidth;
    if (!tiles.length || !w) return;
    const gap = parseFloat(getComputedStyle(line).columnGap) || 8, min = 7.5 * (parseFloat(getComputedStyle(document.documentElement).fontSize) || 16);
    const n = Math.max(1, Math.floor((w + gap) / (min + gap)));
    line.style.setProperty("--bs-take-w", `${(w - (n - 1) * gap) / n}px`);
    const k = Math.max(0, tiles.findIndex((t) => t.classList.contains("bs-current")) - n + 1);
    line.scrollLeft = k * ((w - (n - 1) * gap) / n + gap);
  }
  /** The set fills the first screen, so the clips start below the fold (the view or the window, whichever ends first). */
  function fold() {
    const top = setRow.getBoundingClientRect().top + (view.scrollTop || 0);
    const bottom = Math.min(innerHeight, view.getBoundingClientRect().bottom || innerHeight);
    setRow.style.minHeight = `${Math.max(0, bottom - top)}px`;
  }
  let fitShelf = () => {};                             // the open slot's shelf (openSlot sets it)
  /** The side panel ends where the view does, from where it starts on the page (it starts beside the picture, not at the
   *  top: sized to the window, its lower part, Swap included, sat below the window edge and reaching it scrolled the page). */
  const fitSide = () => {
    const sc = side.closest("#boson-view"); if (!sc || !side.isConnected) return;
    const v = sc.getBoundingClientRect(), top = side.getBoundingClientRect().top + sc.scrollTop - v.top;
    side.style.maxHeight = `${Math.max(320, v.height - top - parseFloat(getComputedStyle(sc).paddingBottom || 0))}px`;
  };
  if (typeof window !== "undefined") window.addEventListener("resize", () => { if (line.isConnected) { fitLine(); fitShelf(); fitSide(); fold(); } });
  if (typeof requestAnimationFrame !== "undefined") requestAnimationFrame(fitSide);

  function drawClips() {
    clipBox.replaceChildren();
    el("h2", `Clips of take ${current?.id ?? "-"}`, clipBox, { className: "b-h2" });
    const mine = clips.filter((c) => c.take === current?.id);
    if (!mine.length) {
      const other = [...new Set(clips.map((c) => c.take))];
      el("p", `No clips of this take yet.${other.length ? ` Clips exist for take ${other.join(", ")}.` : " Set it in motion below."}`, clipBox, { className: "b-meta" });
    }
    const grid = el("div", null, clipBox, { className: "bs-clips" });
    for (const c of mine) {
      const f = el("figure", null, grid, { className: "b-card bs-clip" });
      el("video", null, f, { src: c.video ?? boson.clipUrl(repo, c.id), controls: true, muted: true, loop: true, playsInline: true, preload: "metadata" });
      const cap = el("figcaption", null, f, { className: "bs-prov" });
      el("span", `clip ${c.id} · from take ${c.take}${rendererName(c.renderer) ? ` · made with ${rendererName(c.renderer)}` : ""}`, cap, { title: takeDetails(c, d.sha) });
      const words = el("details", null, f, { className: "bs-details bs-words" });
      el("summary", "the words it was set in motion with", words);
      el("q", c.prompt, words);
    }
  }

  function drawMotion() {
    motion.replaceChildren();
    el("h2", "Set in motion", motion, { className: "b-h2" });
    el("p", `Take ${current?.id ?? "-"} moved by your words: Load Scene, Load Take, Comfy's Gemini Omni (Video), Commit Clip. ` +
      "Loading the graph costs nothing; queueing it makes one clip.", motion, { className: "b-meta" });
    const words = el("textarea", null, motion, { rows: 2, className: "b-input bs-wide",
      placeholder: "how it moves: the tram pulls away, the woman turns to watch it; a 6-second clip" });
    const row = el("div", null, motion, { className: "bs-spend" });
    const status = el("p", null, motion, { className: "b-meta" });
    const load = el("button", "Load the motion graph", row, { type: "button", className: "b-btn b-primary" });
    const queueBtn = spendButton(row, "Queue", MOTION_COST, () => canvasApp().queuePrompt(0, 1), "off on this page: load the graph, then Run it in the canvas");
    queueBtn.classList.add("bs-queue");
    load.onclick = () => acted(async () => {
      if (!words.value.trim()) throw new Error("say how it moves first (and how long: a 6-second clip)");
      const m = await boson.motion(repo, current.id, words.value.trim());
      await graphReady();
      await boson.loadMotion(m.graph, `motion-${d.name}-${current.id}`);
      frameGraph();
      status.replaceChildren();
      el("span", `In the canvas: ${Object.values(m.graph).map((n) => n._meta?.title ?? n.class_type).join(" -> ")}. `, status);
      el("span", m.has_key ? "A Comfy key is on this box. Queue stays off on this page: See the graph, then Run in the canvas spends." : "Queue stays off: no Comfy key on this box.", status);
      el("button", "See the graph", status, { type: "button", className: "b-btn bs-inline", onclick: () => canvasForward(true) });
      el("button", "Back to the set graph", status, { type: "button", className: "b-btn bs-inline", onclick: () => acted(async () => { await sceneGraph(); return wf; }, "set graph") });
      return `motion graph for take ${current.id}`;
    }, "loaded");
  }

  function drawAll() {
    drawMeta();
    drawStage();
    const a = opened?.startsWith("anchor:") ? anchorShapes(d.spec.base, current, slots).find((x) => `anchor:${x.name}` === opened) : null;
    if (a) openAnchor(a); else if (opened && slots.some((s) => s.id === opened)) openSlot(opened); else { opened = null; drawCast(); }
    drawLine(); drawClips(); drawMotion(); fold(); fitSide();
  }
  drawAll();
}

/** set.js styles itself with the theme's variables (theme.css is the frame's): one <style> inside the view. */
export function style(view) {
  el("style", `
    .bs-set { display: grid; grid-template-columns: minmax(0, calc((100vh - 35rem) * 1.8)) minmax(17rem, 1fr); gap: var(--b-s4); align-items: start; margin-top: var(--b-s3); }
    .bs-stage { margin: 0; }
    .bs-left { min-width: 0; }
    .bs-pic { position: relative; border-radius: var(--b-radius); overflow: hidden; background: #000; }
    .bs-pic img { width: 100%; display: block; }
    .bs-hud { position: absolute; inset: 0; width: 100%; height: 100%; }
    .bs-slot rect, .bs-slot polygon { fill: transparent; stroke: rgba(255, 255, 255, 0.8); stroke-width: 1.5; stroke-dasharray: 5 3; cursor: pointer; }
    .bs-slot.bs-swapped rect, .bs-slot.bs-swapped polygon { stroke: var(--b-accent); stroke-dasharray: none; }
    .bs-slot.bs-hot rect, .bs-slot.bs-hot polygon, .bs-slot.bs-open rect, .bs-slot.bs-open polygon { fill: rgba(196, 230, 106, 0.16); stroke: var(--b-accent); stroke-width: 2.5; stroke-dasharray: none; }
    .bs-tag { position: absolute; transform: translateY(calc(-100% - 3px)); border: 0; border-radius: 3px; padding: 1px 6px; cursor: pointer;
      background: rgba(8, 14, 10, 0.72); color: var(--b-text); font: 600 var(--b-fs-xs)/1.4 var(--b-font); white-space: nowrap; }
    .bs-tag.bs-below { transform: translateY(3px); }
    .bs-takecap .bs-details { display: inline; }
    .bs-takecap .bs-details[open] > span { display: block; }
    .bs-tag span { display: none; font-weight: 400; color: var(--b-text-2); }
    .bs-tag.bs-swapped b { color: var(--b-accent); }
    .bs-tag.bs-hot, .bs-tag.bs-open { background: var(--b-accent); color: var(--b-accent-ink); z-index: 2; }
    .bs-tag.bs-hot b, .bs-tag.bs-open b { color: var(--b-accent-ink); }
    .bs-tag.bs-hot span { display: inline; color: var(--b-accent-ink); }
    .bs-prov { font: var(--b-fs-xs)/1.4 var(--b-font); font-variant-numeric: tabular-nums; color: var(--b-text-3); padding: var(--b-s1) 0; overflow-wrap: anywhere; }
    .bs-side { min-width: 0; }
    .bs-side .b-meta { margin: 0 0 var(--b-s2); }
    .bs-first { margin-top: 0; }
    .bs-head { display: flex; justify-content: space-between; align-items: center; gap: var(--b-s2); }
    .bs-castrow { display: grid; grid-template-columns: 3.2rem 1fr; gap: var(--b-s2); align-items: center; width: 100%; margin: 0 0 4px;
      padding: 4px; border: 1px solid transparent; border-radius: var(--b-radius-sm); background: var(--b-surface-2); color: var(--b-text);
      font: inherit; text-align: left; cursor: pointer; }
    .bs-castrow:hover { border-color: var(--b-accent); }
    .bs-castrow img { width: 3.2rem; height: 3.2rem; object-fit: cover; border-radius: 4px; display: block; }
    .bs-castrow span { display: flex; flex-direction: column; min-width: 0; }
    .bs-castrow small { color: var(--b-text-3); font-size: var(--b-fs-xs); }
    .bs-piecefig { margin: 0; }
    .bs-piecefig img { width: 100%; max-height: 14rem; object-fit: contain; background: #000; border-radius: var(--b-radius-sm); display: block; }
    .bs-pieces { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; overflow-y: auto; scroll-snap-type: y mandatory; }
    .bs-pieces > * { scroll-snap-align: start; }
    .bs-hint { margin: 0 0 var(--b-s1); font-size: var(--b-fs-xs); color: var(--b-text-2); }
    .bs-pickrow { display: flex; align-items: center; gap: var(--b-s2); }
    .bs-pickrow img { width: 3.2rem; height: 3.2rem; object-fit: cover; border-radius: 4px; flex: none; }
    .bs-piece { position: relative; padding: 0; border: 2px solid transparent; border-radius: 5px; background: #000; cursor: pointer; }
    .bs-piece img { width: 100%; aspect-ratio: 1; object-fit: cover; display: block; border-radius: 3px; }
    .bs-piece small { position: absolute; left: 2px; bottom: 2px; font-size: 0.6rem; background: rgba(0, 0, 0, 0.7); color: var(--b-text-2); padding: 0 3px; border-radius: 2px; }
    .bs-piece.bs-current { border-color: var(--b-text-3); }
    .bs-piece.bs-chosen, .bs-piece:hover { border-color: var(--b-accent); }
    .bs-pick { display: flex; flex-wrap: wrap; align-items: center; gap: var(--b-s2); margin-top: var(--b-s2); }
    .bs-wide { width: 100%; display: block; min-width: 0; }
    .bs-spend { display: flex; align-items: center; flex-wrap: wrap; gap: var(--b-s1); margin-top: var(--b-s2); }
    .bs-pending { color: var(--b-accent); font-size: var(--b-fs-sm); }
    .bs-line { display: flex; gap: var(--b-s2); overflow-x: auto; padding-bottom: var(--b-s2); scroll-snap-type: x mandatory; }
    .bs-take { flex: 0 0 var(--bs-take-w, 7.5rem); scroll-snap-align: start; padding: 0; border: 2px solid transparent; border-radius: var(--b-radius-sm); background: var(--b-surface-2);
      color: var(--b-text-2); font: inherit; cursor: pointer; text-align: left; overflow: hidden; }
    .bs-take img { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; display: block; }
    .bs-take small { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; padding: 3px 6px; font-size: var(--b-fs-xs);
      line-height: 1.3; min-height: calc(2.6em + 6px); overflow: hidden; overflow-wrap: anywhere; }
    .bs-take:hover { border-color: var(--b-line); }
    .bs-take.bs-current { border-color: var(--b-accent); color: var(--b-text); }
    .bs-clips { display: grid; grid-template-columns: repeat(auto-fill, minmax(20rem, 1fr)); gap: var(--b-s3); }
    .bs-clip video { width: 100%; display: block; background: #000; }
    .bs-clip .bs-prov { padding: var(--b-s1) var(--b-s3) 0; }
    .bs-words { display: block; padding: 0 var(--b-s3) var(--b-s2); color: var(--b-text-2); font-size: var(--b-fs-sm); }
    .bs-words q { display: block; white-space: pre-line; margin-top: var(--b-s1); }
    .bs-inline { margin-left: var(--b-s2); }
    .bs-anchor rect { fill: transparent; stroke: rgba(255, 255, 255, 0.6); stroke-width: 1.2; stroke-dasharray: 3 4; cursor: pointer; }
    .bs-anchor.bs-hot rect, .bs-anchor.bs-open rect { fill: rgba(255, 255, 255, 0.08); stroke: var(--b-text-2); stroke-dasharray: 4 3; }
    .bs-atag { background: rgba(8, 14, 10, 0.72); color: var(--b-text); outline: 1px dashed rgba(255, 255, 255, 0.55); outline-offset: -1px; }
    .bs-atag b::after { content: " +"; color: var(--b-accent); }
    .bs-live { display: inline-flex; align-items: center; gap: var(--b-s2); font-size: var(--b-fs-sm); color: var(--b-text-2); cursor: pointer; }
    .bs-live b { color: var(--b-text); font-weight: 600; }
    .bs-live input { appearance: none; -webkit-appearance: none; margin: 0; width: 2.1rem; height: 1.15rem; border-radius: 1rem;
      background: var(--b-surface-2); border: 1px solid var(--b-line); position: relative; cursor: pointer; flex: none; }
    .bs-live input::after { content: ""; position: absolute; top: 1px; left: 1px; width: calc(1.15rem - 4px); height: calc(1.15rem - 4px);
      border-radius: 50%; background: var(--b-text-3); transition: left 0.15s; }
    .bs-live input:checked { background: var(--b-cost); border-color: var(--b-cost); }
    .bs-live input:checked::after { left: calc(100% - 1.15rem + 3px); background: #fff; }
    .bs-live input:focus-visible { outline: 2px solid var(--b-accent); outline-offset: 2px; }
    .bs-head:has(> .bs-studio) { flex-wrap: wrap; }
    .bs-studio { max-width: 100%; font-size: var(--b-fs-sm); }   /* a long field drops to its own line, never cut (T7) */
    .bs-spot { margin-top: var(--b-s2); }
    .bs-left { position: sticky; top: 0; }
    .bs-left > .b-h2 { margin-top: var(--b-s3); }
    .bs-side { position: sticky; top: 0; max-height: calc(100vh - 12rem); overflow-y: auto; overscroll-behavior: contain; padding-right: 4px; }
    .bs-pic .bs-before { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
    .bs-pic .bs-after { position: relative; }
    .bs-divider { position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: var(--b-accent); pointer-events: none; }
    .bs-compare { display: flex; align-items: center; gap: var(--b-s2); padding-top: var(--b-s1); font-size: var(--b-fs-xs); color: var(--b-text-2); }
    .bs-compare input { flex: 1; accent-color: var(--b-accent); }
    .bs-takecap .b-btn { padding: 2px var(--b-s2); font: var(--b-fs-xs) var(--b-font); }
    @keyframes bs-pulse { 0%, 100% { fill: transparent; } 50% { fill: rgba(196, 230, 106, 0.3); stroke: var(--b-accent); stroke-width: 3; } }
    @keyframes bs-pulse-dim { 0%, 100% { fill: transparent; } 50% { fill: rgba(255, 255, 255, 0.12); } }
    .bs-pulse .bs-slot rect, .bs-pulse .bs-slot polygon { animation: bs-pulse 1.2s ease-in-out 3; }
    .bs-pulse .bs-anchor rect { animation: bs-pulse-dim 1.2s ease-in-out 3; }
    .bs-steps { display: flex; flex-wrap: wrap; gap: 3px; list-style: none; margin: var(--b-s2) 0; padding: 0; font-size: var(--b-fs-xs); }
    .bs-steps li { flex: 1 1 auto; padding: 2px 6px; border-radius: 4px; background: var(--b-surface-2); color: var(--b-text-3); white-space: nowrap; text-align: center; }
    .bs-steps li.bs-done { color: var(--b-text-2); }
    .bs-steps li.bs-done::after { content: " ✓"; color: var(--b-accent); }
    .bs-steps li.bs-now { background: var(--b-accent); color: var(--b-accent-ink); font-weight: 600; }
    .bs-ready { font-size: var(--b-fs-xs); color: var(--b-text-3); }
    .bs-ready[data-state="ready"], .bs-ready[data-state="same"] { color: var(--b-accent); }
    .bs-ready[data-state="live"], .bs-ready[data-state="later"], .bs-ready[data-state="maybe"] { color: var(--b-cost); }
    .bs-piece .bs-badge { left: auto; right: 2px; bottom: auto; top: 2px; font-weight: 600; }
    .bs-piece .bs-badge[data-state="ready"] { background: var(--b-accent); color: var(--b-accent-ink); }
    .bs-piece .bs-badge[data-state="live"], .bs-piece .bs-badge[data-state="spends"], .bs-piece .bs-badge[data-state="later"],
    .bs-piece .bs-badge[data-state="maybe"] { background: rgba(0, 0, 0, 0.75); color: var(--b-cost); }
    .bs-piece.bs-made { border-color: var(--b-accent); box-shadow: 0 0 0 2px rgba(196, 230, 106, 0.35); }
    .bs-madenote { grid-column: 1 / -1; margin: 0; font-size: var(--b-fs-xs); color: var(--b-accent); }
    .bs-pickbox { margin-top: var(--b-s2); }
    .bs-picked { margin: 0; font-size: var(--b-fs-sm); color: var(--b-text); }
    .bs-note { margin: var(--b-s1) 0 0; font-size: var(--b-fs-xs); color: var(--b-warn); }
    .bs-details summary { cursor: pointer; font-size: var(--b-fs-xs); color: var(--b-text-3); }
    .bs-details[open] summary { margin-bottom: var(--b-s1); }
    .bs-name { color: var(--b-text-2); font-family: var(--b-font); }
    @media (max-width: 1100px) { .bs-set { grid-template-columns: 1fr; } .bs-left, .bs-side { position: static; max-height: none; } }
  `, view);
}
