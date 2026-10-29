#!/usr/bin/env python3
"""The open critic for the owner-only line (SPEC v3 §4.2, operator 1a): Qwen3.8-27B Q2.5 + mmproj, local.

It takes Argon's two jobs from T12, same shape, open weights:
  axes  STUDIO_DIR PORT              the forge read: 4-6 axes with two poles, every ref placed -> AXES.md
  read  STUDIO_DIR NN PLATES PORT    a round's drift read: every plate placed on the axes, drift from the
                                     refs' centre named -> history/round-NN/OPEN-READ.md (input to Digest)
Server (started by the caller): llama-server -m Qwen3.8-27B-Q2.5-v3-XYZ.gguf --mmproj
mmproj-Qwen3.8-27B-Q8_0.gguf -ngl 99 -c 32768 --port PORT --jinja
"""
import base64, io, json, pathlib, re, sys, time, urllib.request

MODEL = "Qwen3.8-27B-Q2.5-v3-XYZ + mmproj-Qwen3.8-27B-Q8_0 (local, open weights)"

AXES_Q = """You are the outside critic for a design studio. Its owner's studio sentence and context are below,
then its {n} reference prints (images in order, each followed by a text description).

{studio}

Draw the studio's aesthetic map. Write markdown:
- Title line: "# AXES (outside read: {model})".
- 4 to 6 axes. Each axis: "## Axis k: <name>", then "**Pole A: <name>** (<what it looks like>)" and
  "**Pole B: <name>** (<what it looks like>)". Axes must be visual and cultural (surface, symbolic mode,
  heraldic or emblematic code, composition, density, lettering), each one that these refs actually spread
  along, not a quality scale.
- Under every axis, every ref placed: "* **ref NN**: <at / near / tilted toward / midway> ..., because <what
  in the print puts it there>".
- Last: "## Centre": one short paragraph per axis naming where the refs cluster (the studio's centre).
Describe what is visible; no praise, no advice."""

READ_Q = """You are the outside critic for a design studio. Below: the studio's aesthetic map (AXES.md), then
round {nn}'s plates (images in order, each labelled), which the studio just made.

{axes}

Write the round's drift read in markdown:
- Title line: "# ROUND {nn} AXES READ (outside read: {model})".
- For each plate series ("## <series>"), one line per axis: where its plates sit and whether that is
  inside the studio's centre or drifting off it, naming the visible thing that puts it there and the ref
  it is closest to.
- Last: "## Round": what the round as a whole drifted toward or away from, in 3-5 sentences, naming
  cultural codes (heraldry, emblem, allegory, portrait, vignette) as well as layout.
This is input for the owner's digest, not a verdict: no scores, no keep/kill."""


def img_part(path, side=640):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    im.thumbnail((side, side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}}


def ask(port, parts, max_tokens=8000):
    body = {"messages": [{"role": "user", "content": parts}], "max_tokens": max_tokens, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        out = json.loads(r.read())
    txt = re.sub(r"<think>.*?</think>", "", out["choices"][0]["message"]["content"] or "", flags=re.S).strip()
    if out["choices"][0].get("finish_reason") == "length":
        raise RuntimeError("critic ran out of tokens; raise max_tokens")
    return txt


def axes(studio_dir, port):
    d = pathlib.Path(studio_dir)
    refs = [json.loads(l) for l in (d / "refs" / "refs.jsonl").read_text().splitlines() if l.strip()]
    studio = (d / "FORGE-INPUT.md").read_text() + "\n\n" + (d / "STUDIO.md").read_text()
    parts = [{"type": "text", "text": AXES_Q.format(n=len(refs), studio=studio, model=MODEL)}]
    for r in refs:
        parts += [{"type": "text", "text": f"ref {r['file'].split('.')[0]}:"}, img_part(d / "refs" / r["file"]),
                  {"type": "text", "text": r.get("vlm", "")}]
    t0 = time.time()
    txt = ask(port, parts)
    (d / "AXES.md").write_text(txt + "\n")
    print(f"AXES.md {len(txt.split())} words, {time.time() - t0:.0f}s", flush=True)


def read(studio_dir, nn, plates, port):
    d = pathlib.Path(studio_dir)
    files = sorted(pathlib.Path(plates).glob("*.png"))
    parts = [{"type": "text", "text": READ_Q.format(nn=nn, axes=(d / "AXES.md").read_text(), model=MODEL)}]
    for f in files:
        parts += [{"type": "text", "text": f"plate {f.name.split('__')[0]}:"}, img_part(f, 512)]
    t0 = time.time()
    txt = ask(port, parts)
    out = d / "history" / f"round-{nn}" / "OPEN-READ.md"
    out.write_text(txt + "\n")
    print(f"{out} {len(txt.split())} words over {len(files)} plates, {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    cmd, *a = sys.argv[1:] or ["-h"]
    if cmd not in ("axes", "read"):
        sys.exit(__doc__)
    {"axes": axes, "read": read}[cmd](*a)
