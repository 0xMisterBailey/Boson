#!/usr/bin/env python3
"""A vision model describes each studio reference, because the writer reads text only (T12 step 3, any field).

Top rung Gemini (key ~/.config/gemini/api_key); --port uses a local OpenAI-compatible VLM instead
(Qwen3.8 + mmproj, as in T12). Adds "vlm" and "vlm_model" to each line of refs.jsonl; resume-safe.

  python3 tools/describe_refs.py REFS_DIR --field "fashion photography" [--model gemini-3.1-pro-preview | --port 8099]
"""
import argparse, base64, json, pathlib, re, time, urllib.error, urllib.request

Q = ("You are describing a reference image for a {field} studio's art director who cannot see it. In "
     "120-180 words, plain prose, describe: the composition and framing, the setting and light, what the "
     "subject wears or is (cut, fabric, colour or tone as it reads), pose and gesture, the camera and print "
     "qualities as they look, and the one thing that makes this image distinctive. Describe only what is "
     "visible; no praise; do not name any real person.")


def gemini(model, img, q):
    key = pathlib.Path("~/.config/gemini/api_key").expanduser().read_text().strip()
    body = {"contents": [{"parts": [{"inline_data": {"mime_type": "image/jpeg",
                                                     "data": base64.b64encode(img.read_bytes()).decode()}},
                                    {"text": q}]}]}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        json.dumps(body).encode(), {"Content-Type": "application/json"})
    for wait in (5, 15, 45, 0):   # a busy Gemini (429/5xx) is retried; 2026-10-22 one 503 killed a forge run
        try:
            d = json.load(urllib.request.urlopen(req, timeout=300))
            break
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or not wait:
                raise
            print(f"  gemini {e.code}, retry in {wait}s", flush=True)
            time.sleep(wait)
    return "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"]).strip()


def local(port, img, q):
    b64 = base64.b64encode(img.read_bytes()).decode()
    body = {"messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        {"type": "text", "text": q}]}], "max_tokens": 1200, "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                                 json.dumps(body).encode(), {"Content-Type": "application/json"})
    txt = json.load(urllib.request.urlopen(req, timeout=600))["choices"][0]["message"]["content"] or ""
    return re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()


def agy(img, q, model="gemini-4-argon-medium"):
    """Google Antigravity's Gemini (the box's signed-in plan, `agy -p`): for when the API key has no credit."""
    import os, subprocess
    exe = os.environ.get("BOSON_AGY", str(pathlib.Path("~/dotfiles/launchpad/agy-cloud").expanduser()))
    task = (f"Open and look at the image file {img.resolve()} (view the image itself; do not search or browse). {q}\n"
            "Reply with one line that starts with DESCRIPTION: followed by your description, and nothing else.")
    r = subprocess.run([exe, "--model", model, "-p", task], capture_output=True, text=True, timeout=600)
    got = r.stdout.split("DESCRIPTION:", 1)
    if len(got) < 2:
        raise RuntimeError(f"agy gave no description for {img.name}: {(r.stdout + r.stderr)[-400:]}")
    return " ".join(got[1].split())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("refs")
    ap.add_argument("--field", required=True)
    ap.add_argument("--model", default="gemini-3.1-pro-preview")
    ap.add_argument("--port")
    ap.add_argument("--agy", action="store_true", help="describe through Antigravity's Gemini (agy -p)")
    a = ap.parse_args()
    refs = pathlib.Path(a.refs)
    path = refs / "refs.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    q = Q.format(field=a.field)
    name = f"local VLM :{a.port}" if a.port else ("antigravity:gemini-4-argon-medium" if a.agy else a.model)
    t0 = time.time()
    for k, r in enumerate(rows, 1):
        if not r.get("vlm"):
            img = refs / r["file"]
            r["vlm"] = local(a.port, img, q) if a.port else (agy(img, q) if a.agy else gemini(a.model, img, q))
            r["vlm_model"] = name
            path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows))
        el = time.time() - t0
        print(f"[{k}/{len(rows)}] {r['file']} {len(r['vlm'].split())} words  ETA {el / k * (len(rows) - k):.0f}s",
              flush=True)


if __name__ == "__main__":
    main()
