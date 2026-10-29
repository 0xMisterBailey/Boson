#!/usr/bin/env python3
"""Agents gather, the owner picks (round 40): candidate references on the dot grid, greens become a studio's refs.

  python3 tools/curate.py cars grid [--port 8773]   # candidates on the grid; dot them, write a direction, Ctrl-C
  python3 tools/curate.py cars keep                 # greens -> refs-private/cars/ (+ urls.txt); prints the direction

Candidates live in refs-private/candidates/FIELD/ (gitignored): the pictures, `urls.txt` ("file url", the page it came
from) and `why.tsv` ("file<TAB>lane<TAB>why", the gatherer's reason). The deck and its dots live in
$BOSON_HOME/curate/FIELD/; a re-gather into the same folder keeps every dot already given (cards are keyed by file name).
Then forge as usual: python3 tools/loop.py FIELD forge ... (docs/REAL-REFS.md).
"""
import argparse, hashlib, json, os, pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "boson"))
import grid as gr  # noqa: E402

ENGINE = pathlib.Path(os.environ.get("BOSON_ENGINE", "~/feedback-engine/engine.py")).expanduser()
HOME = pathlib.Path(os.environ.get("BOSON_HOME", "~/.cache/boson")).expanduser() / "curate"
PRIVATE = ROOT / "refs-private"
DIRECTION = "direction"      # the card whose note is the owner's direction sentence
PER_ROW = 8
EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def log(*a):
    print(*a, flush=True)


def read_pairs(path, sep=None, n=2):
    """file -> rest of the line, from urls.txt ("file url") or why.tsv ("file<TAB>lane<TAB>why")."""
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            parts = line.strip().split(sep, n - 1)
            if len(parts) == n and parts[0]:
                out[parts[0]] = parts[1:] if n > 2 else parts[1]
    return out


def dhash(im, k=8):
    g = im.convert("L").resize((k + 1, k))
    px = list(g.getdata())
    return sum(1 << i for i in range(k * k) if px[(i // k) * (k + 1) + i % k] > px[(i // k) * (k + 1) + i % k + 1])


def candidates(field):
    """The gatherer's pictures in why.tsv order, exact and near duplicates dropped (logged)."""
    from PIL import Image
    src = PRIVATE / "candidates" / field
    if not src.is_dir():
        sys.exit(f"no candidates yet: {src}")
    urls, why = read_pairs(src / "urls.txt"), read_pairs(src / "why.tsv", "\t", 3)
    files = [f for f in why if (src / f).exists()]
    files += sorted(p.name for p in src.iterdir() if p.suffix.lower() in EXTS and p.name not in why)
    seen_md5, seen_h, out = {}, [], []
    for f in files:
        p = src / f
        md5 = hashlib.md5(p.read_bytes()).hexdigest()
        try:
            im = Image.open(p)
            im.load()
        except Exception as e:  # noqa: BLE001 - a broken download is skipped, not fatal
            log(f"skip {f}: unreadable ({e})")
            continue
        h = dhash(im)
        near = next((g for g, hh in seen_h if bin(h ^ hh).count("1") <= 4), None)
        if md5 in seen_md5 or near:
            log(f"skip {f}: duplicate of {seen_md5.get(md5) or near}")
            continue
        seen_md5[md5] = f
        seen_h.append((f, h))
        lane, reason = why.get(f, ["unsorted", ""])
        out.append({"file": f, "path": p, "url": urls.get(f, ""), "lane": lane, "why": reason, "size": im.size})
    return out


def placard(path, field):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (900, 1100), (24, 24, 28))
    d = ImageDraw.Draw(im)
    big, small = ImageFont.truetype(gr.FONT, 64), ImageFont.truetype(gr.FONT, 34)
    d.text((70, 300), field.upper(), font=big, fill=(240, 200, 90))
    d.text((70, 390), "DIRECTION", font=big, fill=(240, 240, 240))
    for i, line in enumerate(["Write one sentence in the", "note box below: what this", "studio's work must be, or",
                              "what to gather instead.", "", "Enter saves. No dot needed."]):
        d.text((70, 540 + i * 52), line, font=small, fill=(200, 200, 200))
    im.save(path, quality=90)


def deck(field):
    from PIL import Image
    d = HOME / field
    cards_dir = d / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    cs = candidates(field)
    lanes = list(dict.fromkeys(c["lane"] for c in cs))
    cards = []
    for lane in lanes:
        group = [c for c in cs if c["lane"] == lane]
        for i, c in enumerate(group):
            dst = cards_dir / (pathlib.Path(c["file"]).stem + ".jpg")
            if not dst.exists() or dst.stat().st_mtime < c["path"].stat().st_mtime:
                im = Image.open(c["path"]).convert("RGB")
                im.thumbnail((1600, 1600))
                im.save(dst, quality=88)
            a = i // PER_ROW * PER_ROW
            cards.append({"id": c["file"], "board": f"{lane} ({len(group)})",
                          "row": f"{a + 1}-{min(a + PER_ROW, len(group))}", "col": pathlib.Path(c["file"]).stem,
                          "caption": pathlib.Path(c["file"]).stem, "image": f"cards/{dst.name}", "gold": None,
                          "detail": f"{c['why']}\n\n{c['url'] or '(no source link)'}\n{c['size'][0]}x{c['size'][1]}"})
    placard(cards_dir / "direction.jpg", field)
    cards.append({"id": DIRECTION, "board": "your direction", "row": "", "col": "direction", "caption": "DIRECTION",
                  "image": "cards/direction.jpg", "gold": None,
                  "detail": "Write one sentence in the note box under this card: what this studio's work must be, "
                            "or what the agents should gather instead. No dot needed here."})
    out = {"config": {"title": f"BOSON · {field} · CANDIDATE REFERENCES",
                      "question": "Green = keep as a reference. Red = not this. Then the direction card's note box.",
                      "yes": {"label": "GREEN DOT"}, "no": {"label": "RED DOT"},
                      "tags": ["render or AI", "stock look", "dark", "not my taste", "duplicate"],
                      "fields": {"meta": "board", "top": "caption", "body": "detail", "image": "image"},
                      "field_labels": {"top": "CANDIDATE", "body": "WHY THE AGENT PICKED IT, THEN ITS SOURCE"}},
           "cards": cards}
    (d / "DECK.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    log(f"{field}: {len(cards) - 1} candidates in {len(lanes)} lanes ({', '.join(lanes)}) -> {d / 'DECK.json'}")
    return d / "DECK.json"


def labels(field):
    sys.path.insert(0, str(ENGINE.parent))
    import engine
    p = HOME / field / "DECK.labels.jsonl"
    got, notes = engine.current_labels(p), engine.current_notes(p)
    return got, notes


def keep(field):
    """Greens -> refs-private/FIELD/ with their urls.txt lines; reds stay in candidates. Rerun-safe."""
    got, notes = labels(field)
    src, dst = PRIVATE / "candidates" / field, PRIVATE / field
    dst.mkdir(parents=True, exist_ok=True)
    urls = read_pairs(src / "urls.txt")
    have = read_pairs(dst / "urls.txt")
    greens = [k for k, v in got.items() if v.get("label") == 1 and k != DIRECTION and (src / k).exists()]
    reds = [k for k, v in got.items() if v.get("label") == 0 and k != DIRECTION]
    lines = []
    for f in greens:
        shutil.copy2(src / f, dst / f)
        if f not in have and urls.get(f):
            lines.append(f"{f} {urls[f]}")
    if lines:
        with (dst / "urls.txt").open("a") as fh:
            fh.write("\n".join(lines) + "\n")
    direction = " ".join(notes.get(DIRECTION, "").split())
    (HOME / field / "direction.txt").write_text(direction + "\n")
    log(f"{field}: {len(greens)} green -> {dst} ({len(lines)} new urls), {len(reds)} red, "
        f"{len(notes) - (DIRECTION in notes)} notes")
    log(f"direction: {direction or '(none written yet)'}")
    for k, v in notes.items():
        if k != DIRECTION:
            log(f"  note {k}: {v}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("field", help="the folder in refs-private/candidates/ (cars, architecture, ...)")
    ap.add_argument("step", choices=["grid", "keep"])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8773)
    ap.add_argument("--no-serve", action="store_true", help="grid: write the deck only")
    a = ap.parse_args()
    if a.step == "keep":
        return keep(a.field)
    path = deck(a.field)
    if a.no_serve:
        return
    log(f"open http://{a.host}:{a.port}/ in the browser on the remote desktop. Left-click = green, right-click = red, "
        f"type your direction under the last card (Enter saves).\nDone: Ctrl-C here, then python3 tools/curate.py "
        f"{a.field} keep")
    try:
        subprocess.run([sys.executable, str(ENGINE), str(path), "--matrix", "--host", a.host, "--port", str(a.port)])
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
