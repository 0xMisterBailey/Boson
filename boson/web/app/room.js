// Boson room: the studio view (a workroom). The house (the studio's taste) front and centre and editable through
// Edit House; the open loop round as a grid the owner dots (click = green, again = red, again = clear) with a literal
// text slot for the verdict; Submit sets the Dots node's widgets and queues only it (greens -> pins, the verdict row:
// no call). Next would make the next round (that spends): shown disabled with its cost. History: each round's verdict
// beside what it changed (TASTE.json pins, STUDIO.md) and what the next round made, r1 -> r2 -> r3.
// Contract (top of shell.js): renderStudio(view, boson, entry) fills `view`. Exports only (ComfyUI imports every .js
// under web/ into its own page). Reads: boson.studio + boson.loop (GET /boson/loop, docs/APP-API.md).
import { el, say, spendButton, isPrivatePiece, PRIVATE_LABEL, canvasApp } from "./ui.js";
import { run } from "./messages.js";
import { rendererName } from "./set.js";

export const WRITER_COST = "one writer call ($0.82-1.25, 3-6 min)";
export const IMAGE_USD = 0.06;            // one Nano Banana 2.1 picture at 1K (tools/loop.py IMAGE_USD)

/** studio@sha:path -> "studio@sha" (the commit that made it). */
export const madeAt = (piece) => String(piece).split(":")[0];
/** The renderer, in plain words: boson-nanobanana:gemini-nano-banana-2.1 -> Nano Banana 2.1. */
export const shortRenderer = (r) => rendererName(r) || "maker not recorded";
/** The open round's heading and its one-line gloss (IDEAS round 54: the dots explained as "Curate your preferences"). */
export const DOTS_HEADING = "Curate your preferences";
export const DOTS_GLOSS = "Green = more like this next round, red = less. The studio's taste builds up round by round.";
/** none -> green -> red -> none. */
export const nextDot = (d) => (d == null ? "green" : d === "green" ? "red" : null);

export async function renderStudio(view, boson, entry) {
  const [d, L] = await Promise.all([boson.studio(entry.repo), boson.loop(entry.repo).catch(() => null)]);
  view.replaceChildren();
  view.dataset.studio = entry.name;
  el("style", ROOM_CSS, view);
  const room = el("div", null, view, { className: "b-room" });
  const taste = L?.taste ?? d.taste;
  const rounds = L?.rounds ?? [];
  const short = (piece) => piece.split(":").pop().split("/").pop().replace(/__d\d+__\w+\.\w+$/, "").replace(/[-_]/g, " ");

  // ---- a write: queue it, hear every node of the run (messages.js: progress, Cancel, the outcome), then the view again ----
  const rerender = () => { if (view.dataset.studio === entry.name) renderStudio(view, boson, entry).catch((e) => say(String(e.message ?? e), "error")); };
  const actions = { uncast: (slot) => { try { boson.uncast(slot); say(`${slot}: uncast`, "ok"); } catch (e) { say(String(e.message ?? e), "error"); } } };
  const go = (label, verb) => run(label, verb, { app: canvasApp(), upstream: (ids) => boson.upstream(ids),
    interrupt: (p) => boson.interrupt(p), actions, then: rerender });
  const edit = (field, value, op) => go(`Edit House: ${op} ${field}`, () => boson.editHouse(entry.repo, field, value, op));
  const cap = (parent, piece, renderer) => {   // provenance on every picture: the commit that made it, who drew it
    const c = el("div", null, parent, { className: "b-prov" });
    el("span", `${madeAt(piece).split("@")[0]} studio`, c, { title: madeAt(piece) });   // the commit: on hover
    if (isPrivatePiece(piece)) el("span", PRIVATE_LABEL, c, { className: "b-private" });
    else if (renderer !== undefined) el("span", shortRenderer(renderer), c);
    return c;
  };
  const thumb = (parent, piece, src, { renderer, dot, title, mini } = {}) => {
    const f = el("figure", null, parent, { className: "b-thumb" });
    if (dot) f.dataset.dot = dot;
    el("img", null, f, { src, alt: title ?? short(piece), loading: "lazy",
      title: `${title ?? short(piece)}${dot ? ` (${dot})` : ""}\n${piece}${renderer ? `\nmade with ${shortRenderer(renderer)} (${renderer})` : ""}` });
    if (!mini) cap(f, piece, renderer);                   // minis: the group line names the studio and who drew them
    return f;
  };
  /** A strip of small pieces: each says its commit, one line under them says the studio and who drew them. */
  const minis = (parent, pieces, cls) => {
    const g = el("div", null, parent, { className: `b-strip ${cls}` });
    for (const p of pieces) thumb(g, p.piece, p.image, { renderer: p.renderer, dot: p.dot, title: p.title, mini: true });
    const studios = [...new Set(pieces.map((p) => madeAt(p.piece).split("@")[0]))];
    const drew = [...new Set(pieces.map((p) => shortRenderer(p.renderer)))];
    el("div", `${studios.join(", ")} · ${drew.join(", ")}`, parent, { className: "b-prov b-prov-line" });
    return g;
  };

  // ---- the house: front and centre, every line removable, every list open to one more ----
  el("h1", entry.label, room, { className: "b-h1" });
  const house = el("section", null, room, { className: "b-house" });
  const sent = el("div", null, house, { className: "b-sentence" });
  const showSentence = () => {
    sent.replaceChildren();
    el("p", taste.sentence || "no house sentence yet", sent, { className: "b-lede" });
    el("button", "Edit", sent, { type: "button", className: "b-btn b-quiet", onclick: () => {
      sent.replaceChildren();
      const t = el("textarea", null, sent, { className: "b-input b-wide", rows: 2, value: taste.sentence ?? "" });
      el("button", "Save", sent, { type: "button", className: "b-btn b-primary", onclick: () => t.value.trim() && edit("sentence", t.value, "set") });
      el("button", "Cancel", sent, { type: "button", className: "b-btn", onclick: showSentence });
      t.focus();
    } });
  };
  showSentence();
  const list = (title, field, items, placeholder) => {
    const box = el("div", null, house, { className: "b-field" });
    el("h2", title, box, { className: "b-h2" });
    const ul = el("div", null, box, { className: field === "words" ? "b-chips" : "b-lines" });
    for (const x of items) {
      const it = el("span", null, ul, { className: "b-item" });
      el("span", x, it);
      el("button", "remove", it, { type: "button", className: "b-x", title: `remove from the house: ${x}`, onclick: () => edit(field, x, "remove") });
    }
    const add = el("input", null, box, { className: "b-input", placeholder });
    add.onkeydown = (e) => { if (e.key === "Enter" && add.value.trim()) edit(field, add.value, "add"); };
  };
  list("Words", "words", taste.words, "+ a word, Enter");
  list("Style lines", "style_lines", taste.style_lines, "+ a style line, Enter");
  const pics = (title, field, items, verb) => {
    const box = el("div", null, house, { className: "b-field" });
    el("h2", title, box, { className: "b-h2" });
    if (!items.length) { el("p", field === "pins" ? "nothing pinned: green dots become pins" : "none yet: add one from a round below", box, { className: "b-meta" }); return; }
    const g = el("div", null, box, { className: "b-strip" });
    for (const piece of items) {
      const f = thumb(g, piece, boson.pieceUrl(piece));
      el("button", verb, f, { type: "button", className: "b-x b-on-pic", onclick: () => edit(field, piece, "remove") });
    }
  };
  pics("Pinned for the next make", "pins", taste.pins, "unpin");
  pics("House pictures", "pictures", taste.pictures, "remove");
  el("p", `${rounds.length} loop rounds · ${d.rules.length} rules · ${d.shelf.length} on the shelf. ` +
    "Every edit is saved in the studio's history, free.", house, { className: "b-meta", title: `studio @${d.sha}` });

  // ---- the open round: dot it, say it, submit ----
  const open = rounds.find((r) => r.round === L?.open);
  const last = rounds[rounds.length - 1];
  const next = el("div", null, null, { className: "b-next" });
  const nextButton = (r, brief) => {
    const n = r?.n ?? 6;
    spendButton(next, `Next: round ${(r?.round ?? 0) + 1}`, `${WRITER_COST} + ${n} image calls ($${(n * IMAGE_USD).toFixed(2)})`,
      () => boson.make(entry.repo, r?.frame ?? "", brief ?? "", n));
  };
  if (open) {
    boson.aimDots(entry.repo, open.round).catch(() => {});             // the graph's Dots shows the open round
    const key = `boson-dots:${entry.name}:${open.round}:${open.make}`;   // stable across Edit House commits
    const dots = new Map(JSON.parse(sessionStorage.getItem(key) ?? "[]"));
    const sec = el("section", null, room, { className: "b-open" });
    el("h2", DOTS_HEADING, sec, { className: "b-h2" });
    el("p", DOTS_GLOSS, sec, { className: "b-gloss" });
    el("p", `Round ${open.round} · "${open.base_idea}" · ${open.pieces.length} pieces · click a picture once for green, ` +
      "again for red, a third time to clear", sec, { className: "b-meta" });
    const grid = el("div", null, sec, { className: "b-grid b-dots" });
    const count = el("p", null, null, { className: "b-meta" });
    const v = el("textarea", null, null, { className: "b-input b-wide b-verdict", rows: 2,
      placeholder: "Write your verdict on this round, one sentence in your own words: what it got right, what it must stop." });
    const submit = el("button", "Submit dots and verdict", null, { type: "button", className: "b-btn b-primary" });
    const sync = () => {
      sessionStorage.setItem(key, JSON.stringify([...dots]));
      const g = [...dots].filter(([, x]) => x === "green").length, r = [...dots].filter(([, x]) => x === "red").length;
      count.textContent = `${g} green · ${r} red · ${open.pieces.length - g - r} undotted`;
      submit.disabled = !(g + r) || !v.value.trim();
      submit.title = submit.disabled ? "dot at least one picture and write the verdict" : "queues only the Dots node: greens -> pins, the verdict committed (no call)";
    };
    for (const p of open.pieces) {
      const c = el("figure", null, grid, { className: "b-card b-dot-card", tabIndex: 0 });
      const paint = () => { const x = dots.get(p.piece); if (x) c.dataset.dot = x; else delete c.dataset.dot; };
      const flip = () => { const x = nextDot(dots.get(p.piece)); if (x) dots.set(p.piece, x); else dots.delete(p.piece); paint(); sync(); };
      c.onclick = (e) => { if (!e.target.closest("button")) flip(); };
      c.onkeydown = (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); flip(); } };
      el("img", null, c, { src: p.image, alt: p.title, loading: "lazy" });
      const cp = el("figcaption", null, c, { className: "b-cap" });
      el("span", p.title, cp, { className: "b-title" });
      const acts = el("span", null, cp, { className: "b-acts" });
      el("button", "Pin", acts, { type: "button", className: "b-btn b-quiet", title: "pin for the next make (Edit House)", onclick: () => edit("pins", p.piece, "add") });
      el("button", "To house", acts, { type: "button", className: "b-btn b-quiet", title: "a house picture (Edit House)", onclick: () => edit("pictures", p.piece, "add") });
      cap(c, p.piece, p.renderer);
      paint();
    }
    const say_ = el("div", null, sec, { className: "b-say" });
    el("label", `Your verdict on round ${open.round}`, say_, { className: "b-h2", htmlFor: "b-verdict" });
    v.id = "b-verdict";
    say_.append(v, count);
    const row = el("div", null, say_, { className: "b-row-actions" });
    row.append(submit, next);
    v.value = sessionStorage.getItem(`${key}:v`) ?? "";
    v.oninput = () => { sessionStorage.setItem(`${key}:v`, v.value); sync(); };
    submit.onclick = async () => {
      const greens = open.pieces.map((p) => p.piece).filter((x) => dots.get(x) === "green");
      const reds = open.pieces.map((p) => p.piece).filter((x) => dots.get(x) === "red");
      go(`Dots for round ${open.round}`, async () => {
        const ids = await boson.dots(entry.repo, open.round, greens, reds, v.value);
        sessionStorage.removeItem(key); sessionStorage.removeItem(`${key}:v`);
        return ids;
      });
    };
    nextButton(open, null);
    el("span", "the next brief is written from your verdict once Dots commits it", next, { className: "b-meta" });
    sync();
  } else if (last) {
    const sec = el("section", null, room, { className: "b-open" });
    el("h2", `Round ${last.round} is judged; round ${last.round + 1} waits for a make`, sec, { className: "b-h2" });
    el("pre", last.brief ?? "", sec, { className: "b-brief" });
    sec.append(next);
    nextButton(last, last.brief);
  } else {
    const sec = el("section", null, room, { className: "b-open" });
    el("p", "No loop round yet (tools/loop.py NAME make --idea ...). Make answers an idea now:", sec, { className: "b-meta" });
    sec.append(next);
    spendButton(next, "Make 4", `${WRITER_COST} + 4 image calls ($${(4 * IMAGE_USD).toFixed(2)})`, () => boson.make(entry.repo, "", "", 4));
  }

  // ---- history: each verdict beside what it changed and what the next round made ----
  const judged = rounds.filter((r) => r.verdict);
  if (judged.length) {
    const hist = el("section", null, room, { className: "b-history" });
    el("h2", "How each verdict bound the next round", hist, { className: "b-h2" });
    for (const r of judged) {
      const nx = rounds.find((x) => x.round === r.round + 1);
      const row = el("article", null, hist, { className: "b-hrow" });
      row.dataset.round = r.round;
      const a = el("div", null, row, { className: "b-hcol" });
      el("div", `Round ${r.round} · your verdict`, a, { className: "b-k" });
      el("blockquote", r.verdict, a, { className: "b-quote" });
      minis(a, r.pieces, "b-mini");
      el("div", `${r.greens.length} green · ${r.reds.length} red`, a, { className: "b-meta" });

      const b = el("div", null, row, { className: "b-hcol" });
      el("div", `What it changed · ${r.change.from} -> ${r.change.to}`, b, { className: "b-k" });
      const h = r.change.house ?? {};
      for (const [field, ch] of Object.entries(h)) {
        if (field === "sentence") { el("div", `sentence -> ${ch.to}`, b, { className: "b-diff b-add" }); continue; }
        el("div", `TASTE.json ${field}`, b, { className: "b-file" });
        for (const x of ch.added) el("div", `+ ${typeof x === "string" && x.includes("@") ? short(x) : x}`, b, { className: "b-diff b-add", title: x });
        for (const x of ch.removed) el("div", `- ${typeof x === "string" && x.includes("@") ? short(x) : x}`, b, { className: "b-diff b-del", title: x });
      }
      if (!r.change.files.includes("STUDIO.md")) el("div", "STUDIO.md: no rule change", b, { className: "b-file b-quiet-t" });
      else el("pre", r.change.diff.split("\ndiff --git").find((x) => x.includes("STUDIO.md")) ?? "", b, { className: "b-brief" });
      if (r.brief) {
        const det = el("details", null, b, { className: "b-briefbox" });
        el("summary", "the next brief", det);
        el("pre", r.brief, det, { className: "b-brief" });
      }

      const c = el("div", null, row, { className: "b-hcol" });
      if (nx) {
        el("div", `Round ${nx.round} · what it made${nx.verdict ? "" : " (open)"}`, c, { className: "b-k" });
        minis(c, nx.pieces, "b-next-pieces");
        el("div", `pins it saw: ${nx.pins.length}`, c, { className: "b-meta" });
      } else el("div", `Round ${r.round + 1}: not made yet`, c, { className: "b-k" });
    }
  }

  // ---- makes outside the loop (Make answered an idea) ----
  const inLoop = new Set(rounds.map((r) => r.make));
  const other = d.makes.filter((m) => !inLoop.has(m.key));
  if (other.length) {
    const det = el("details", null, room, { className: "b-other" });
    el("summary", `${other.length} other makes`, det, { className: "b-h2" });
    for (const m of [...other].reverse()) {
      el("div", m.idea || m.frame || `make ${m.key.slice(0, 6)}`, det, { className: "b-k" });
      const g = el("div", null, det, { className: "b-strip b-mini" });
      for (const p of m.pieces) {
        const f = thumb(g, p.piece, boson.plateUrl(entry.repo, p.file), { title: p.title });
        el("button", "Keep", f, { type: "button", className: "b-x b-on-pic", onclick: () => go("Keep", () => boson.keep(entry.repo, p.file)) });
      }
    }
  }
  if (!rounds.length && !d.makes.length) say(`${entry.label}: nothing made yet`);
}

// Room styles: theme variables only (theme.css), no new colours; green dot = the accent, red dot = --b-danger.
export const ROOM_CSS = `
  .b-room { display: flex; flex-direction: column; gap: var(--b-s4); }
  .b-gloss { margin: 0; font-size: var(--b-fs-md); color: var(--b-text); }   /* the dots' one-line meaning */
  .b-house { background: var(--b-surface-2); border: 1px solid var(--b-line); border-radius: var(--b-radius); padding: var(--b-s4) var(--b-s5);
    display: grid; grid-template-columns: 1fr 1fr; gap: var(--b-s2) var(--b-s5); }
  .b-house > .b-sentence, .b-house > .b-meta { grid-column: 1 / -1; }
  .b-sentence { display: flex; gap: var(--b-s3); align-items: flex-start; flex-wrap: wrap; }
  .b-sentence .b-lede { flex: 1; margin: 0; color: var(--b-text); font-size: var(--b-fs-xl); line-height: 1.25; }
  .b-field .b-h2 { margin-top: var(--b-s2); }
  .b-chips, .b-lines { display: flex; flex-wrap: wrap; gap: var(--b-s1) var(--b-s2); margin-bottom: var(--b-s2); }
  .b-lines { flex-direction: column; }
  .b-item { display: inline-flex; align-items: baseline; gap: var(--b-s2); background: var(--b-surface-3); border-radius: var(--b-radius-sm);
    padding: 2px var(--b-s2); font-size: var(--b-fs-sm); }
  .b-x { font: inherit; font-size: var(--b-fs-xs); color: var(--b-text-3); background: none; border: 0; cursor: pointer; padding: 0 2px; }
  .b-x:hover { color: var(--b-danger); }
  .b-on-pic { position: absolute; top: 4px; right: 4px; background: rgba(0,0,0,0.6); color: var(--b-text); border-radius: 4px; padding: 1px 6px; }
  .b-quiet { background: none; font-size: var(--b-fs-xs); padding: 2px var(--b-s2); }
  .b-wide { width: 100%; }
  .b-strip { display: grid; grid-template-columns: repeat(auto-fill, minmax(7.5rem, 1fr)); gap: var(--b-s2); }
  .b-strip.b-mini { grid-template-columns: repeat(3, 1fr); gap: 4px; }
  .b-strip.b-next-pieces { grid-template-columns: repeat(3, 1fr); gap: 6px; }
  .b-thumb { position: relative; margin: 0; border-radius: var(--b-radius-sm); overflow: hidden; background: #000; outline: 2px solid transparent; outline-offset: -2px; }
  .b-thumb img { width: 100%; aspect-ratio: 1; object-fit: cover; display: block; }
  .b-prov { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 0 var(--b-s2); font: var(--b-fs-xs)/1.3 var(--b-mono);
    color: var(--b-text-3); padding: 3px var(--b-s2); background: var(--b-surface); }
  .b-mini .b-prov, .b-next-pieces .b-prov { font-size: 0.6rem; padding: 2px 4px; }
  .b-prov-line { background: none; padding: 0; }
  [data-dot="green"] { outline: 3px solid var(--b-accent) !important; outline-offset: -3px; }
  [data-dot="red"] { outline: 3px solid var(--b-danger) !important; outline-offset: -3px; }
  .b-dot-card { cursor: pointer; margin: 0; position: relative; outline: 3px solid transparent; outline-offset: -3px; }
  .b-dot-card img { aspect-ratio: 1; }
  .b-dot-card[data-dot]::after { content: attr(data-dot); position: absolute; top: 8px; left: 8px; font: 600 var(--b-fs-xs)/1 var(--b-font);
    text-transform: uppercase; letter-spacing: 0.08em; padding: 4px 8px; border-radius: 99px; background: var(--b-accent); color: var(--b-accent-ink); }
  .b-dot-card[data-dot="red"]::after { background: var(--b-danger); color: var(--b-text); }
  .b-dot-card .b-cap { flex-wrap: wrap; }
  .b-title { flex: 1; min-width: 8rem; }
  .b-acts { display: flex; gap: 2px; }
  .b-say { margin-top: var(--b-s3); display: flex; flex-direction: column; gap: var(--b-s2); }
  .b-verdict { font-size: var(--b-fs-lg); min-height: 3.6em; }
  .b-row-actions { display: flex; flex-wrap: wrap; gap: var(--b-s4); align-items: center; }
  .b-next { display: inline-flex; flex-wrap: wrap; gap: var(--b-s2); align-items: center; }
  .b-brief { white-space: pre-wrap; font: var(--b-fs-xs)/1.4 var(--b-mono); color: var(--b-text-2); background: rgba(0,0,0,0.3);
    padding: var(--b-s2) var(--b-s3); border-radius: var(--b-radius-sm); margin: var(--b-s1) 0; max-height: 14rem; overflow: auto; }
  .b-history { display: flex; flex-direction: column; gap: var(--b-s3); }
  .b-hrow { display: grid; grid-template-columns: 1fr 0.9fr 1.25fr; gap: var(--b-s4); background: var(--b-surface-2); border: 1px solid var(--b-line);
    border-radius: var(--b-radius); padding: var(--b-s4); }
  .b-hcol { min-width: 0; display: flex; flex-direction: column; gap: var(--b-s2); }
  .b-k { font-size: var(--b-fs-xs); font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--b-text-3); }
  .b-quote { margin: 0; font-size: var(--b-fs-lg); line-height: 1.3; color: var(--b-text); border-left: 3px solid var(--b-accent); padding-left: var(--b-s3); }
  .b-file { font: var(--b-fs-xs)/1.3 var(--b-mono); color: var(--b-text-2); margin-top: var(--b-s1); }
  .b-quiet-t { color: var(--b-text-3); }
  .b-diff { font: var(--b-fs-sm)/1.35 var(--b-mono); padding: 2px var(--b-s2); border-radius: 4px; overflow-wrap: anywhere; }
  .b-add { color: var(--b-accent); background: color-mix(in srgb, var(--b-accent) 9%, transparent); }
  .b-del { color: var(--b-danger); background: color-mix(in srgb, var(--b-danger) 9%, transparent); }
  .b-briefbox summary { cursor: pointer; color: var(--b-text-2); font-size: var(--b-fs-xs); }
  .b-other .b-strip { margin-bottom: var(--b-s3); }
  `;
