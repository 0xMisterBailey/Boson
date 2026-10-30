#!/usr/bin/env python3
"""feedback-engine: a one-keypress human-feedback UI for any binary judgment over cards. Vendored into Boson as the
grid behind `tools/loop.py NAME dots` (stdlib only; the same labels file `loop.py NAME dot` writes headlessly).

  python3 engine.py DECK.json [--labels OUT.jsonl] [--host 127.0.0.1] [--port 8765] [--matrix]

--matrix serves matrix.html at / instead: every card at once as image grids (card keys board/row/col), left-click
green, right-click red, double-click enlarges. Same labels file and API; /matrix and /cards reach either view.

DECK.json = {"config": {...}, "cards": [...]}; tools/loop.py (Loop.deck) writes the decks Boson serves.
Every action is appended to the labels file (default: DECK.labels.jsonl next to the deck). The latest record
per card id wins, and "undo" retracts. Stdlib only, no build step. Binds to 127.0.0.1 by default (this machine only); --host 0.0.0.0 or a
private-network address lets your other devices reach it.
"""
import argparse, json, mimetypes, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote
from pathlib import Path
from threading import Lock

HERE = Path(__file__).resolve().parent
PAGE = HERE / "engine.html"
MATRIX = HERE / "matrix.html"
DEFAULTS = {
    "title": "FEEDBACK", "question": "Is this right?",
    "yes": {"label": "YEP", "hint": "yes"}, "no": {"label": "NOPE", "hint": "no"},
    "tags": [], "tag_prompt": "why? (optional)",
    "fields": {"meta": "source", "context": "context", "top": "claim", "body": "passage",
               "image": "image", "left": "left", "right": "right",
               "left_label": "left_label", "right_label": "right_label"},
    "css": "",
    "field_labels": {"top": "CLAIM", "body": "PASSAGE"},
    "highlight_numbers": True, "round_size": 20, "footnote": "Go with your first read.",
    "formats": {},          # slot -> "text" | "markdown" | "json" | "code"
    "rows": [],             # [[card_key, LABEL], ...] shown between top and body
    "wikilink_url": "",     # e.g. "obsidian://open?vault=V&file={}"; empty = plain styled text
}
_lock = Lock()


def merged_config(cfg):
    out = {**DEFAULTS, **cfg}
    for k in ("yes", "no", "fields", "field_labels"):
        out[k] = {**DEFAULTS[k], **cfg.get(k, {})}
    return out


def current_labels(path):
    out = {}
    if path.exists():
        for line in path.open():
            r = json.loads(line)
            if r.get("op") == "note":
                continue                      # notes ride alongside; they are not a judgment
            if r.get("op") == "undo":
                out.pop(r["id"], None)
            else:
                out[r["id"]] = r
    return out


def current_notes(path):
    """id -> latest note text (an empty note clears it)."""
    out = {}
    if path.exists():
        for line in path.open():
            r = json.loads(line)
            if r.get("op") == "note":
                out[r["id"]] = r.get("note", "")
    return {k: v for k, v in out.items() if v}


def make_handler(deck_path, labels_path, matrix=False):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="application/json"):
            b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path in ("/", "/index.html", "/matrix", "/cards"):
                page = MATRIX if self.path == "/matrix" or (matrix and self.path != "/cards") else PAGE
                return self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            if self.path == "/api/state":  # deck re-read per request: edit the deck, reload the page
                deck = json.loads(deck_path.read_text())
                return self._send(200, {"config": merged_config(deck.get("config", {})),
                                        "queue": deck["cards"], "done": current_labels(labels_path),
                                        "notes": current_notes(labels_path)})
            if self.path.startswith("/media/"):   # cards may carry an image, served from the deck's folder
                name = unquote(self.path[len("/media/"):].split("?")[0])
                f = (deck_path.parent / name).resolve()
                if f.is_file() and deck_path.parent.resolve() in f.parents:
                    ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                    return self._send(200, f.read_bytes(), ctype)
                return self._send(404, {"error": "no such media"})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            r = json.loads(self.rfile.read(n) or b"{}")
            if self.path not in ("/api/label", "/api/undo", "/api/tag", "/api/note") or "id" not in r:
                return self._send(400, {"error": "bad request"})
            r["op"], r["ts"] = self.path.rsplit("/", 1)[-1], time.time()
            with _lock:
                if r["op"] == "tag":  # re-emit the existing label with the tag attached
                    cur = current_labels(labels_path).get(r["id"])
                    if not cur:
                        return self._send(409, {"error": "no label to tag"})
                    r = {**cur, "tag": r.get("tag"), "ts": r["ts"], "op": "label"}
                with labels_path.open("a") as f:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            self._send(200, {"ok": True})

        def log_message(self, *a):
            pass
    return H


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("deck", type=Path)
    ap.add_argument("--labels", type=Path)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--matrix", action="store_true", help="serve the grid view (matrix.html) at /")
    a = ap.parse_args()
    deck = a.deck.resolve()
    labels = (a.labels or deck.with_suffix(".labels.jsonl")).resolve()
    n = len(json.loads(deck.read_text())["cards"])
    print(f"feedback-engine{' (matrix)' if a.matrix else ''}: http://{a.host}:{a.port}/  deck={deck.name} ({n} cards, "
          f"{len(current_labels(labels))} labelled) -> {labels}", flush=True)
    ThreadingHTTPServer((a.host, a.port), make_handler(deck, labels, a.matrix)).serve_forever()


if __name__ == "__main__":
    main()
