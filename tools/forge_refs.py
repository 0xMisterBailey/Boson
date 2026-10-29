#!/usr/bin/env python3
"""A Forge Studio refs folder from the owner's own pictures (green dots, past work, anything on disk): NN.jpg +
refs.jsonl, the shape tools/fetch_refs.py writes for public-domain works. Describe them next (tools/describe_refs.py,
one vision call per picture): the writer reads text only.

  python3 tools/forge_refs.py OUT IMAGE_OR_DIR... [--why "what the owner loves in them"] [--maker NAME] [--private]

Each picture becomes refs/NN.jpg (RGB, long side <= 2048); its line names the source file, maker (default "the
owner"), license "owner's own (made for this studio)" and why. Refuses an OUT that already holds refs.jsonl.

--private (real references the owner found, round 39): license "found reference, private, not redistributed", maker
"unknown" unless given, url from the picture's own record (see source_url), and OUT/.gitignore keeps the pictures out
of the studio repo: a studio forged from it commits refs.jsonl (urls + descriptions), never the images.
"""
import argparse, json, os, pathlib, re, sys

from PIL import Image

EXT = (".png", ".jpg", ".jpeg", ".webp")
PRIVATE = "found reference, private, not redistributed"
URL = re.compile(r"https?://[^\s\"'<>]+")
LISTS = ("urls.txt", "sources.txt")       # one line per picture: "<file name> <url>"


def source_url(src):
    """Where a found picture came from, from what sits beside it (first hit wins), else "": a sidecar <stem>.url or
    <stem>.desktop (a dragged browser link: URL=...), <stem>.txt or <stem>.json ({"url" | "page_url" | "source": ...});
    a urls.txt or sources.txt line in its folder naming the file; a browser's download record, when it wrote one
    (xattr user.xdg.referrer.url, the page, then user.xdg.origin.url, the image). Never guessed from the file name."""
    src = pathlib.Path(src)
    for side in (src.with_suffix(".url"), src.with_suffix(".desktop"), src.with_suffix(".txt")):
        if side.is_file():
            m = URL.search(side.read_text(errors="replace"))
            if m:
                return m.group(0)
    side = src.with_suffix(".json")
    if side.is_file():
        try:
            d = json.loads(side.read_text())
            for k in ("page_url", "url", "source"):
                if isinstance(d.get(k), str) and URL.match(d[k]):
                    return d[k]
        except (ValueError, AttributeError):
            pass
    for lst in LISTS:
        f = src.parent / lst
        for line in f.read_text(errors="replace").splitlines() if f.is_file() else []:
            m = URL.search(line)
            if m and line.split()[0] in (src.name, src.stem):
                return m.group(0)
    for attr in ("user.xdg.referrer.url", "user.xdg.origin.url"):
        try:
            v = os.getxattr(src, attr).decode(errors="replace").strip()
            if URL.match(v):
                return v
        except (OSError, AttributeError):
            pass
    return ""


def build(out, sources, why="", maker=None, private=False):
    out = pathlib.Path(out).expanduser()
    if (out / "refs.jsonl").exists():
        raise SystemExit(f"{out}/refs.jsonl exists: pick a new folder")
    files = []
    for s in map(lambda x: pathlib.Path(x).expanduser(), sources):
        files += sorted(p for p in s.iterdir() if p.suffix.lower() in EXT) if s.is_dir() else [s]
    if not files:
        raise SystemExit("no pictures given")
    out.mkdir(parents=True, exist_ok=True)
    if private:   # copied into the studio with refs.jsonl: git add -A in the forge then skips the pictures
        (out / ".gitignore").write_text("# found references: private, never committed (round 39)\n" +
                                        "".join(f"*{e}\n" for e in EXT))
    maker = maker or ("unknown" if private else "the owner")
    rows = []
    for k, src in enumerate(files, 1):
        im = Image.open(src).convert("RGB")
        im.thumbnail((2048, 2048))
        im.save(out / f"{k:02d}.jpg", quality=92)
        rows.append({"n": k, "file": f"{k:02d}.jpg", "title": src.stem, "maker": maker, "year": "", "why": why,
                     "url": source_url(src) if private else "", "source": src.name,
                     "license": PRIVATE if private else "owner's own (made for this studio)"})
    (out / "refs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--why", default="")
    ap.add_argument("--maker", help='default "the owner", or "unknown" with --private')
    ap.add_argument("--private", action="store_true", help="found references: private license, urls, images not committed")
    a = ap.parse_args()
    rows = build(a.out, a.sources, a.why, a.maker, a.private)
    print(f"{len(rows)} refs in {a.out}; next: python3 tools/describe_refs.py {a.out} --field \"...\"", file=sys.stderr)


if __name__ == "__main__":
    main()
