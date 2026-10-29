#!/usr/bin/env python3
"""The A/B page's tiny server, loopback only: serves WORK/page/index.html, the pictures it names (under A's examples/
or the A/B work dir, nothing else), and saves the operator's picks (A / B / C / tie + a free-text note per pair) to
WORK/picks.json.

  python3 tools/ab_serve.py [--work ~/.cache/boson-ab] [--port 8774]
"""
import argparse, http.server, json, pathlib, time, urllib.parse

ROOT = pathlib.Path(__file__).resolve().parents[1]


def make_handler(work):
    work = pathlib.Path(work).resolve()
    roots = [(ROOT / "examples").resolve(), (ROOT / "design").resolve(), work]
    picks = work / "picks.json"

    class H(http.server.BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=3600" if ctype.startswith("image") else "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path in ("/", "/index.html"):
                return self._send(200, (work / "page" / "index.html").read_bytes(), "text/html; charset=utf-8")
            if u.path == "/picks":
                return self._send(200, picks.read_bytes() if picks.exists() else b"{}")
            if u.path == "/f":
                p = pathlib.Path(urllib.parse.parse_qs(u.query).get("p", [""])[0]).resolve()
                if p.is_file() and any(p.is_relative_to(r) for r in roots):
                    ct = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(p.suffix.lower(),
                                                                                             "application/octet-stream")
                    return self._send(200, p.read_bytes(), ct)
            self._send(404, b"{}")

        def do_POST(self):
            if self.path != "/pick":
                return self._send(404, b"{}")
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if not d.get("id") or d.get("pick") not in ("A", "B", "C", "tie", ""):
                return self._send(400, b'{"error": "id and pick (A, B, C, tie) please"}')
            cur = json.loads(picks.read_text()) if picks.exists() else {}
            cur[d["id"]] = {"pick": d.get("pick", ""), "note": d.get("note", ""), "at": time.strftime("%Y-%m-%d %H:%M:%S")}
            picks.write_text(json.dumps(cur, indent=1) + "\n")
            self._send(200, json.dumps({"saved": d["id"], "count": len(cur)}).encode())

    return H


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default=str(pathlib.Path.home() / ".cache" / "boson-ab"))
    ap.add_argument("--port", type=int, default=8774)
    a = ap.parse_args()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(a.work))
    print(f"A/B page on http://127.0.0.1:{a.port}/ (picks -> {pathlib.Path(a.work) / 'picks.json'})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
