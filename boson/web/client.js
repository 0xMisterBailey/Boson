// Boson client: the one module a Boson UI calls (docs/APP-API.md). Reads go to the pack's read-only /boson/* routes;
// every write sets widgets on the graph's own Boson nodes and queues that graph (only the nodes write a repo), exactly
// as panel.js does. It keeps no state of its own: the repos hold it, the graph holds pending casts in its widgets.
// No side effects on import (ComfyUI loads every .js in web/ as an extension; this one only exports).
// Verb names follow design/v4/proto/API.md in camelCase (make, moreLike, editHouse, ...); differences: docs/APP-API.md.

export function bosonClient({ base = "", app = () => globalThis.app } = {}) {
  const get = async (path, q = {}) => {
    const qs = new URLSearchParams(Object.entries(q).filter(([, v]) => v != null && v !== "")).toString();
    const r = await fetch(`${base}${path}${qs ? "?" + qs : ""}`);
    const d = await r.json();
    if (d && d.error) throw new Error(d.error);
    return d;
  };
  const post = async (path, body) => {
    const r = await fetch(`${base}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const d = await r.json();
    if (d && d.error) throw new Error(d.error);
    return d;
  };
  const url = (path, q) => `${base}${path}?${new URLSearchParams(q).toString()}`;

  // ---- the graph (a ComfyUI `app`: this page's, or an iframe's contentWindow.app) ----
  const g = () => { const a = app(); if (!a?.graph) throw new Error("no ComfyUI graph: open the canvas first"); return a; };
  // A graph for the canvas, rebuilt in the canvas's own window. The app page fetches it, but ComfyUI (in the iframe)
  // tells a link from a widget value by `instanceof Array`, which an array from another window fails: every link dropped.
  const own = (data) => {
    const w = g().canvasEl?.ownerDocument?.defaultView;
    return w?.JSON && w.JSON !== JSON ? w.JSON.parse(JSON.stringify(data)) : data;
  };
  const loadGraph = async (data) => g().loadGraphData(own(data));
  const loadApi = async (data, file) => g().loadApiJson(own(data), file);
  const nodes = (type) => (g().graph._nodes ?? []).filter((n) => n.type === type);
  const widget = (n, name) => n?.widgets?.find((w) => w.name === name);
  const set = (n, name, v) => {
    const w = widget(n, name);
    if (!w) throw new Error(`${n?.title ?? n?.type} has no widget ${name}`);
    w.value = v; w.callback?.(v); n.setDirtyCanvas?.(true, true);
  };
  const one = (type, pick = () => true) => {
    const n = nodes(type).find(pick);
    if (!n) throw new Error(`this graph has no ${type.replace("Boson", "")} node`);
    return n;
  };
  const wiredFrom = (n, input) => {             // the node feeding n's input, or null
    const i = n.inputs?.find((x) => x.name === input);
    const link = i?.link != null ? g().graph.links?.[i.link] ?? g().graph.links?.get?.(i.link) : null;
    return link ? g().graph.getNodeById(link.origin_id) : null;
  };
  const queue = async (targets) => {            // targets: output nodes to run (and what they need), else the graph
    const ids = targets?.map((n) => String(n.id));
    const ok = await g().queuePrompt(0, 1, ids ? { queueNodeIds: ids } : {});
    if (ok === false) throw new Error("ComfyUI refused this run before it started: press Graph to see which node it names.");
    return ids ?? "graph";
  };
  const shotRender = () => one("BosonNanoBanana", (n) => wiredFrom(n, "shot"));
  const loadStudioOf = (n) => {                 // the Load Studio upstream of n's studio input
    for (let x = wiredFrom(n, "studio"); x; x = wiredFrom(x, "studio")) if (x.type === "BosonLoadStudio") return x;
    return null;
  };
  const point = (n, repo) => {                  // aim n's Load Studio at repo (main), if it is not there already
    const ls = loadStudioOf(n);
    if (!ls) throw new Error(`${n.title ?? n.type} has no Load Studio upstream`);
    if (repo && widget(ls, "repo").value !== repo) { set(ls, "repo", repo); set(ls, "ref", "main"); }
    return n;
  };
  const named = async (list, name, what) => {   // a studio or scene name -> its repo (a path or a .bundle stays as is)
    if (!name || /[/]|\.bundle$/.test(name)) return name;
    const hit = (await list()).find((x) => x.name === name);
    if (!hit) throw new Error(`no ${what} named ${name}`);
    return hit.repo;
  };
  const studioRepo = (name) => named(() => get("/boson/studios"), name, "studio");
  const sceneRepo = (name) => named(() => get("/boson/scenes"), name, "scene");
  const STUDIO_NODES = ["BosonMake", "BosonEditHouse", "BosonDraftBrief", "BosonVerdict"];
  /** The studio graph (workflows/studio.json) behind a studio view, its Load Studio aimed at the studio. */
  const studioGraph = async (studio, need, pick = () => true) => {
    const repo = await studioRepo(studio);
    if (!nodes(need).filter(pick).length) {
      if (api.graphState().length) throw held();
      await loadGraph(await get("/boson/workflow", { name: "studio" }));
    }
    return { repo, n: (type, pick) => point(one(type, pick), repo) };
  };
  const roundRender = () => one("BosonNanoBanana", (n) => wiredFrom(n, "studio")?.type === "BosonDraftBrief");
  const pad = (take) => (take === "" || take == null ? "" : String(take).padStart(2, "0"));
  const spotIdea = (sl, words = "") => {        // a Make for a slot's spot: part of the stored key, one copy only
    const spot = `for the spot in commission image 1: ${sl.place?.line ?? ""}`.trim();
    return words.trim() ? `${words.trim()} It goes ${spot}` : `A new ${sl.short ?? sl.noun} ${spot}`;
  };
  /** The refusal while Cast widgets hold pending casts: names the slots (.slots, so a view can offer Uncast). */
  const held = (other = "") => {
    const slots = api.graphState().map((c) => c.slot);
    const what = slots.map((x) => x.replace(/[-_]+/g, " ")).join(", ");
    return Object.assign(new Error(`You have ${slots.length > 1 ? `${slots.length} unapplied swaps` : "an unapplied swap"}${other} (${what}). ` +
      `Swap ${slots.length > 1 ? "them" : "it"} or Uncast ${slots.length > 1 ? "them" : "it"} first.`), { slots });
  };

  const api = {
    // ---- reads ----
    studios: () => get("/boson/studios"),
    studio: (repo, ref = "main") => get("/boson/studio", { repo, ref }),
    loop: (repo, ref = "main") => get("/boson/loop", { repo, ref }),   // the loop rounds, dots, verdicts, changes
    scenes: () => get("/boson/scenes"),
    scene: (repo, ref = "main") => get("/boson/scene", { repo, ref }),
    shelf: () => get("/boson/shelf"),
    workflow: (name) => get("/boson/workflow", { name }),
    hasWorkflow: async (name) => (await fetch(url("/boson/workflow", { name }))).ok,   // a shipped workflows/NAME.json
    pieceUrl: (ref) => url("/boson/piece", { ref }),
    takeUrl: (repo, take, ref = "main") => url("/boson/take", { repo, take, ref }),
    plateUrl: (repo, file) => url("/boson/plate", { repo, file }),
    clipUrl: (repo, clip, ref = "main") => url("/boson/clip", { repo, clip, ref }),
    /** The motion graph for a take (tools/motion_workflow.build, API format): {graph, has_key, cost}. Reads only. */
    motion: (repo, take, prompt) => get("/boson/motion", { repo, take, prompt }),
    /** The scene's graph built from SCENE.json now (API format, tools/scene_workflow.build): {name, graph}. Reads only. */
    sceneGraph: (repo) => get("/boson/scene-graph", { repo }),
    /** What replays with no call for a slot (server.ready): {slots, take, parent (the take a Swap edits), swaps:
     *  [{piece, stored, located, flat}], makes: [{studio, stored, pieces}]}. words: the owner's idea, as commissionNew
     *  takes it; pieces: the ones to check (default the shelf's and this spot's stored makes). Reads only. */
    async ready(scene, take, slot, { words = "", n = 4, pieces } = {}) {
      const repo = await sceneRepo(scene);
      if (!slot) return get("/boson/ready", { repo });
      const sl = (await get("/boson/scene", { repo })).spec.slots.find((x) => x.id === slot);
      if (!sl) throw new Error(`no slot ${slot}`);
      return get("/boson/ready", { repo, take: pad(take), slot, idea: spotIdea(sl, words), frame: sl.role ?? "", n,
                                   pieces: pieces?.join("\n") });
    },
    spotIdea,

    // ---- the graph behind the view ----
    /** Load a shipped workflow (scene-NAME: tools/scene_workflow.py) unless the graph already holds this scene's Load
     *  Scene node. Switching scenes refuses while casts are pending (they live only in the graph). casts: also load it
     *  when the graph has no Cast node (a motion graph holds the scene's Load Scene but no Casts). */
    async ensureScene(repo, name = "scene-street", { casts = false } = {}) {
      const have = nodes("BosonLoadScene");
      if (have.length && widget(have[0], "repo").value !== repo && api.graphState().length)
        throw held(" in another scene");
      if (!have.length || widget(have[0], "repo").value !== repo || (casts && !nodes("BosonCast").length))
        await loadGraph(await get("/boson/workflow", { name }));
      const ls = nodes("BosonLoadScene")[0];
      if (widget(ls, "repo").value !== repo) set(ls, "repo", repo);
      return ls;
    },
    /** A Cast node for every slot: when the scene has slots the loaded graph lacks (made since it was saved, Add Slot),
     *  load the graph built from its SCENE.json now. Refuses while casts are pending. Loads only: nothing is queued. */
    async syncScene(repo, slots) {
      const have = new Set(nodes("BosonCast").map((n) => widget(n, "slot").value));
      if (slots.every((s) => have.has(s))) return false;
      if (api.graphState().length) throw held();
      const { name, graph } = await get("/boson/scene-graph", { repo });
      await loadApi(graph, `${name}.api.json`);
      const ls = nodes("BosonLoadScene")[0];
      if (ls && widget(ls, "repo").value !== repo) set(ls, "repo", repo);
      return true;
    },
    /** The studio graph (workflows/studio.json) unless the graph already is one, its Load Studio aimed at repo (main).
     *  Refuses while Cast widgets hold pending casts (as every studio verb does). Loads only: nothing is queued. */
    async ensureStudio(repo) {
      const { repo: r } = await studioGraph(repo, "BosonDraftBrief");
      const ls = nodes("BosonLoadStudio")[0];
      if (!ls) throw new Error("the studio graph has no Load Studio node");
      if (widget(ls, "repo").value !== r) { set(ls, "repo", r); set(ls, "ref", "main"); }
      return ls;
    },
    /** Load a motion graph (API format, from motion()) into the canvas: Load Scene -> Load Take -> Gemini Omni ->
     *  Commit Clip. Loads only: nothing is queued. Refuses while casts are pending (they live only in the graph). */
    async loadMotion(graph, name = "motion") {
      if (api.graphState().length) throw held();
      await loadApi(graph, `${name}.api.json`);
      return nodes("BosonCommitClip")[0]?.id ?? null;
    },
    graphState() {                              // what is pending on the graph (Cast widgets), read from the widgets
      return nodes("BosonCast").map((n) => ({ slot: widget(n, "slot").value, piece: widget(n, "piece").value }))
        .filter((c) => c.piece);
    },

    // ---- writes: set widgets, then queue ----
    /** Use this take: the scene stands on it (SCENE.json chosen + that take's cast, one commit, nothing deleted), so
     *  the next Swap edits it. Undo swap = useTake(scene, the swap's parent). -> the scene, as scene(). */
    async useTake(scene, take) { return post("/boson/use-take", { repo: await sceneRepo(scene), take: pad(take) }); },
    /** Remove this slot: a slot made from the frame is part of the base again (SCENE.json, one commit, takes stay).
     *  Its pending cast on the graph is cleared first (that Cast node stays, idle). -> the scene, as scene(). */
    async removeSlot(scene, slot) {
      const repo = await sceneRepo(scene);
      try { if (api.graphState().some((c) => c.slot === slot)) api.uncast(slot); } catch { /* no scene graph: nothing staged */ }
      return post("/boson/remove-slot", { repo, slot });
    },
    /** Cast a slot (a swap). Sets the Cast node's widgets only: pending until shoot() or swap(). */
    cast(slot, piece, { desc = "", short = "" } = {}) {
      const n = one("BosonCast", (x) => widget(x, "slot").value === slot);
      set(n, "piece", piece); if (widget(n, "desc")) set(n, "desc", desc); if (widget(n, "short")) set(n, "short", short);
      return n.id;
    },
    uncast(slot) { set(one("BosonCast", (x) => widget(x, "slot").value === slot), "piece", ""); },
    /** Shoot a new take: a new day on the same set (one image call per draw), located (one vision call) and committed. */
    shoot({ take = "", draws = 1 } = {}) {
      const c = one("BosonCompileScene");
      set(c, "mode", "shoot"); set(c, "take", take);
      const nb = shotRender(); set(nb, "mode", "live"); set(nb, "draws", draws);
      set(one("BosonLocate"), "mode", "live");
      return queue([one("BosonCommitTake")]);
    },
    /** Apply every pending swap as one edit of the last shoot take (no call if only flats changed), then commit.
     *  The proto's (scene, take, slots) are optional: slots, when given, must be exactly what is pending. */
    swap(scene, take, slots, { live = true } = {}) {
      if (slots) {
        const p = api.graphState().map((c) => c.slot).sort().join(",");
        if ([...slots].sort().join(",") !== p) throw new Error(`pending on the graph: ${p || "nothing"}, not ${slots}`);
      }
      const mode = live ? "live" : "stored";       // stored: the swap rendered before, replayed with no key and no call
      set(one("BosonCompileScene"), "mode", "swap");
      set(shotRender(), "mode", mode);
      set(one("BosonLocate"), "mode", mode);
      return queue([one("BosonCommitTake")]);
    },
    /** Locate the image feeding the Locate node (one vision call unless cached). */
    locate() { const n = one("BosonLocate"); set(n, "mode", "live"); return queue([n]); },
    /** Put a piece on the shared shelf: Keep Piece's path + note, its Load Studio pointed at the piece's studio. */
    async keep(studio, path, note = "") {
      const k = point(one("BosonKeepPiece"), await studioRepo(studio));
      set(k, "path", path); set(k, "note", note); if (widget(k, "op")) set(k, "op", "keep");
      return queue([k]);
    },
    /** Take a piece off the shelf (path, or the whole studio@sha:path). */
    async unkeep(studio, piece) {
      const k = point(one("BosonKeepPiece"), await studioRepo(studio));
      set(k, "path", piece); set(k, "op", "unkeep");
      return queue([k]);
    },

    // ---- studio side (the studio graph: workflows/studio.json, loaded when the graph lacks the node) ----
    /** Make n pieces for a frame (a style line or a subject) and an idea: one writer call + n image calls, not a round. */
    async make(studio, frame, idea, n = 4, { like = "" } = {}) {
      const free = (x) => !wiredFrom(x, "image_1");   // not a scene's commission-new Make
      const s = await studioGraph(studio, "BosonMake", free);
      const m = s.n("BosonMake", free);
      set(m, "frame", frame ?? ""); set(m, "idea", idea ?? ""); set(m, "n", n); set(m, "like", like); set(m, "mode", "live");
      return queue([m]);
    },
    /** n more like a piece (studio@sha:path): its prompt to the writer, its image to the renderer. */
    moreLike(studio, piece, n = 4) { return api.make(studio, "", "", n, { like: piece }); },
    /** An owner edit of the house, one commit: field sentence | words | style_lines | principles | subjects | pictures | pins. */
    async editHouse(studio, field, value, op = field === "sentence" ? "set" : "add") {
      const s = await studioGraph(studio, "BosonEditHouse");
      const e = s.n("BosonEditHouse");
      set(e, "field", field); set(e, "op", op); set(e, "value", Array.isArray(value) ? value.join("\n") : String(value));
      return queue([e]);
    },
    /** Pin a piece for the next make (the inspiration frame). */
    pin(studio, piece) { return api.editHouse(studio, "pins", piece, "add"); },
    unpin(studio, piece) { return api.editHouse(studio, "pins", piece, "remove"); },
    /** A piece becomes one of the house pictures. */
    addPicture(studio, piece) { return api.editHouse(studio, "pictures", piece, "add"); },
    /** + Style line / + Subject: kind "style" or "subject", named. */
    newBranch(studio, kind, name) {
      if (!name?.trim()) throw new Error(`a new ${kind} needs a name`);
      return api.editHouse(studio, kind === "subject" ? "subjects" : "style_lines", name, "add");
    },
    /** Run on its own: the writer drafts the next round, Nano Banana renders it; the Verdict node then waits. */
    async runRounds(studio, { pieces = 4, draws = 1 } = {}) {
      const s = await studioGraph(studio, "BosonDraftBrief");
      set(s.n("BosonDraftBrief"), "pieces", pieces);
      const nb = roundRender(); set(nb, "mode", "live"); set(nb, "draws", draws);
      return queue([s.n("BosonVerdict")]);
    },
    /** Sign the open round's verdict (one sentence). Refuses a round that is not the studio's open, drafted one. */
    async verdict(studio, round, text) {
      if (!text?.trim()) throw new Error("a verdict is one sentence");
      const s = await studioGraph(studio, "BosonVerdict");
      const st = await get("/boson/studio", { repo: s.repo, ref: "main" });
      if (String(round).padStart(2, "0") !== st.round || !st.drafted) throw new Error(`round ${round} is not open (open: ${st.round}${st.drafted ? "" : ", not drafted"})`);
      const v = s.n("BosonVerdict"); set(v, "verdict", text); set(roundRender(), "mode", "stored");
      return queue([v]);
    },
    /** Aim the Dots node at the open loop round (widget only, nothing queued), so Run pauses on the right round. */
    async aimDots(studio, round) { const s = await studioGraph(studio, "BosonDots"); set(s.n("BosonDots"), "round", Number(round)); },
    /** The owner's dots and verdict on the open loop round (the room's Submit): sets the Dots node's widgets and
     *  queues only it. It commits greens -> pins and the verdict row (no call); it never makes the next round. */
    async dots(studio, round, greens = [], reds = [], text = "") {
      if (!text?.trim()) throw new Error("a verdict is one sentence");
      if (!greens.length && !reds.length) throw new Error("no dots yet: green what to make more of, red what to stop");
      const s = await studioGraph(studio, "BosonDots");
      const d = s.n("BosonDots");
      set(d, "round", Number(round)); set(d, "greens", greens.join("\n")); set(d, "reds", reds.join("\n")); set(d, "verdict", text);
      return queue([d]);
    },
    /** The writer digests the judged round into lessons and proposed rules (a writer call). */
    async digest(studio) { const s = await studioGraph(studio, "BosonDigest"); set(roundRender(), "mode", "stored"); return queue([s.n("BosonDigest")]); },
    /** Approve proposed rules by number ("1,3") or "none". */
    async approve(studio, round, picks) {
      const s = await studioGraph(studio, "BosonApproveRules");
      const a = s.n("BosonApproveRules"); set(a, "picks", `${String(round).padStart(2, "0")}: ${picks}`);
      return queue([a]);
    },
    /** Forge a studio from a refs folder (tools/forge_refs.py + describe_refs.py) and the owner's sentence (a writer call). */
    async forgeStudio({ refs, sentence, field, owner = "", name, path, instrument = "", commission = "" }) {
      if (!nodes("BosonForgeStudio").length) await studioGraph("", "BosonForgeStudio");
      const f = one("BosonForgeStudio");
      // a bare name: Forge Studio puts the studio in examples/ (st.forge_path)
      set(f, "path", path ?? name); set(f, "owner", owner); set(f, "field", field);
      set(f, "sentence", sentence); set(f, "refs", refs); set(f, "instrument", instrument); set(f, "commission", commission);
      return queue([f]);
    },
    /** + New scene: from a piece (its base view, no slots yet) or a SCENE.json (object or text). */
    async newScene({ name, fromPiece = "", spec = "", path = "" }) {
      if (!nodes("BosonNewScene").length) await studioGraph("", "BosonNewScene");
      const n = one("BosonNewScene");
      set(n, "name", name); set(n, "from_piece", fromPiece); set(n, "spec", typeof spec === "string" ? spec : JSON.stringify(spec, null, 1));
      set(n, "path", path);
      return queue([n]);
    },

    // ---- scene side, by the proto's names ----
    /** Stage a piece for a slot (pending), or, for the world slot, the day: the TAKE sentence of the next re-shoot. */
    async stage(scene, slot, piece, opts = {}) {
      await api.ensureScene(await sceneRepo(scene));
      if (slot === "world") { set(one("BosonCompileScene"), "take", piece?.day ?? piece ?? ""); return null; }
      return api.cast(slot, piece, opts);
    },
    /** Re-shoot: a new day on the same set (the staged day, if any, stays in Compile Scene's take). */
    async reshoot(scene, take, { draws = 1 } = {}) {
      await api.ensureScene(await sceneRepo(scene));
      return api.shoot({ take: widget(one("BosonCompileScene"), "take").value, draws });
    },
    /** Commission new: the slot's crop of a take (Load Take -> Slot Crop) as a studio's commission image, Make n.
     *  studio: any studio by name (plug and play, round 49), else the slot's own. idea: the owner's words, else the
     *  slot's place line. live false: stored, what this make rendered before, no key, no call. */
    async commissionNew(scene, take, slot, { n = 4, studio = "", idea = "", live = true } = {}) {
      const repo = await sceneRepo(scene);
      await api.ensureScene(repo);
      const sl = (await get("/boson/scene", { repo })).spec.slots.find((x) => x.id === slot);
      if (!sl) throw new Error(`no slot ${slot}`);
      const crop = one("BosonSlotCrop", (x) => widget(x, "slot").value === slot);
      const m = one("BosonMake", (x) => wiredFrom(x, "image_1") === crop);
      const lt = wiredFrom(crop, "image");
      if (lt?.type === "BosonLoadTake") set(lt, "take", pad(take));
      if (studio) point(m, await studioRepo(studio));
      set(m, "frame", sl.role ?? ""); set(m, "idea", spotIdea(sl, idea));
      set(m, "n", n); set(m, "like", ""); set(m, "mode", live ? "live" : "stored");
      return queue([m]);
    },
    /** Make a slot from the frame: Add Slot's widgets, then queue it (a commit of SCENE.json, no call). anchor: a base
     *  anchor Locate boxes (the slot takes its box), or box: "x, y, w, h" fractions. */
    addSlot({ anchor = "", slot, noun, studio, where = "", box = "" }) {
      const a = one("BosonAddSlot");
      set(a, "anchor", anchor); set(a, "slot", slot); set(a, "noun", noun); set(a, "studio", studio);
      set(a, "where", where); set(a, "box", box);
      return queue([a]);
    },
    /** Queue the whole graph as it stands (stored modes cost nothing). */
    run: () => queue(),
    /** The node ids a run of targets needs (they and everything wired into them), for a "step k of N" line. */
    upstream(ids) {
      const seen = new Set(), todo = (ids ?? []).map((id) => g().graph.getNodeById(Number(id))).filter(Boolean);
      while (todo.length) {
        const n = todo.pop();
        if (seen.has(String(n.id))) continue;
        seen.add(String(n.id));
        for (const i of n.inputs ?? []) { const x = wiredFrom(n, i.name); if (x) todo.push(x); }
      }
      return [...seen];
    },
    /** Stop the running prompt (this one only, when its id is known); not started yet: clear the waiting queue too. */
    async interrupt(promptId) {
      const post = (path, body) => fetch(`${base}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!promptId) await post("/queue", { clear: true });
      const a = app();
      if (a?.api?.interrupt) return a.api.interrupt(promptId ?? undefined);
      await post("/interrupt", promptId ? { prompt_id: promptId } : {});
    },
  };
  return api;
}
