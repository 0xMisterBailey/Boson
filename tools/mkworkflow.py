#!/usr/bin/env python3
"""A ComfyUI UI workflow (what loadGraphData and the canvas read) from an API workflow (what /prompt runs), so the two
shipped files never drift: widgets in each node's INPUT_TYPES order, links from the API inputs, titles and positions
from `_meta` (`title`, `pos`, `size`) or an existing UI file with the same node ids.

  python3 tools/mkworkflow.py workflows/NAME.api.json [--keep workflows/NAME.json] > workflows/NAME.json
"""
import argparse, json, pathlib, sys, types

ROOT = pathlib.Path(__file__).resolve().parents[1]
STOCK = {"PreviewImage": ({"required": {"images": ("IMAGE",)}}, ()),
         "LoadBackgroundRemovalModel": ({"required": {"bg_removal_name": (["birefnet.safetensors"],)}},
                                        [("bg_model", "BACKGROUND_REMOVAL")]),
         "RemoveBackground": ({"required": {"bg_removal_model": ("BACKGROUND_REMOVAL",), "image": ("IMAGE",)}},
                              [("mask", "MASK")])}
WIDGET = ("STRING", "INT", "FLOAT", "BOOLEAN")


def boson_nodes():
    """boson.nodes importable outside ComfyUI (ExecutionBlocker stubbed)."""
    if "comfy_execution.graph_utils" not in sys.modules:
        stub = types.ModuleType("comfy_execution.graph_utils")
        stub.ExecutionBlocker = type("ExecutionBlocker", (), {"__init__": lambda self, m: None})
        sys.modules.setdefault("comfy_execution", types.ModuleType("comfy_execution"))
        sys.modules["comfy_execution.graph_utils"] = stub
    sys.path.insert(0, str(ROOT))
    from boson import nodes
    return nodes.NODE_CLASS_MAPPINGS


def shape(cls_type):
    """-> ([(name, type, is_widget, default)], [(output name, type)]) for a node class. default: an optional widget's
    (its first choice for a combo), None for a required one."""
    if cls_type in STOCK:
        it, outs = STOCK[cls_type]
    else:
        c = boson_nodes()[cls_type]
        it = c.INPUT_TYPES()
        outs = list(zip(getattr(c, "RETURN_NAMES", None) or c.RETURN_TYPES, c.RETURN_TYPES))
    ins = []
    for part in ("required", "optional"):
        for name, spec in it.get(part, {}).items():
            t, opt = spec[0], (spec[1] if len(spec) > 1 else {})
            dflt = None if part == "required" else (t[0] if isinstance(t, list) else opt.get("default"))
            ins.append((name, "COMBO" if isinstance(t, list) else t, isinstance(t, list) or t in WIDGET, dflt))
    return ins, outs


def widget_names(cls_type):
    return [n for n, _, w, _ in shape(cls_type)[0] if w]


def ui(api, keep=None):
    old = {n["id"]: n for n in (keep or {}).get("nodes", [])}
    nodes, links, by_id = [], [], {}
    for order, (nid, n) in enumerate(api.items()):
        ins, outs = shape(n["class_type"])
        meta, o = n.get("_meta", {}), old.get(int(nid), {})
        node = {"id": int(nid), "type": n["class_type"], "pos": meta.get("pos") or o.get("pos") or [order % 4 * 380, order // 4 * 260],
                "size": meta.get("size") or o.get("size") or [300, 120], "flags": {}, "order": order, "mode": 0,
                "inputs": [], "outputs": [{"name": a, "type": t, "links": []} for a, t in outs],
                "properties": {"Node name for S&R": n["class_type"]}, "widgets_values": []}
        for name, t, is_w, dflt in ins:
            v = n["inputs"].get(name, dflt)
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                links.append([len(links) + 1, int(v[0]), v[1], int(nid), name, t])
                node["inputs"].append({"name": name, "type": t, "link": len(links)})
            elif is_w:
                if v is None:
                    raise SystemExit(f"node {nid} ({n['class_type']}): no value for widget {name}")
                node["widgets_values"].append(v)
        if meta.get("title") or o.get("title"):
            node["title"] = meta.get("title") or o["title"]
        nodes.append(node)
        by_id[int(nid)] = node
    out = []
    for lid, src, slot, dst, name, t in links:
        by_id[src]["outputs"][slot]["links"].append(lid)
        tgt = next(i for i, x in enumerate(by_id[dst]["inputs"]) if x["name"] == name)
        out.append([lid, src, slot, dst, tgt, t])
    return {"last_node_id": max(by_id), "last_link_id": len(out), "nodes": nodes, "links": out,
            "groups": (keep or {}).get("groups", []), "config": {}, "extra": (keep or {}).get("extra", {}), "version": 0.4}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("api")
    ap.add_argument("--keep", help="an existing UI file: keep its positions, sizes, titles, groups, note")
    a = ap.parse_args()
    keep = json.loads(pathlib.Path(a.keep).read_text()) if a.keep and pathlib.Path(a.keep).exists() else None
    print(json.dumps(ui(json.loads(pathlib.Path(a.api).read_text()), keep), indent=1))


if __name__ == "__main__":
    main()
