// Boson panel: a ComfyUI sidebar over the graph's own Boson nodes. It reads the studio through /boson/studio
// (read-only) and acts only by setting widgets on the graph's nodes and queueing the graph: Verdict commits the
// sentence, Approve Rules commits the picks, Draft Brief + Nano Banana make the next round. No state of its own.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const CSS = `
.boson-panel { font: 13px Inter, system-ui, sans-serif; color: #ddd; padding: 12px; display: flex;
  flex-direction: column; gap: 14px; height: 100%; overflow-y: auto; box-sizing: border-box; }
.boson-panel h3 { margin: 0; font-size: 15px; font-weight: 600; color: #eee; }
.boson-panel .sub { color: #8a8a8a; font-size: 12px; }
.boson-panel select, .boson-panel textarea { width: 100%; box-sizing: border-box; background: #313235; color: #ddd;
  border: 1px solid #444; border-radius: 6px; padding: 6px 8px; font: inherit; }
.boson-panel textarea { min-height: 64px; resize: vertical; }
.boson-panel .deck { position: relative; background: #171718; border-radius: 12px; overflow: hidden; }
.boson-panel .deck img { display: block; width: 100%; max-height: 52vh; object-fit: contain; background: #171718; }
.boson-panel .deck .cap { padding: 6px 10px; color: #a0a0a0; font-size: 12px; display: flex; justify-content: space-between; }
.boson-panel .thumbs { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 2px; }
.boson-panel .thumbs img { height: 52px; border-radius: 6px; opacity: .55; cursor: pointer; border: 2px solid transparent; }
.boson-panel .thumbs img.on { opacity: 1; border-color: #3080ff; }
.boson-panel button { background: #3080ff; color: #fff; border: 0; border-radius: 6px; padding: 7px 12px; font: inherit;
  font-weight: 600; cursor: pointer; }
.boson-panel button.ghost { background: #313235; color: #ddd; }
.boson-panel button:disabled { opacity: .4; cursor: default; }
.boson-panel .row { display: flex; gap: 8px; align-items: center; }
.boson-panel .rule { display: flex; gap: 8px; align-items: flex-start; padding: 6px 0; border-top: 1px solid #2c2c2e; }
.boson-panel .status { font: 12px ui-monospace, monospace; color: #fff; background: #171718; border-radius: 6px;
  padding: 6px 8px; white-space: pre-wrap; }
.boson-panel .past { color: #a0a0a0; font-size: 12px; border-left: 2px solid #444; padding-left: 8px; }
`;

const $ = (tag, cls, parent, html) => { const e = document.createElement(tag); if (cls) e.className = cls;
  if (html != null) e.innerHTML = html; parent?.appendChild(e); return e; };
const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const nodesOf = (type) => (app.graph?._nodes ?? []).filter((n) => n.type === type);
const widget = (n, name) => n?.widgets?.find((w) => w.name === name);
const setWidget = (n, name, v) => { const w = widget(n, name); if (!w) return false; w.value = v; w.callback?.(v);
  n.setDirtyCanvas?.(true, true); return true; };

function panel(root) {
  root.innerHTML = "";
  if (!document.getElementById("boson-panel-css")) { const s = $("style"); s.id = "boson-panel-css"; s.textContent = CSS; document.head.appendChild(s); }
  const el = $("div", "boson-panel", root);
  let at = 0, data = null, studioNode = null;

  async function load() {
    const studios = nodesOf("BosonLoadStudio");
    el.innerHTML = "";
    $("h3", "", el, "Boson");
    if (!studios.length) { $("div", "sub", el, "Add a Load Studio node (and a round: Draft Brief → Nano Banana → Verdict) to work a studio here."); return; }
    if (!studioNode || !studios.includes(studioNode)) studioNode = studios[0];
    if (studios.length > 1) {
      const sel = $("select", "", el);
      studios.forEach((n, i) => { const o = $("option", "", sel, esc(`${n.title} · ${widget(n, "repo").value.split("/").pop()}`)); o.value = i; if (n === studioNode) o.selected = true; });
      sel.onchange = () => { studioNode = studios[+sel.value]; at = 0; load(); };
    }
    const repo = widget(studioNode, "repo").value, ref = widget(studioNode, "ref").value;
    try {
      const r = await api.fetchApi(`/boson/studio?repo=${encodeURIComponent(repo)}&ref=${encodeURIComponent(ref)}`);
      data = await r.json();
    } catch (e) {
      $("div", "status", el, esc(`could not read the studio (${e.message ?? e}): is the Boson pack loaded on this server?`));
      return;
    }
    if (data.error) { $("div", "status", el, esc(data.error)); return; }
    render(repo);
  }

  function render(repo) {
    const d = data;
    $("div", "sub", el, esc(`${d.studio} @ ${d.ref} (${d.sha}) · round ${d.round} · ${d.rules.length} rule(s) bind`));
    // ---- the deck: the open round's plates
    if (d.plates.length) {
      at = Math.min(at, d.plates.length - 1);
      const deck = $("div", "deck", el), img = $("img", "", deck), cap = $("div", "cap", deck);
      const thumbs = $("div", "thumbs", el);
      const url = (p) => `/api/boson/plate?repo=${encodeURIComponent(repo)}&file=${encodeURIComponent(p.file)}`;
      const show = (k) => { at = k; img.src = url(d.plates[k]);
        cap.innerHTML = `<span>${esc(d.plates[k].title)}</span><span>${k + 1} / ${d.plates.length}</span>`;
        [...thumbs.children].forEach((t, i) => t.classList.toggle("on", i === k)); };
      d.plates.forEach((p, k) => { const t = $("img", "", thumbs); t.src = url(p); t.onclick = () => show(k); });
      deck.tabIndex = 0;
      deck.onkeydown = (e) => { if (e.key === "ArrowRight") show((at + 1) % d.plates.length); if (e.key === "ArrowLeft") show((at + d.plates.length - 1) % d.plates.length); };
      img.onclick = () => show((at + 1) % d.plates.length);
      show(at);
    } else {
      $("div", "sub", el, d.drafted ? `round ${d.round} is drafted, not rendered yet` : `round ${d.round} is not drafted yet`);
    }
    // ---- the step this studio is at
    const box = $("div", "", el);
    if (d.awaiting) {
      $("div", "", box, `<b>Round ${esc(d.awaiting)} proposes</b> <span class="sub">tick what binds from now on</span>`);
      const picks = Object.entries(d.proposed).map(([n, rule]) => { const row = $("label", "rule", box);
        const c = $("input", "", row); c.type = "checkbox"; c.value = n; $("span", "", row, `${esc(n)}. ${esc(rule)}`); return c; });
      const go = $("button", "", $("div", "row", box), "Approve rules");
      go.onclick = () => { const on = picks.filter((c) => c.checked).map((c) => c.value);
        run("BosonApproveRules", "picks", `${d.awaiting}: ${on.length ? on.join(",") : "none"}`, go); };
    } else if (d.verdict) {
      $("div", "past", box, `round ${esc(d.round)} verdict: “${esc(d.verdict)}”`);
      const go = $("button", "", $("div", "row", box), "Digest it");
      go.onclick = () => run(null, null, null, go);
    } else if (d.plates.length) {
      $("div", "", box, `<b>Your verdict on round ${esc(d.round)}</b> <span class="sub">one sentence on the whole round</span>`);
      const ta = $("textarea", "", box); ta.placeholder = "One sentence on the whole round (required)";
      const v = nodesOf("BosonVerdict")[0]; if (v) ta.value = widget(v, "verdict")?.value ?? "";
      const go = $("button", "", $("div", "row", box), "Commit verdict");
      go.onclick = () => { if (ta.value.trim()) run("BosonVerdict", "verdict", ta.value.trim(), go); };
    } else {
      const go = $("button", "", $("div", "row", box), `Draft + render round ${esc(d.round)}`);
      go.onclick = () => run(null, null, null, go);
    }
    // ---- history
    if (d.rounds.length) {
      const h = $("div", "", el); $("div", "sub", h, "history");
      d.rounds.slice().reverse().forEach((r) => $("div", "past", h, `r${esc(r.round)} “${esc(r.verdict ?? "")}”`));
    }
    if (d.rules.length) {
      const h = $("div", "", el); $("div", "sub", h, "binding rules");
      d.rules.forEach((r) => $("div", "past", h, esc(r)));
    }
    status = $("div", "status", el, esc(lastStatus || "ready"));
  }

  let status = null, lastStatus = "", running = false;
  async function run(type, name, value, btn) {
    if (type) {
      const n = nodesOf(type)[0];
      if (!n || !setWidget(n, name, value)) { say(`this graph has no ${type.replace("Boson", "")} node`); return; }
    }
    btn.disabled = true;
    running = true;
    say("queued");
    await app.queuePrompt(0, 1);
  }
  const say = (t) => { lastStatus = t; if (status) status.textContent = t; };

  current = { say, done: () => { if (running) { running = false; load(); } } };
  load();
  return { reload: load };
}

// one set of listeners for the page; they talk to whichever panel is open
let current = null;
api.addEventListener("executed", (e) => {
  const n = app.graph?.getNodeById(e.detail?.node);
  if (n?.type?.startsWith("Boson") && e.detail?.output?.text) current?.say(`${n.title}: ${[].concat(e.detail.output.text).join(" ")}`);
});
api.addEventListener("executing", (e) => { const n = e.detail && app.graph?.getNodeById(e.detail);
  if (n?.type?.startsWith("Boson")) current?.say(`${n.title} …`); });
api.addEventListener("status", (e) => { if (e.detail?.exec_info?.queue_remaining === 0) current?.done(); });
api.addEventListener("execution_error", (e) => {      // e.g. a render node without credit: said here, not only in a toast
  const d = e.detail || {};
  current?.say(`${d.node_type ?? "node"} failed: ${String(d.exception_message ?? "").split("\n")[0].slice(0, 240)}`);
});

app.registerExtension({
  name: "boson.panel",
  async setup() {
    app.extensionManager.registerSidebarTab({
      id: "boson", icon: "pi pi-sparkles", title: "Boson", tooltip: "Boson: your studio's rounds and verdicts",
      type: "custom", render: (root) => { panel(root); }, destroy: () => { current = null; },
    });
  },
});
