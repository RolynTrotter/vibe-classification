"""A local stand-in for api.typesafe.ai, so tests never need a key or the network.

Answers are deterministic: a yes/no question is "yes" (0.9) when the item text contains
the word YES, "unsure" (0.5) when it contains MAYBE, and "no" (0.1) otherwise. A choice
picks the first option named in the text, falling back to the first option. A score
picks the level whose index appears as LEVEL<n>.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def answer(state, q):
    text = json.dumps(state)
    t = q["type"]
    if t == "noul":
        p = 0.9 if "YES" in text else 0.5 if "MAYBE" in text else 0.1
        return {"type": "noul", "noul": p}
    if t == "choice":
        opts = list(q["criteria"])
        pick = next((o for o in opts if o in text), opts[0])
        probs = {o: (0.85 if o == pick else 0.15 / max(1, len(opts) - 1)) for o in opts}
        return {"type": "choice", "choice": pick, "probabilities": probs, "confidence": 0.8}
    levels = q["criteria"]
    lvl = next((i for i in range(len(levels)) if f"LEVEL{i}" in text), 0)
    return {"type": "score", "score": float(lvl),
            "legend": {str(i): l for i, l in enumerate(levels)},
            "probabilities": {str(i): 1.0 if i == lvl else 0.0 for i in range(len(levels))},
            "confidence": 0.9}


class Handler(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Handler.calls.append(body)
        if self.headers.get("Authorization") != "Bearer test-key":
            return self.reply(401, {"detail": "bad key"})
        if "RATELIMIT" in json.dumps(body["state"]) and not getattr(Handler, "limited", False):
            Handler.limited = True
            return self.reply(429, {"detail": "slow down"}, {"retry-after": "0"})
        for qid, q in body["questions"].items():
            if q.get("type") not in ("noul", "choice", "score"):
                return self.reply(422, {"detail": f"bad question {qid}"})
        answers = {qid: answer(body["state"], q) for qid, q in body["questions"].items()}
        self.reply(200, {"model": "jev-fake", "answers": answers,
                         "usage": {"input_tokens": 100, "output_tokens": 10}})

    def reply(self, code, obj, headers=None):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)


def start():
    """-> (server, base_url). Call server.shutdown() when done."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"
