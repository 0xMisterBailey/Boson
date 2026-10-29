#!/usr/bin/env python3
"""Fetch a studio's reference works from Wikimedia Commons: public domain / CC0 only, license per file.

Picks files from a Commons category whose title or description matches --match, skips --exclude,
downloads a 960 px copy of each (Commons renders TIFF scans to JPEG at that size) and writes
refs/{NN.jpg, refs.jsonl} (the shape Forge reads).

  python3 tools/fetch_refs.py --category "Category:Photographs by Toni Frissell" \
      --match "fashion|model|vogue" --exclude "Kennedy|Kahlo" --maker "Toni Frissell" --out DIR/refs
"""
import argparse, html, json, pathlib, re, time, urllib.parse, urllib.request

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "BosonRefs/0.1 (studio reference fetch; github 0xMisterBailey)"}
PD = re.compile(r"public domain|^pd\b|pd-|cc0|no restrictions?", re.I)


def get(url, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for k in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception as e:  # 429 / transient
            print("  retry", k, e, flush=True)
            time.sleep(20 * (k + 1))
    raise RuntimeError(url)


def members(category):
    cont, out = {}, {}
    while True:
        d = json.loads(get(API, {"action": "query", "format": "json", "generator": "categorymembers",
                                 "gcmtitle": category, "gcmtype": "file", "gcmlimit": 100, "prop": "imageinfo",
                                 "iiprop": "url|extmetadata|mime|size", "iiurlwidth": 960, **cont}))
        for pid, pg in d.get("query", {}).get("pages", {}).items():  # imageinfo may arrive on a later page
            if pg.get("imageinfo") or pid not in out:
                out[pid] = pg
        if "continue" not in d:
            return sorted(out.values(), key=lambda p: p["title"])
        cont = d["continue"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--category", required=True)
    ap.add_argument("--match", required=True)
    ap.add_argument("--exclude", default="$^")
    ap.add_argument("--maker", default="")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows, stems = [], set()
    for p in members(a.category):
        ii = (p.get("imageinfo") or [{}])[0]
        em = ii.get("extmetadata", {})
        lic = em.get("LicenseShortName", {}).get("value", "")
        desc = html.unescape(re.sub("<[^>]+>", " ", em.get("ImageDescription", {}).get("value", ""))).strip()
        text = p["title"] + " " + desc
        stem = re.sub(r"\W+", "", p["title"].rsplit(".", 1)[0].lower())[:40]
        if (not PD.search(lic) or ii.get("mime") not in ("image/jpeg", "image/png", "image/tiff") or stem in stems
                or not re.search(a.match, text, re.I) or re.search(a.exclude, text, re.I)):
            continue
        stems.add(stem)
        k = len(rows) + 1
        img = out / f"{k:02d}.jpg"
        if not img.exists():  # resume-safe: same order, files already fetched are kept
            try:
                img.write_bytes(get(ii.get("thumburl") or ii["url"]))
            except RuntimeError as e:
                print(f"skip {p['title'][5:70]}: {e}", flush=True)
                stems.discard(stem)
                continue
            time.sleep(5)
        date = html.unescape(re.sub("<[^>]+>", "", em.get("DateTimeOriginal", {}).get("value", "")))[:40]
        rows.append({"n": k, "file": img.name, "title": p["title"][5:].rsplit(".", 1)[0], "maker": a.maker,
                     "year": date, "why": "", "url": ii["descriptionurl"], "image_url": ii["url"],
                     "license": lic, "commons_desc": desc[:400]})
        print(f"ok {k:02d} {p['title'][5:70]} ({lic})", flush=True)
        (out / "refs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        if len(rows) >= a.n:
            break
    print(f"{len(rows)} refs -> {out}")


if __name__ == "__main__":
    main()
