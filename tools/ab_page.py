#!/usr/bin/env python3
"""The A/B page: every picture of the Austin scene as made in the cloud (A) next to its redraw on this machine (B), and
for the takes the hybrid (C: A's cloud street, B's local pieces), each captioned with who drew it, who wrote its words,
whose dots chose it, who found its boxes, and what it was given as references. A pick (A / B / C / tie) and a note per
pair, saved by tools/ab_serve.py to WORK/picks.json. Also writes WORK/PROVENANCE.md (strace destinations by turn).

  python3 tools/ab_page.py [--work ~/.cache/boson-ab]    # -> WORK/page/index.html, WORK/page/text.md, WORK/PROVENANCE.md
"""
import argparse, collections, html, json, pathlib, re, subprocess, urllib.parse

ROOT = pathlib.Path(__file__).resolve().parents[1]
EX = ROOT / "examples"
A_SCENE = EX / "austin-stop"
STREET_A = EX / "streets" / "refs" / "01.jpg"
KLEIN = "FLUX 3 Klein (bf16, open weights) on this machine's RTX 4090"
NB = "Nano Banana 2.1 through the Comfy partner node (cloud)"
STREET_NOTES = {   # the agent's one-line read of each B street version against SCENE.json's words (2026-10-27)
    "gold-east-cesar-chavez.png": "Shelter and streetcar on the left half, no corner building with a painted name; the "
                                  "slots' places (woman right of the shelter, car near lane) fall on empty road.",
    "gold-east-cesar-chavez-s2.png": "Wide road, far vehicles; no brick corner building on the left; the white van is "
                                     "far off, not in the near lane.",
    "gold-east-cesar-chavez-s3.png": "Corner building with a painted name and a mural on the left, shelter, streetcar; "
                                     "everything sits small and far, the near lane is empty.",
    "gold-east-cesar-chavez-s4.png": "PICKED: every anchor the words name: low sun behind the big live oak, a brick "
                                     "corner building with a painted name and a mural, the shelter with a lit ad panel "
                                     "and a woman at the stop, the cartoon-wrapped streetcar, a white van in the lane. "
                                     "The shelter sits left of where A's is (x 0.2-0.45, not 0.62-0.78).",
}
B_STREET = "gold-east-cesar-chavez-s4.png"


def rows(p):
    p = pathlib.Path(p)
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True).stdout.strip()


def src(p):
    return "/f?" + urllib.parse.urlencode({"p": str(p)})


def esc(s):
    return html.escape(str(s))


def fig(path, cap, arm):
    if not path or not pathlib.Path(path).exists():
        return f'<figure class="arm {arm} missing"><div class="none">not made</div><figcaption>{cap}</figcaption></figure>'
    return (f'<figure class="arm {arm}"><a href="{src(path)}" target="_blank"><img loading="lazy" src="{src(path)}"></a>'
            f'<figcaption><b>{arm.upper()}</b> {cap}</figcaption></figure>')


def picker(pid, arms):
    opts = "".join(f'<label><input type="radio" name="{pid}" value="{a}"> {a}</label>' for a in arms + ["tie"])
    return (f'<div class="pick" data-id="{pid}">{opts}<textarea placeholder="a note (why)" rows="2"></textarea>'
            f'<span class="saved"></span></div>')


def traces(work):
    """turn -> Counter of destinations (address, port or unix path) from strace connect lines."""
    out = {}
    for t in sorted((work / "traces").glob("*.trace")):
        c = collections.Counter()
        for line in t.read_text(errors="replace").splitlines():
            m = re.search(r'sin_port=htons\((\d+)\), sin_addr=inet_addr\("([^"]+)"\)', line)
            m6 = re.search(r'sin6_port=htons\((\d+)\).*inet_pton\(AF_INET6, "([^"]+)"', line)
            mu = re.search(r'sun_path="([^"]+)"', line)
            if m:
                c[f"{m.group(2)}:{m.group(1)}"] += 1
            elif m6:
                c[f"[{m6.group(2)}]:{m6.group(1)}"] += 1
            elif mu:
                c[f"unix:{mu.group(1)}"] += 1
        out[t.stem] = c
    return out


def off_box(c):
    return sorted(k for k in c if not (k.startswith("127.0.0.1") or k.startswith("[::1]") or k.startswith("unix:")
                                       or k.startswith("0.0.0.0")))


def gpu_turns(work):
    """[(turn, kind, minutes)] from the === start/end lines in progress.log."""
    starts, out = {}, []
    for line in (work / "logs" / "progress.log").read_text().splitlines():
        m = re.match(r"=== (\S+)(?: \((\w+)\))? (start|end) (\d\d):(\d\d):(\d\d)", line)
        if not m:
            continue
        name, kind, what = m.group(1), m.group(2) or "klein", m.group(3)
        sec = int(m.group(4)) * 3600 + int(m.group(5)) * 60 + int(m.group(6))
        if what == "start":
            starts[name] = (kind, sec)
        elif name in starts:
            k, s0 = starts.pop(name)
            out.append((name, k, round((sec - s0) / 60, 1)))
    return out


def a_renderer(r):
    return NB if "nano-banana" in (r or "") else ("renderer not recorded" if not r else esc(r))


def build(work):
    work = pathlib.Path(work)
    plan = rows(work / "plan.jsonl")
    rep = {r["file"]: r for r in rows(work / "logs" / "replay.jsonl") if r.get("drawn") or True}
    tk = collections.defaultdict(dict)
    for r in rows(work / "logs" / "takes.jsonl"):
        tk[(r["scene"], r["take"])][r["step"]] = r
    tr = traces(work)
    turns = gpu_turns(work)
    dests = collections.Counter()
    for c in tr.values():
        dests.update(c)
    off = off_box(dests)
    b_takes = sorted(p.name for p in (work / "scenes" / "austin-stop-b" / "takes").glob("*") if p.is_dir())
    c_takes = sorted(p.name for p in (work / "scenes" / "austin-stop-c" / "takes").glob("*") if p.is_dir())
    b_plates = sum(1 for r in plan if (work / "studios" / f"{r['studio']}-plates" / r["file"]).exists())
    cards = sorted((work / "home" / "shots" / "garments").glob("*.png"))
    streets = sorted((work / "street").glob("*.png"))
    n = {"A": 1 + len(plan) + 12, "B": len(streets) + b_plates + len(b_takes) + len(cards), "C": len(c_takes)}
    gpu = collections.defaultdict(float)
    for name, kind, m in turns:
        gpu[kind] += m
    first = {"K1": "street and plain plates"}
    turn_txt = ", ".join(f"{nm} {m} min" for nm, k, m in turns)

    css = """
body{font:15px/1.4 system-ui,sans-serif;background:#111;color:#ddd;margin:0;padding:16px 24px}
h1{font-size:22px;margin:4px 0} h2{font-size:18px;margin:28px 0 8px;border-top:1px solid #333;padding-top:14px}
.top{background:#1b1b1b;padding:10px 14px;border-radius:6px;margin:8px 0}
.row{display:flex;gap:12px;align-items:flex-start;margin:14px 0 4px}
.arm{flex:1;margin:0;min-width:0} .arm img{width:100%;border-radius:4px;display:block}
figcaption{font-size:12.5px;color:#aaa;margin-top:4px} figcaption b{color:#fff}
.arm.a b{color:#8cf} .arm.b b{color:#9e9} .arm.c b{color:#fc8}
.none{height:120px;display:flex;align-items:center;justify-content:center;background:#222;color:#666}
.pick{display:flex;gap:12px;align-items:center;margin:2px 0 18px;font-size:14px}
.pick textarea{flex:1;background:#1d1d1d;color:#ddd;border:1px solid #444;border-radius:4px;font:13px system-ui}
.pick .saved{color:#7c7;font-size:12px;min-width:60px} .title{font-weight:600;color:#fff;margin-top:18px}
.small{font-size:12.5px;color:#999} .pickd{outline:2px solid #9e9}
.streets{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}
"""
    H = [f"<!doctype html><meta charset=utf-8><title>BOSON A/B: Austin scene, cloud vs this machine</title><style>{css}</style>",
         "<h1>Boson A/B: the Austin scene, cloud (A) vs this machine (B), and the hybrid (C)</h1>",
         '<div class="top">'
         f"<b>Pictures:</b> A {n['A']} (1 street, {len(plan)} plates, 12 takes) &middot; B {n['B']} ({len(streets)} "
         f"street versions, {b_plates} plates, {len(b_takes)} takes, {len(cards)} clothes cards) &middot; C {n['C']} takes. "
         f"<b>GPU minutes</b> (RTX 4090): Klein {gpu['klein']:.1f}, vision {gpu['vision']:.1f} ({esc(turn_txt)}). "
         f"<b>Network during B and C</b> (strace on every runner and on ComfyUI): "
         f"{'only this machine (127.0.0.1 and local sockets)' if not off else 'OFF-BOX: ' + esc(', '.join(off))}."
         "<br><b>The rule:</b> only the pictures change. Every B picture is drawn from A's logged words byte for byte "
         "(the Claude writer wrote the plate prompts in the cloud; Compile Scene builds the take prompts from A's "
         "SCENE.json). The dots are A's (the operator dotted A's pictures; B inherits them). Where A passed a picture as "
         "a reference, B passes B's own redraw of it. Klein's seed is a hash of the file name. Boxes (Locate): Gemini "
         "for A; Qwen3.8-27B with its vision projector, on this machine, for B and C. Masks: BiRefNet on CPU. "
         "Posters are flat slots: the words ask for a blank ad panel and the poster art is pasted at view (not shown "
         "here). A's takes show the blank panel; Klein often drew its own art into the panel in B and C (it did not "
         "follow 'blank'). Pick per pair; picks save as you click.</div>"]

    # ---- street
    srow = next(r for r in rows(ROOT / "design/reforge/scene/fan-03/nb-log.jsonl") if r["out"] == "gold-east-cesar-chavez.png")
    H.append("<h2>1. The street (the scene's base view)</h2>")
    H.append('<div class="streets">' + fig(STREET_A, f"drawn by {NB}, fan-out 03, 2026-10-24. Words: Claude (the agent, "
             "cloud), 10-24. Chosen by the operator (fan-03 #8). No references (text to image).", "a"))
    for p in streets:
        nb = next((r for r in rows(p.parent / "nb-log.jsonl") if r["out"] == p.name), {})
        H.append(fig(p, f"{p.name}: {KLEIN}, seed {nb.get('seed')}, {nb.get('seconds')} s, A's prompt byte for byte, no "
                        f"references. {esc(STREET_NOTES.get(p.name, ''))}", "b"))
    H.append("</div>" + picker("street", ["A", "B"]))
    H.append(f'<div class="small">A\'s street prompt ({len(srow["prompt"])} characters): {esc(srow["prompt"][:400])}...</div>')

    # ---- takes
    H.append("<h2>2. The takes (A's tree: 01 shoot; 02 outfit, 03 car on 01; 04 shoot; 05 car, 06-08 building on 04; "
             "09 outfit on 08; 10 corner building on 09; 11, 12 car on 10)</h2>")
    for tid in [f"{i:02d}" for i in range(1, 13)]:
        at = json.loads((A_SCENE / "takes" / tid / "take.json").read_text())
        ab = json.loads((A_SCENE / "takes" / tid / "boxes.json").read_text())
        what = at["op"] + (f" ({', '.join(at['swapped'])}) on take {at['parent']}" if at.get("swapped") else "")
        H.append(f'<div class="title">Take {tid}: {esc(what)}</div><div class="row">')
        H.append(fig(A_SCENE / "takes" / tid / "image.jpg",
                     f"drawn by {a_renderer(at.get('renderer'))}; boxes {esc(ab.get('model', 'Gemini'))} (cloud); "
                     "images sent: not recorded in take.json.", "a"))
        for arm, scene in (("b", "austin-stop-b"), ("c", "austin-stop-c")):
            r, cm = tk[(scene, tid)].get("render", {}), tk[(scene, tid)].get("commit", {})
            img = work / "scenes" / scene / "takes" / tid / "image.jpg"
            base = "B's Klein street (version s4)" if arm == "b" else "A's cloud street"
            words = {"exact": "A's prompt byte for byte", "spans": "A's prompt with this take's own Locate spans"}.get(
                r.get("words"), "?")
            miss = cm.get("missed")
            H.append(fig(img, f"drawn by {KLEIN}, seed {r.get('seed')}, {r.get('seconds')} s; base {base}; words: {words}; "
                              f"images sent: {esc(', '.join(r.get('labels', [])))}; boxes Qwen3.8 (this machine)"
                              + (f"; Locate missed: {esc(', '.join(miss))}" if miss else "") + ".", arm))
        H.append("</div>" + picker(f"take-{tid}", ["A", "B", "C"]))

    # ---- pieces
    cast = set()
    for c in sorted(A_SCENE.glob("takes/*/cast.json")):
        cast |= {p.split(":", 1)[1] for p in json.loads(c.read_text()).values() if not p.startswith("streets@")}
    H.append("<h2>3. The pieces (the 12 cast in A's takes first, then the in-context rounds' other candidates and the "
             "earlier plates they were drawn from)</h2>")
    crops = {"make-f420fd9d2797": "B's take 04 building crop (A's parent take not matched by key: the brief's take 04)",
             "make-6ea1ca391006": "B's take 08 corner-building crop (A's round matched take 08 by key)",
             "make-f5d8eedd69a1": "B's take 10 car crop (A's round matched take 10 by key). A's words say 'remove the "
                                  "white delivery van'; the crop in both arms shows take 10's sedan (A's words, kept)",
             "make-1a25bf320a66": "B's take 10 car crop (A's round matched take 10 by key); same van wording as above"}
    order = sorted(plan, key=lambda r: (r["file"] not in cast, r["studio"], r["file"]))
    shown_crop = set()
    for r in order:
        if r["commission"] and r["round"] not in shown_crop:
            shown_crop.add(r["round"])
            H.append(f'<div class="small">Commission image 1 for {r["round"]}: {esc(crops.get(r["round"], ""))}. A\'s crop was '
                     f'a temp file (not kept).</div><div class="row" style="max-width:40%">'
                     + fig(work / "crops" / f"{r['round']}.png", "B's crop, pad 0.15, as Slot Crop cuts it", "b") + "</div>")
        sha = r["manifest"]["studio_sha"]
        day = git(EX / r["studio"], "log", "-1", "--format=%cs", sha) or "?"
        rp = rep.get(r["file"], {})
        refs = ", ".join(pathlib.Path(x).name.replace("__d0__nbn.png", "") for x in r["refs"]) or "none"
        tag = "CAST" if r["file"] in cast else "candidate" if r["commission"] else "earlier plate (a reference)"
        H.append(f'<div class="title">{esc(r["studio"])} &middot; {esc(pathlib.Path(r["file"]).name.replace("__d0__nbn.png", ""))}'
                 f' <span class="small">({tag}, round {esc(r["round"])})</span></div><div class="row">')
        H.append(fig(EX / f"{r['studio']}-plates" / r["file"],
                     f"drawn by {a_renderer(r['manifest'].get('renderer'))} at {esc(r['aspect'])}; words: the studio's "
                     f"Claude writer (claude-opus-5-5, cloud), studio at {sha[:8]} ({day}); dots: the operator's, on A's "
                     f"rounds; refs: {esc(refs)} (A's Nano Banana plates" + (", A's take crop" if r["commission"] else "")
                     + ").", "a"))
        H.append(fig(work / "studios" / f"{r['studio']}-plates" / r["file"],
                     f"drawn by {KLEIN}, seed {rp.get('seed')}, {rp.get('seconds')} s; words: A's prompt byte for byte; "
                     f"refs: {esc(refs)} (B's own Klein redraws" + (", B's take crop" if r["commission"] else "") + ").", "b"))
        H.append("</div>" + picker(f"plate-{r['studio']}/{r['file']}", ["A", "B"]))

    js = """
const P = fetch('/picks').then(r => r.json());
document.querySelectorAll('.pick').forEach(el => {
  const id = el.dataset.id, ta = el.querySelector('textarea'), sv = el.querySelector('.saved');
  P.then(p => { const x = p[id]; if (!x) return; ta.value = x.note || '';
    const r = el.querySelector(`input[value="${x.pick}"]`); if (r) r.checked = true; });
  const save = () => { const r = el.querySelector('input:checked');
    fetch('/pick', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id, pick: r ? r.value : '', note: ta.value})})
      .then(x => x.json()).then(() => { sv.textContent = 'saved'; setTimeout(() => sv.textContent = '', 1500); }); };
  el.querySelectorAll('input').forEach(i => i.addEventListener('change', save));
  ta.addEventListener('change', save);
});"""
    H.append(f"<script>{js}</script>")
    (work / "page").mkdir(exist_ok=True)
    (work / "page" / "index.html").write_text("\n".join(H))
    text = re.sub(r"<script>.*?</script>", "", re.sub(r"<(?!/?script)[^>]+>", " ", "\n".join(H)), flags=re.S)
    (work / "page" / "text.md").write_text(re.sub(r"[ \t]+", " ", html.unescape(text)) + "\n")

    # ---- PROVENANCE.md
    P = ["# Provenance: arm B (and C) of the Austin A/B, 2026-10-27", "",
         "Every B and C picture was drawn on this machine by FLUX 3 Klein (flux3-image-klein-bf16, ComfyUI on the RTX "
         "4090, UUID-pinned). Words: A's, byte for byte (plate prompts: the Claude writer, cloud, 10-21..10-24; street: "
         "Claude, fan-out 03, 10-24; take prompts: Compile Scene from A's SCENE.json, swaps with this take's own Locate "
         "spans). Dots: A's (the operator's). Boxes: Qwen3.8-27B Q4_K_M + mmproj (llama-server on :8192). Masks: "
         "BiRefNet on CPU. No writer ran; no Nano Banana, Gemini or Claude call was made by any runner.", "",
         f"Inputs: B street = Klein from A's street prompt (4 versions, picked {B_STREET}); C street = A's cloud street "
         "(examples/streets/refs/01.jpg, Nano Banana 2.1). Pieces for B and C = B's Klein plates.", "",
         "## GPU turns", ""] + [f"- {nm} ({k}): {m} min" for nm, k, m in turns] + [
         f"- total: Klein {gpu['klein']:.1f} min, vision {gpu['vision']:.1f} min", "",
         "## strace connect destinations, by trace", ""]
    for name, c in tr.items():
        P.append(f"- {name}: " + (", ".join(f"{k} x{v}" for k, v in c.most_common()) or "no connects"))
    P += ["", f"Off-box destinations across all traces: {', '.join(off) or 'none'}.", ""]
    (work / "PROVENANCE.md").write_text("\n".join(P) + "\n")
    return work / "page" / "index.html"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default=str(pathlib.Path.home() / ".cache" / "boson-ab"))
    print(build(ap.parse_args().work))


if __name__ == "__main__":
    main()
