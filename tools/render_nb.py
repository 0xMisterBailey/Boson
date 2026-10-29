#!/usr/bin/env python3
"""Render a studio round's specs on Nano Banana (top rung, IDEAS round 27), per the studio's RENDER.json.

Each call gets the studio refs RENDER.json names + the commission refs, then lead + the spec's prompt.
Nano Banana is not reproducible with a seed (tested 2026-10-20: same seed, mean pixel diff 10/255), so these plates are a keyed
`live` render: stored on their own line (renderer field in the manifest), never in a Klein grid row (I4, I6).

  python3 tools/render_nb.py STUDIO_REPO REF OUT [--draws 1]
  -> OUT/rNN/<spec-id>__d<k>__nb.png + OUT/manifest.jsonl + OUT/rNN/sheet.jpg
"""
import argparse, json, pathlib, sys
from concurrent.futures import ThreadPoolExecutor

BOSON = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BOSON / "tools"), str(BOSON / "boson")]
import nb, studio as st  # noqa: E402


def sheet(paths, out, h=520):
    from PIL import Image
    ims = [Image.open(p).convert("RGB") for p in paths]
    ims = [i.resize((round(i.width * h / i.height), h)) for i in ims]
    cols = 4
    w = max(i.width for i in ims)
    S = Image.new("RGB", (cols * (w + 12), ((len(ims) + cols - 1) // cols) * (h + 12)), "white")
    for k, i in enumerate(ims):
        S.paste(i, ((k % cols) * (w + 12), (k // cols) * (h + 12)))
    S.save(out, quality=88)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo")
    ap.add_argument("ref")
    ap.add_argument("out")
    ap.add_argument("--draws", type=int, default=1)
    a = ap.parse_args()
    s = st.load(a.repo, a.ref)
    cfg = st.render_cfg(s)
    rid = f"{len(st.rounds(s)) + 1:02d}"
    d = pathlib.Path(s["dir"])
    specs = st.specs(d / "history" / f"round-{rid}")
    if not specs:
        sys.exit(f"no specs for round {rid} at {a.ref}")
    refs = [d / "refs" / f"{r}.jpg" for r in cfg["refs"]]
    refs += [d / r for r in cfg.get("commission_refs", [])]
    out = pathlib.Path(a.out) / f"r{rid}"
    jobs = [(sp, k, out / f"{sp['id']}__d{k}__nb.png") for sp in specs for k in range(a.draws)]

    def run(j):
        sp, k, p = j
        if not p.exists():
            nb.generate(cfg.get("lead", "") + sp["prompt"], p, refs, cfg.get("model", "gemini-nano-banana-2.1"),
                        cfg.get("aspect"), cfg.get("size", "2K"))
        return {"round": rid, "id": sp["id"], "draw": k, "file": str(p.relative_to(a.out)),
                "renderer": f"nanobanana:{cfg.get('model', 'gemini-nano-banana-2.1')}", "mode": "live",
                "studio_sha": s["sha"], "refs": [str(r.relative_to(d)) for r in refs]}

    with ThreadPoolExecutor(6) as ex:
        rows = list(ex.map(run, jobs))
    with open(pathlib.Path(a.out) / "manifest.jsonl", "a") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    sheet([out / pathlib.Path(r["file"]).name for r in rows], out / "sheet.jpg")
    print(f"round {rid}: {len(rows)} plates -> {out} (sheet.jpg)")


if __name__ == "__main__":
    main()
