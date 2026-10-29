"""The grid: one row per studio revision, same renderer and ref set in every cell (SPEC v3 §4.2, I6).

A row at ref X shows the round the studio drafted *from* X (r00 -> round 01's plates: the forge alone,
no history). Its readout: the verdict that made X, the rule(s) X's round wrote, one countable check.
`stored` mode reads plates + manifest beside the fixture: zero keys, zero LLM calls (I4).
"""
import json, pathlib, re

try:
    from . import studio as st
except ImportError:
    import studio as st

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def plates_dir(repo_path):
    """examples/ex-libris.bundle -> examples/ex-libris-plates (stored renders live beside the fixture)."""
    p = pathlib.Path(repo_path).expanduser()
    return p.parent / f"{p.name.split('.')[0]}-plates"


def _norm(m):
    """Nano Banana rounds (tools/render_nb.py) store {round: "01", id, draw, renderer: "nanobanana:..."}; Grid rows read
    {round: "r01", spec, seed, renderer: {name}}. NB ignores seeds, so `seed` carries the draw index (same brief, not
    same seed). Klein lines pass through unchanged."""
    if "spec" in m or "id" not in m:
        return m
    rnd = str(m["round"])
    return {**m, "round": rnd if rnd.startswith("r") else f"r{rnd}", "spec": m["id"], "seed": m.get("draw", 0),
            "renderer": {"name": m["renderer"]} if isinstance(m.get("renderer"), str) else m.get("renderer")}


def manifest(pdir):
    m = pdir / "manifest.jsonl"
    return [_norm(json.loads(l)) for l in m.read_text().splitlines() if l.strip()] if m.exists() else []


def verdict_line(s):
    rs = st.rounds(s)
    if not rs:
        return "(no history: the forge only)"
    rid = rs[-1]["round"]
    rd = pathlib.Path(s["dir"]) / "history" / f"round-{rid}"
    if (rd / "VERDICT.md").exists():
        return f'r{rid}: "{(rd / "VERDICT.md").read_text().strip()}"'
    if (rd / "OWNER-NOTE.md").exists():
        # T12-era rounds kept the owner's words as prose: take the first quote that is not the question asked
        para = (rd / "OWNER-NOTE.md").read_text().split("\n\n")[0]
        said = [q for q in re.findall(r'"([^"]+)"', para) if not q.rstrip().endswith("?")]
        if said:
            return f'r{rid}: "{said[0]}" (owner, quoted from OWNER-NOTE.md)'
    return f"r{rid}: " + rs[-1].get("verdict", rs[-1].get("reasons", ""))


def rule_line(s):
    rs = st.rounds(s)
    if not rs:
        return "no rules"
    rid = rs[-1]["round"]
    new = [r for r in st.rules(s) if r.startswith(f"(round {rid})")]
    return " | ".join(r.split(") ", 1)[1] for r in new) if new else f"round {rid} approved no rules"


def check_line(pdir, rid, arm="orig", line="main"):
    p = pdir / "checks.jsonl"
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
    hit = [c for c in rows if c["round"] == rid and c.get("arm", "orig") == arm and c.get("line", "main") == line]
    return "; ".join(f"{c['check']}: {c['count']}/{c['of']}" for c in hit) or "check: none recorded"


def line_of(repo, sha):
    """Which line of history a commit belongs to: "main" (main and its round-NN continuation branches), or
    the name of the side line holding it (e.g. owner-only). Stored plates carry the line they were drafted
    on, so two lines' round 01 never share a row."""
    heads = st.git(repo, "branch", "-a", "--contains", sha, "--format=%(refname:short)").split()
    side = sorted({h.split("/", 1)[-1] for h in heads} - {"main", "HEAD"})
    side = [h for h in side if not h.startswith("round-") and h != "origin"]
    return "main" if not side or st.git(repo, "branch", "-a", "--contains", sha, "--list", "*main") else side[0]


def owner_edits_before_draft(repo, sha, rid):
    """Owner edits committed between a row's ref and its round's draft (e.g. a new camera view in the commission):
    they shaped the round as much as the rules did, so the readout names them. -> ["<sha8> <subject>", ...]"""
    log = st.git(repo, "log", "--all", "--format=%H %P %s", f"--grep=^round {rid}: draft")
    for line in log.splitlines():
        h, parent, _ = line.split(" ", 2)
        if parent == sha:
            return []
        try:
            st.git(repo, "merge-base", "--is-ancestor", sha, parent)   # raises when the draft is not downstream
        except RuntimeError:
            continue
        got = st.git(repo, "log", "--format=%h %s", f"{sha}..{parent}")
        return [l for l in got.splitlines() if l.split(" ", 1)[-1].startswith("owner edit")]
    return []


def rows(repo, refs, cells, variant="", arm="orig"):
    """-> list of dicts {ref, round, sha, verdict, rule, check, plates:[(path, spec, seed)]}."""
    pdir = plates_dir(repo)
    man = manifest(pdir)
    out = []
    for ref in [r.strip() for r in refs.split(",") if r.strip()]:
        s = st.load(repo, ref)
        rid = st.next_round(s)
        line = line_of(s["repo"], s["sha"])
        hit = {}
        for m in man:          # a re-render of the same piece (e.g. by the Nano Banana node) replaces the earlier one
            if (m["round"] == f"r{rid}" and variant in m["spec"] and m.get("line", "main") == line
                    and m.get("prompt_arm", "orig") == arm):
                hit[(m["spec"], m["seed"])] = m
        ps = sorted(hit.values(), key=lambda m: (m["spec"], m["seed"]))
        out.append({"ref": ref, "round": rid, "sha": s["sha"], "verdict": verdict_line(s), "rule": rule_line(s),
                    "edits": owner_edits_before_draft(s["repo"], s["sha"], rid),
                    "check": check_line(pdir, rid, arm, line), "arm": arm,
                    "plates": [(pdir / m["file"], m["spec"], m["seed"]) for m in ps[:cells]],
                    "renderer": ps[0]["renderer"]["name"] if ps else None,
                    "drafted": ps[0].get("drafted") if ps else None})
    return out


def live_row(draft, cells, renderer):
    """One Grid Row: a writer draw at a tag, its pieces rendered on the canvas at each seed.
    cells = [(PIL image, spec id, seed)]. Never mixed with stored rows in one grid (I4)."""
    s = draft["studio"]
    return {"kind": "live", "ref": s["ref"], "round": draft["round"], "sha": s["sha"], "verdict": verdict_line(s),
            "rule": rule_line(s), "check": "check: by eye (live cells are not counted)", "arm": None,
            "draws": [draft["draw"]], "writer": draft["writer"], "renderer": renderer, "plates": cells}


def merge_live(rows):
    """Rows from draws of the same commit become one row, draws side by side (the spread is the point)."""
    out = {}
    for r in rows:
        if r["sha"] in out:
            m = out[r["sha"]]
            m["plates"] = m["plates"] + r["plates"]
            m["draws"] = m["draws"] + r["draws"]
            if r["writer"] not in m["writer"]:
                m["writer"] += " + " + r["writer"]
        else:
            out[r["sha"]] = dict(r)
    return list(out.values())


def readout(rs):
    lines = []
    for r in rs:
        if r.get("kind") == "live":
            seeds = sorted({c[2] for c in r["plates"]})
            lines += [f"{r['ref']} @ {r['sha'][:8]} -> round {r['round']} (LIVE: draws {r['draws']} x seeds {seeds}, "
                      f"{r['writer']}, rendered {r['renderer']})",
                      f"  verdict: {r['verdict']}", f"  rule: {r['rule']}", f"  {r['check']}"]
            continue
        altered = ", stored prompt stripped of the template (T14 strip)" if r["arm"] == "stripped" else ""
        drafted = f", {r['drafted']}" if r.get("drafted") else ""
        kind = (f"stored, {r['renderer']}{altered}{drafted}" if r["plates"]
                else "no stored plates (render them, or use mode live)")
        lines += [f"{r['ref']} @ {r['sha'][:8]} -> round {r['round']} ({kind})",
                  f"  verdict: {r['verdict']}", f"  rule: {r['rule']}"]
        lines += [f"  owner edit before the draft: {e[:96]}" for e in r.get("edits", [])]
        lines += [f"  {r['check']}"]
    return "\n".join(lines)


def _open(p):
    from PIL import Image
    return (p if isinstance(p, Image.Image) else Image.open(p)).convert("RGB")


def cell_aspect(rs, default=832 / 1216):
    """Width/height of a cell: the first stored plate's, so 4:5 and 16:9 studios are not stretched to 832x1216."""
    for r in rs:
        for p, _, _ in r["plates"]:
            im = _open(p)
            return im.width / im.height
    return default


def fit(im, cell_w, cell_h):
    """Same aspect as the cell (within 1 %): plain resize, as before. Otherwise fit inside it, centred on white."""
    from PIL import Image, ImageOps
    if abs(im.width / im.height - cell_w / cell_h) < 0.01 * cell_w / cell_h:
        return im.resize((cell_w, cell_h))
    out = Image.new("RGB", (cell_w, cell_h), "white")
    t = ImageOps.contain(im, (cell_w, cell_h))
    out.paste(t, ((cell_w - t.width) // 2, (cell_h - t.height) // 2))
    return out


def compose(rs, cell_h=512, label_w=560):
    from PIL import Image, ImageDraw, ImageFont
    import textwrap
    pad, n = 12, max([len(r["plates"]) for r in rs] + [1])
    cell_w = int(cell_h * cell_aspect(rs))
    W = label_w + n * (cell_w + pad) + pad
    img = Image.new("RGB", (W, len(rs) * (cell_h + pad) + pad), "white")
    d = ImageDraw.Draw(img)
    big, small = ImageFont.truetype(FONT, 26), ImageFont.truetype(FONT, 17)
    for i, r in enumerate(rs):
        y = pad + i * (cell_h + pad)
        tag = "  LIVE" if r.get("kind") == "live" else ""
        d.text((pad, y), f"{r['ref']}  (round {r['round']}){tag}", fill="black", font=big)
        ty = y + 40
        extra = (("", r["writer"]),) if r.get("kind") == "live" else ((("", r["drafted"]),) if r.get("drafted") else ())
        for head, body in (("verdict", r["verdict"]), ("rule", r["rule"]), ("", r["check"])) + extra:
            for k, ln in enumerate(textwrap.wrap((f"{head}: " if head else "") + body, 52)[:7]):
                d.text((pad, ty), ln, fill="black" if head != "verdict" else "#7a1f1f", font=small)
                ty += 22
            ty += 8
        for j, (p, _, _) in enumerate(r["plates"]):
            img.paste(fit(_open(p), cell_w, cell_h), (label_w + pad + j * (cell_w + pad), y))
        if not r["plates"]:
            d.text((label_w + pad, y + cell_h // 2), "no stored plates for this round", fill="#888", font=big)
    return img
