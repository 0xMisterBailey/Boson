// Boson: each node's status line (its ui.text) on the canvas, e.g. Verdict's "waiting for your verdict",
// Draft Brief's round listing, Grid's readout. Uses the frontend's own text preview (the Preview Any widget) when
// it has one, else a read-only multiline STRING. The widget appears with the first status, never before.
import { app } from "../../scripts/app.js";

const plain = (t) => (t == null ? "" : Array.isArray(t) ? t.filter((x) => x != null).join("\n\n") : String(t));

async function show(node, text) {
  const native = window.comfyAPI?.textPreviewWidgets;
  const had = node.widgets?.some((w) => w.name === "preview_text" || w.name === "boson_status");
  if (native) {
    if (!had) {
      native.addTextPreviewWidgets(node);
      const mode = node.widgets.find((w) => w.name === "preview_mode");
      if (mode) mode.hidden = true; // the Markdown / Plain text toggle: Boson's lines are plain text
    }
    native.updateTextPreviewWidgets(node, { text });
  } else {
    let w = node.widgets?.find((w) => w.name === "boson_status");
    if (!w) {
      // older frontends without the native preview: their scripts/widgets.js (internal in newer ones)
      const { ComfyWidgets } = await import("../../scripts/widgets.js");
      w = ComfyWidgets.STRING(node, "boson_status", ["STRING", { multiline: true }], app).widget;
      w.inputEl.readOnly = true;
      w.inputEl.style.opacity = 0.6;
      w.serialize = false;
    }
    w.value = plain(text);
  }
  if (!had) {
    const [w, h] = node.computeSize();
    node.setSize([Math.max(node.size[0], w), Math.max(node.size[1], h)]);
  }
  node.setDirtyCanvas?.(true, true);
}

app.registerExtension({
  name: "boson.status",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (!nodeData.name?.startsWith("Boson")) return;
    const onExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      onExecuted?.apply(this, arguments);
      if (message?.text) show(this, message.text);
    };
  },
  // outputs restored on reload or tab switch
  onNodeOutputsUpdated(outputs) {
    for (const [id, out] of Object.entries(outputs ?? {})) {
      const node = app.graph?.getNodeById(id);
      if (node?.type?.startsWith("Boson") && out?.text) show(node, out.text);
    }
  },
});
