#!/usr/bin/env python3
"""Gather candidate reference photos from Wikimedia Commons search, in lanes, for an owner to dot (curate.py grid).

Open API only, spaced requests, ~1920 px thumbs, licence per file (CC0 / PD / CC BY / CC BY-SA; no NC, no ND).
Each lane is a CirrusSearch query (deepcat:"..." works); a lane takes its first --per-lane files that pass the filters.

  python3 tools/gather_commons.py --out refs-private/candidates/streets-local --lanes lanes.json --per-lane 6
  lanes.json: [{"lane": "portland", "city": "Portland, OR", "line": "Portland Streetcar",
                "query": "deepcat:\"Portland Streetcar\" stop"}, ...]

Writes the pictures (slug names), urls.txt ("file url"), why.tsv ("file<TAB>lane<TAB>why", factual: city, line,
date, the Commons description) and credits.jsonl (author, licence, url, image_url, per file). Resume-safe.
"""
import argparse, html, json, pathlib, re, time, urllib.parse, urllib.request

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "BosonRefs/0.1 (studio reference fetch; github 0xMisterBailey)"}
OK_LIC = re.compile(r"^(cc0|public domain|pd\b|pd-|cc by(-sa)? \d)", re.I)
BAD_LIC = re.compile(r"\bnc\b|\bnd\b|-nc|-nd", re.I)


def get(url, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for k in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - 429 / transient
            print("  retry", k, e, flush=True)
            time.sleep(20 * (k + 1))
    raise RuntimeError(url)


def clean(s):
    return " ".join(html.unescape(re.sub("<[^>]+>", " ", s or "")).split())


def search(query, limit=50):
    d = json.loads(get(API, {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
                             "gsrsearch": query + " filetype:bitmap", "gsrlimit": limit, "prop": "imageinfo",
                             "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 1920,
                             "iiextmetadatafilter": "LicenseShortName|DateTimeOriginal|Artist|ImageDescription"}))
    pages = sorted(d.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    return pages


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lanes", required=True, help="JSON list of {lane, city, line, query}")
    ap.add_argument("--per-lane", type=int, default=6)
    ap.add_argument("--min-year", type=int, default=2008)
    ap.add_argument("--min-width", type=int, default=1600)
    ap.add_argument("--exclude", default=r"crash|construction|interior|inside|map|diagram|logo|fireworks|aerial|"
                                         r"bike counter|depot|maintenance|barn|night|museum|model|test train|sign\b")
    ap.add_argument("--pause", type=float, default=6.0)
    ap.add_argument("--allow-portrait", action="store_true", help="keep portrait files too (default landscape only)")
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cred_p = out / "credits.jsonl"
    creds = {json.loads(l)["file"]: json.loads(l) for l in cred_p.read_text().splitlines()} if cred_p.exists() else {}
    seen = {c["url"] for c in creds.values()}
    t0 = time.time()
    lanes = json.loads(pathlib.Path(a.lanes).read_text())
    for li, ln in enumerate(lanes):
        have = sum(1 for c in creds.values() if c["lane"] == ln["lane"])
        for p in search(ln["query"]):
            if have >= a.per_lane:
                break
            ii = (p.get("imageinfo") or [{}])[0]
            em = ii.get("extmetadata", {})
            lic = clean(em.get("LicenseShortName", {}).get("value"))
            date = clean(em.get("DateTimeOriginal", {}).get("value"))
            yr = re.search(r"(19|20)\d\d", date)
            desc = clean(em.get("ImageDescription", {}).get("value"))
            title = p["title"][5:]
            if (ii.get("descriptionurl") in seen or not OK_LIC.search(lic) or BAD_LIC.search(lic)
                    or ii.get("mime") != "image/jpeg" or ii.get("width", 0) < a.min_width
                    or (not a.allow_portrait and ii.get("width", 0) < ii.get("height", 1))  # landscape only: the base street is 16:9
                    or not yr or int(yr.group()) < a.min_year or re.search(a.exclude, title + " " + desc, re.I)):
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", title.rsplit(".", 1)[0].lower()).strip("-")[:60]
            f = f"{ln['lane']}-{slug}.jpg"
            try:
                (out / f).write_bytes(get(ii.get("thumburl") or ii["url"]))
            except RuntimeError as e:
                print(f"skip {title[:60]}: {e}", flush=True)
                continue
            seen.add(ii["descriptionurl"])
            have += 1
            creds[f] = {"file": f, "lane": ln["lane"], "city": ln["city"], "line": ln["line"], "title": title,
                        "author": clean(em.get("Artist", {}).get("value"))[:120], "license": lic, "date": date[:40],
                        "url": ii["descriptionurl"], "image_url": ii["url"], "commons_desc": desc[:300]}
            cred_p.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in creds.values()))
            print(f"ok {f} ({lic}, {date[:10]})", flush=True)
            time.sleep(a.pause)
        el = time.time() - t0
        print(f"lane {li + 1}/{len(lanes)} {ln['lane']}: {have} | {el / 60:.1f} min, "
              f"ETA {el / (li + 1) * (len(lanes) - li - 1) / 60:.1f} min", flush=True)
        time.sleep(a.pause)
    rows = sorted(creds.values(), key=lambda c: [l["lane"] for l in lanes].index(c["lane"])
                  if c["lane"] in [l["lane"] for l in lanes] else 99)
    (out / "urls.txt").write_text("".join(f"{c['file']} {c['url']}\n" for c in rows))
    (out / "why.tsv").write_text("".join(
        f"{c['file']}\t{c['lane']}\t{c['city']}; {c['line']}; {c['date'][:10]}; {c['title']}"
        f"{'; ' + c['commons_desc'][:160] if c['commons_desc'] else ''}; {c['license']}, {c['author'][:60]}\n"
        for c in rows))
    print(f"{len(rows)} candidates -> {out}")


if __name__ == "__main__":
    main()
