#!/usr/bin/env python3
"""Which real references may appear on screen: ask Wikimedia Commons for each ref's licence and credit line.

The demo studios' refs are labelled "found reference, private, not redistributed". Those with a Commons file page
can be shown under their Commons licence; this writes a sidecar per studio (never into the studio repos, whose sha
must not move) saying which, and the exact credit to show:

  python3 tools/ref_licences.py --cache /tmp/boson-ref-licences      # -> refs-licences/<studio>.jsonl

Metadata only, no image downloads; one request per second, every answer cached raw in --cache so a rerun makes no
calls. Refs with no Commons URL get showable=false and the reason; nothing is guessed.
"""
import argparse, collections, hashlib, html, json, pathlib, re, sys, time, urllib.parse

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from fetch_refs import API, get  # noqa: E402  (same User-Agent and retry as the ref fetch)

STUDIOS = ["architecture-real", "cars-real", "cars-s4471-real", "fashion-real", "posters-real",
           "rockets-real", "robots-real", "terrain-real", "skybox-real",   # the sci-fi scene (10-29)
           "forest-real", "temple-real", "tree-real", "wizard-real"]       # the mystic forest (10-29)
FIELDS = ["LicenseShortName", "LicenseUrl", "License", "Artist", "Credit", "AttributionRequired", "UsageTerms"]
# Commons' Artist field is sometimes a note, not a name; the credit then uses the name the note itself asks for.
CREDIT_AS = {"File:Henderson Wave Bridge (I).jpg": "Supanut Arunoprayote"}  # "please mention me as the author"
SHOWABLE = re.compile(r"^(cc0|cc-zero|pd\b.*|public[- ]domain|cc-by-(sa-)?\d.*)$", re.I)


def title_from_url(url):
    """'https://commons.wikimedia.org/wiki/File:A%C3%A9.jpg' -> 'File:Aé.jpg'; None if not a Commons file page."""
    p = urllib.parse.urlparse(url or "")
    if p.netloc != "commons.wikimedia.org" or "/wiki/" not in p.path:
        return None
    t = urllib.parse.unquote(p.path.split("/wiki/", 1)[1]).replace("_", " ")
    return t if t.startswith("File:") else None


def fetch(title, cache):
    """The raw Commons answer for one file title, from cache when present (no call, no sleep)."""
    f = pathlib.Path(cache) / (hashlib.sha1(title.encode()).hexdigest()[:16] + ".json")
    if f.exists():
        return json.loads(f.read_text())
    d = json.loads(get(API, {"action": "query", "format": "json", "formatversion": 2, "titles": title,
                             "prop": "imageinfo", "iiprop": "extmetadata|url"}))
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"title": title, "answer": d}, ensure_ascii=False, indent=1))
    time.sleep(1)
    return {"title": title, "answer": d}


def text(v):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", v or ""))).strip()


def parse(answer):
    """One Commons query answer -> {found, meta{field: plain text}}. Follows normalized/redirected titles."""
    pages = (answer.get("query") or {}).get("pages") or []
    if isinstance(pages, dict):  # formatversion=1
        pages = list(pages.values())
    pg = next((p for p in pages if p.get("imageinfo")), None)
    if pg is None:
        return {"found": False, "meta": {}}
    em = pg["imageinfo"][0].get("extmetadata", {})
    return {"found": True, "meta": {k: text((em.get(k) or {}).get("value", "")) for k in FIELDS}}


def classify(meta):
    """(showable, reason). True for CC0, public domain, CC BY, CC BY-SA (a GFDL/CC BY-SA dual counts: BY-SA is on
    offer); anything else false with why."""
    key, short = meta.get("License", ""), meta.get("LicenseShortName", "")
    if SHOWABLE.match(key) or SHOWABLE.match(short.lower().replace(" ", "-")):
        return True, ""
    if not key and not short:
        return False, "Commons gives no licence for this file"
    return False, f"licence {short or key} is not CC0, PD, CC BY or CC BY-SA"


def credit(meta, title=""):
    """Commons' own attribution form: author, licence, via Wikimedia Commons."""
    author = CREDIT_AS.get(title) or meta.get("Artist") or "Unknown author"
    return f"{author}, {meta.get('LicenseShortName') or meta.get('License') or 'licence unknown'}, via Wikimedia Commons"


def row(ref, cache, fetcher=fetch):
    base = {"n": ref["n"], "file": ref["file"], "url": ref.get("url", "")}
    url = base["url"]
    title = title_from_url(url)
    if not url:
        return {**base, "licence": None, "licence_url": None, "author": None, "attribution": None,
                "showable": False, "reason": "no source URL recorded"}
    if not title:
        return {**base, "licence": None, "licence_url": None, "author": None, "attribution": None,
                "showable": False, "reason": f"no Commons record; source {urllib.parse.urlparse(url).netloc}"}
    p = parse(fetcher(title, cache)["answer"])
    if not p["found"]:
        return {**base, "licence": None, "licence_url": None, "author": None, "attribution": None,
                "showable": False, "reason": "not found on Commons"}
    m = p["meta"]
    ok, why = classify(m)
    return {**base, "licence": m["LicenseShortName"] or m["License"], "licence_url": m["LicenseUrl"] or None,
            "author": m["Artist"] or None, "attribution": credit(m, title), "showable": ok, "reason": why,
            "attribution_required": m["AttributionRequired"] or None, "usage_terms": m["UsageTerms"] or None,
            "commons_credit": m["Credit"] or None}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--studios", nargs="+", default=STUDIOS)
    ap.add_argument("--examples", default=str(ROOT / "examples"))
    ap.add_argument("--cache", default="/tmp/boson-ref-licences")
    ap.add_argument("--out", default=str(ROOT / "refs-licences"))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for s in a.studios:
        refs = [json.loads(l) for l in open(pathlib.Path(a.examples) / s / "refs" / "refs.jsonl") if l.strip()]
        rows = [row(r, a.cache) for r in refs]
        (out / f"{s}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        lic = collections.Counter(r["licence"] or f"none ({r['reason'].split(';')[0]})" for r in rows)
        shown = sum(r["showable"] for r in rows)
        print(f"{s}: {len(rows)} refs, {shown} showable | " + ", ".join(f"{k} {v}" for k, v in lic.most_common()),
              flush=True)


if __name__ == "__main__":
    main()
