// Boson messages: every outcome of a run reaches the status line in plain words, in the right tone, with the next step.
// plain() is the one table from node texts and raises to sentences; watchRun() hears every node of a queued run (not
// only its target) and decides at the end: ok (it worked), warn (nothing made, nothing stored), error (a raise).
// tell() writes the status line with its buttons. Exports only (ComfyUI imports every .js under web/ into its page).

export const IMAGE_USD = 0.06;                   // one Nano Banana 2.1 picture at 1K (room.js IMAGE_USD)
export const WRITER_USD = [0.82, 1.25];                 // one writer call (room.js WRITER_COST)
export const words = (id) => String(id ?? "").replace(/[-_]+/g, " ");
export const usd = (x) => `$${x.toFixed(2)}`;
export const KEYLESS = "This copy has no keys, so it can only replay. Pieces marked ready replay.";

// [pattern, tone, sentence, next]: next names the button (tell's actions) or null. tone is the quiet-stop tone; a raise
// is always red. The first match wins.
export const RULES = [
  [/not rendered yet/, "warn", () => `This exact swap was never made, so there is nothing to replay. Turn on live calls to make it (about ${usd(IMAGE_USD)}).`, "live"],
  [/not made yet: run in live mode \(a writer call \+ (\d+) image calls\)/, "warn", (m) => {
    const n = +m[1];
    return `Nothing was made for this exact request before (this studio, this take, these words), so there is nothing to replay. ` +
      `Turn on live calls to make ${n} (a writer call and ${n} pictures, about ${usd(WRITER_USD[0] + n * IMAGE_USD)}-${usd(WRITER_USD[1] + n * IMAGE_USD)}).`;
  }, "live"],
  [/nothing to swap/, "warn", () => "Nothing to swap: pick a new piece for a slot first, then press Swap.", null],
  [/no swaps since take (\d+)/, "warn", (m) => `Nothing changed since take ${m[1]}: pick a new piece for a slot first, then press Swap.`, null],
  [/never located/, "warn", () => "Boson can't find the slots in this new picture without a vision call. Turn on live calls to let it look (one vision call).", "live"],
  [/slot (\S+) is not visible in this take/, "warn", (m) => `The ${words(m[1])} isn't a slot of this take yet: click it on the picture and press Make it a slot.`, null],
  [/(?:'([^']+)'|(\S+)) is not a slot of this scene/, "warn", (m) => `The ${words(m[1] ?? m[2])} isn't a slot of this scene yet: click it on the picture and press Make it a slot.`, null],
  [/no slot '([^']+)'/, "warn", (m) => `The ${words(m[1])} isn't a slot of this scene yet: click it on the picture and press Make it a slot.`, null],
  [/has no takes yet/, "warn", () => "This scene has no takes yet. Shooting the first one needs live calls (one image call and one vision call).", null],
  [/(\S+) is not in this take: skipped/, "warn", (m) => `The ${words(m[1])} isn't in this take, so it was skipped.`, null],
  [/take (\S+) (?:was committed without boxes|has no slot map)/, "warn", (m) => `Take ${m[1]} has no map of its slots, so its slots can't be cut out.`, null],
  [/is not a flat slot|Paste Flat only works on posters and signs/, "warn", () => "Paste Flat only works on flat slots: posters and signs.", null],
  [/no stored Nano Banana plates for round (\S+)/, "warn", (m) => `Round ${m[1]} was never rendered on this box, so there is nothing to replay. Live calls would render it.`, "live"],
  [/api[_ ]?key|unauthori[sz]ed|\b40[13]\b|credentials|not logged in/i, "error", () => "Live calls need a key, and this box has none. Turn live calls off to replay what was made before.", "replay"],
  [/^slot (\S+) (already in the scene|made from the frame)[^:]*: (\S+) fills it/, "ok", (m) =>
    `The ${words(m[1])} ${m[2] === "already in the scene" ? "was already" : "is now"} a slot, filled by the ${m[3]} studio. Pick a piece for it, or Make 4 for this spot.`, null],
  [/^take (\S+) already committed/, "warn", (m) => `Nothing new: this picture is already take ${m[1]}.`, null],
  [/^take (\S+) committed/, "ok", (m) => `New take ${m[1]} made.`, null],
  [/^make \S+: (\d+) pieces \(stored\)/, "ok", (m) => `${m[1]} pieces made, replayed from before (no call).`, null],
  [/flat swap, no image call/, "info", () => "A flat swap: pasted, no image call.", null],
  [/Author identity unknown|tell me who you are|unable to auto-detect email/i, "error", () => "Saving didn't finish: this computer has no name to sign saves with. Nothing changed. Set one once in a terminal (git config --global user.name \"Your Name\", and the same for user.email), then try again.", null],
  [/index\.lock|^git (?:add|commit|checkout|reset)\b/, "error", () => "Saving didn't finish (another save may still be running, or the disk is full). Nothing changed: the scene is as it was. Try again in a moment.", null],
  [/has uncommitted changes/, "error", () => "This scene's files were changed outside Boson, so Boson won't save over them. Nothing was made. Undo that outside change, then try again.", null],
  [/moved since this studio was loaded/, "error", () => "This scene changed in another window since this page read it. Reload the page, then try again.", null],
  [/slot (\S+) holds .* undo or swap it back first/, "warn", (m) => `The ${words(m[1])} still shows its own piece in the take the scene stands on, so removing the slot would leave that piece in the picture. Undo that swap (or swap the slot back) first.`, null],
  [/the (\S+) came with the scene/, "warn", (m) => `The ${words(m[1])} came with the scene, so it stays a slot: only slots made from the picture can be removed.`, null],
  [/^waiting/, "warn", (m, t) => `Not run yet: ${t.replace(/^waiting(: | for )?/, "")}.`, null],
];

/** A node text or a raise -> {tone, text, next, known}. raised: an execution_error (red). title: the node, for texts
 *  the table doesn't know (they pass through verbatim, with the node's title). */
export function plain(raw, { title = "", raised = false } = {}) {
  const t = String(raw ?? "").replace(/^Execution Blocked: |^(?:Runtime|Value|Key)Error: /, "").split("\n")[0].trim();
  for (const [re, tone, say, next] of RULES) {
    const m = re.exec(t);
    if (m) return { tone: raised ? "error" : tone, text: say(m, t), next, known: true };
  }
  return { tone: raised ? "error" : "info", text: title ? `${title}: ${t}` : t, next: null, known: false };
}

/** A refusal thrown by a verb or a route (client.js tags the pending-cast ones with .slots) -> what tell() shows: the
 *  table's sentence and tone when it knows the text, else the text, red. */
export function refusal(e) {
  const slots = e?.slots ?? [], p = plain(e?.message ?? e);
  return { tone: p.known ? p.tone : "error", text: p.known ? p.text : String(e?.message ?? e), next: slots.length ? "uncast" : null, slots };
}

/** Listen to one queued run on a ComfyUI app (its api events) and report it. Attach before queueing, then call
 *  target(ids) with what the verb queued: the run is the first prompt seen after attaching. progress(line) while it
 *  runs; end(outcome) once, at the end: {tone, text, next, take, slots}. upstream(ids): the node ids the run needs
 *  (for "step k of N"). -> {target(ids), stop(), promptId()}. */
export function watchRun(app, { label = "Run", upstream = () => [], progress = () => {}, end = () => {} } = {}) {
  const api = app?.api;
  const title = (id) => { const n = app?.graph?.getNodeById?.(Number(id)) ?? app?.graph?.getNodeById?.(id);
    return n?.title ?? String(n?.type ?? "").replace(/^Boson/, ""); };
  let pid = null, ids = null, need = new Set(), finished = null, closed = false;
  const cached = new Set(), texts = [];
  const mine = (d) => { const p = d?.prompt_id; if (p == null) return true; pid ??= p; return p === pid; };
  const order = new Map();                              // node id -> its step number, in the order the run starts them
  const step = (id) => {
    if (id && !cached.has(id) && !order.has(id)) order.set(id, order.size + 1);
    const n = Math.max([...need].filter((x) => !cached.has(x)).length, order.size), k = id ? order.get(id) : 0;
    progress(`${label}: working…${id ? ` ${title(id)}` : ""}${need.size && k ? `, step ${k} of ${n}` : ""}`);
  };
  const on = {
    execution_start: (e) => { if (mine(e.detail)) step(); },
    execution_cached: (e) => { if (!mine(e.detail)) return; for (const x of e.detail?.nodes ?? []) cached.add(String(x)); step(); },
    executing: (e) => { const id = typeof e.detail === "object" ? e.detail?.node : e.detail;
      if (id == null || pid == null) return; step(String(id)); },
    progress: (e) => { const d = e.detail; if (!mine(d) || !d?.max) return;
      progress(`${label}: working… ${title(d.node)} ${Math.round((100 * d.value) / d.max)}%`); },
    executed: (e) => { const d = e.detail; if (!mine(d)) return;
      const t = d?.output?.text; if (t?.length) texts.push({ node: String(d.node), text: t.join(" ") }); },
    execution_success: (e) => { if (mine(e.detail)) finish({ how: "done" }); },
    execution_error: (e) => { if (mine(e.detail)) finish({ how: "error", d: e.detail }); },
    execution_interrupted: (e) => { if (mine(e.detail)) finish({ how: "stopped" }); },
  };
  const detach = () => { if (closed) return; closed = true; for (const [k, f] of Object.entries(on)) api?.removeEventListener(k, f); };
  for (const [k, f] of Object.entries(on)) api?.addEventListener(k, f);
  function finish(f) { finished ??= f; if (ids) settle(); }
  function settle() {
    if (closed) return;
    detach();
    end(outcome(finished, ids, texts, title));
  }
  return {
    target(t) { ids = (Array.isArray(t) ? t : []).map(String); try { need = new Set((upstream(ids) ?? []).map(String)); } catch { need = new Set(); }
      if (!api) { detach(); return; } if (finished) settle(); },
    stop: detach,
    halt() { finish({ how: "stopped" }); },              // Cancel: end it here too (a run that never started sends nothing)
    promptId: () => pid,
  };
}

/** The end of a run, decided once from everything it said: a raise -> red; the target ran -> its own line (ok unless
 *  the table says otherwise); else the blocker that stopped it -> amber, nothing made and nothing stored. */
export function outcome(f, ids, texts, title = () => "") {
  if (f?.how === "error") {
    const d = f.d ?? {};
    const p = plain(d.exception_message ?? "an error", { title: title(d.node_id) || String(d.node_type ?? "").replace(/^Boson/, ""), raised: true });
    return { ...p, take: null };
  }
  if (f?.how === "stopped") return { tone: "warn", text: "Stopped: nothing was made.", next: null, take: null };
  const own = texts.filter((x) => ids.includes(x.node));
  const said = own.length ? own[own.length - 1] : null;
  if (said) {
    const p = plain(said.text, { title: title(said.node) });
    const take = /^take (\S+) committed/.exec(said.text)?.[1] ?? null;
    return { ...p, tone: p.known ? p.tone : "ok", take };
  }
  const warns = texts.map((x) => ({ x, p: plain(x.text, { title: title(x.node) }) })).filter(({ p }) => p.known && p.tone === "warn");
  const why = warns.find(({ x }) => !/skipped$/.test(x.text.split("\n")[0])) ?? warns[0];   // a branch skipped is not why
  if (why) return { ...why.p, take: null };
  const last = texts[texts.length - 1];
  const stop = ids.map(title).filter(Boolean).join(", ") || "the last step";
  return { tone: "warn", take: null, next: null,
    text: `Nothing was made: the run stopped before ${stop}${last ? ` (${title(last.node)}: ${last.text.split("\n")[0]})` : ""}.` };
}

/** A miss whose next step is live calls, on a box with no keys: the stored path instead, no button that leads nowhere. */
export function keyless(o) {
  return { ...o, next: null, text: `${String(o.text ?? "").replace(/ (Turn on live calls|Live calls would)[^]*$/, "")} ${KEYLESS}` };
}

/** Write the status line: the sentence, then a button per next step the view can take (actions: {live, replay,
 *  uncast(slot), cancel, ...} -> {label, run}; keyless: true on a box with no keys). */
export function tell(o, actions = {}) {
  const s = typeof document !== "undefined" && document.getElementById("boson-status");
  if (!s) return;
  if (o.next === "live" && actions.keyless) o = keyless(o);
  s.replaceChildren(document.createTextNode(o.text ?? ""));
  s.dataset.tone = o.tone ?? "info";
  const add = (label, run) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "b-btn bs-inline"; b.textContent = label;
    b.onclick = () => { b.disabled = true; run(); };
    s.append(" ", b);
  };
  if (o.next === "uncast" && actions.uncast) for (const slot of o.slots ?? []) add(`Uncast ${words(slot)}`, () => actions.uncast(slot));
  else if (o.next && actions[o.next]) add(actions[o.next].label, actions[o.next].run);
  if (actions.cancel && o.busy) add(actions.cancel.label, actions.cancel.run);
}

/** Queue a verb and see it through: "LABEL: starting…", the progress line with Cancel, then the outcome with its next
 *  step. verb() queues and returns the target ids (a client.js write verb). busy: the button that started it (disabled
 *  while it runs). then(outcome) after the end (redraw from the repo). A refusal before anything is queued is said
 *  red, with Uncast buttons when it names pending casts. -> the outcome, once the run ends (null when refused). */
export function run(label, verb, { app, upstream, interrupt, actions = {}, busy = null, then = () => {} } = {}) {
  const free = () => { if (busy) { busy.disabled = false; busy.removeAttribute("aria-busy"); } };
  if (busy) { busy.disabled = true; busy.setAttribute("aria-busy", "true"); }
  return new Promise((resolve) => {
    let w = null;
    const cancel = { label: "Cancel", run: () => { Promise.resolve(interrupt?.(w?.promptId())).catch(() => {}); w?.halt(); } };
    w = watchRun(app, { label, upstream,
      progress: (text) => tell({ tone: "info", text, busy: true }, { cancel }),
      end: (o) => { free(); tell(o, actions); Promise.resolve(then(o)).finally(() => resolve(o)); } });
    tell({ tone: "info", text: `${label}: starting…`, busy: true }, { cancel });
    Promise.resolve().then(verb).then((ids) => {
      w.target(ids);
      if (!app?.api) { free(); tell({ tone: "ok", text: `${label}: queued` }); resolve(null); }
    }, (e) => { w.stop(); free(); tell(refusal(e), actions); resolve(null); });
  });
}
