#!/usr/bin/env python3
"""Loopback proxy between maki's Gemini requests and Antigravity.

maki posts `/models/<id>:streamGenerateContent` with the bearer token and the
project as headers. The proxy wraps the body in the Cloud Code Assist envelope,
picks the reasoning level variant of the model, and strips the `response`
wrapper from each streamed chunk.
"""

import http.server
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HOST = "127.0.0.1"
PORT = 51123
API_URL = "https://daily-cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse"
USER_AGENT = "antigravity/cli/1.5.0 (aidev_client; os_type=darwin; arch=arm64; cl=1013440158; auth_method=consumer)"
PROJECT_HEADER = "x-antigravity-project"
MODEL_PREFIX = "/models/"
STREAM_SUFFIX = ":streamGenerateContent"
LEVELS = ("low", "medium", "high")
OFF_LEVEL = "low"
ADAPTIVE_LEVEL = "medium"
# maki sends models without "gemini" in the id a token budget instead of a
# level: 20, 40 and 60 percent of its ceiling for low, medium and high, where
# the ceiling is half the output cap and at most 32768.
MAX_BUDGET = 32768
MEDIUM_SHARE = 0.3
HIGH_SHARE = 0.5
STREAM_TIMEOUT_S = 600


def thinking_level(generation):
    config = generation.get("thinkingConfig")
    if config is None:
        return OFF_LEVEL
    if "thinkingLevel" in config:
        return config["thinkingLevel"].lower()
    if "thinkingBudget" not in config:
        return ADAPTIVE_LEVEL
    ceiling = min(generation.get("maxOutputTokens", 2 * MAX_BUDGET) // 2, MAX_BUDGET)
    share = config["thinkingBudget"] / ceiling
    if share < MEDIUM_SHARE:
        return "low"
    return "medium" if share < HIGH_SHARE else "high"


def upstream_model(model, request):
    if model.rsplit("-", 1)[-1] in LEVELS:
        return model
    return "%s-%s" % (model, thinking_level(request.get("generationConfig", {})))


def add_call_ids(contents):
    """Claude and GPT require ids on function calls and responses, which the
    Gemini format leaves out. An id comes from the call's position, so earlier
    turns stay byte-identical and keep their cache."""
    open_calls = []
    for turn, content in enumerate(contents):
        for index, part in enumerate(content.get("parts", [])):
            if "functionCall" in part:
                call = part["functionCall"]
                call["id"] = "call_%d_%d" % (turn, index)
                open_calls.append(call)
            elif "functionResponse" in part:
                response = part["functionResponse"]
                call = next((c for c in open_calls if c["name"] == response["name"]), None)
                if call:
                    open_calls.remove(call)
                    response["id"] = call["id"]


def unwrap(line):
    if not line.startswith(b"data:"):
        return line
    try:
        payload = json.loads(line[5:])
    except ValueError:
        return line
    return b"data: " + json.dumps(payload.get("response", payload)).encode() + b"\n"


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if not (path.startswith(MODEL_PREFIX) and path.endswith(STREAM_SUFFIX)):
            self.send_body(404, json.dumps({"error": {"message": "unsupported path " + path}}).encode())
            return
        model = urllib.parse.unquote(path[len(MODEL_PREFIX) : -len(STREAM_SUFFIX)])
        request = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)))
        add_call_ids(request.get("contents", []))
        envelope = {
            "project": self.headers.get(PROJECT_HEADER),
            "model": upstream_model(model, request),
            "request": request,
            "requestType": "agent",
            "userAgent": "antigravity",
            "requestId": "agent/maki/%d/%s/%d" % (time.time() * 1000, uuid.uuid4(), len(request.get("contents", []))),
        }
        headers = {
            "authorization": self.headers.get("authorization", ""),
            "content-type": "application/json",
            "user-agent": USER_AGENT,
        }
        try:
            upstream = urllib.request.urlopen(
                urllib.request.Request(API_URL, json.dumps(envelope).encode(), headers), timeout=STREAM_TIMEOUT_S
            )
        except urllib.error.HTTPError as err:
            self.send_body(err.code, err.read())
            return
        except OSError as err:
            self.send_body(502, json.dumps({"error": {"message": "Antigravity unreachable: %s" % err}}).encode())
            return
        with upstream:
            self.send_response(upstream.status)
            self.send_header("content-type", "text/event-stream")
            self.send_header("transfer-encoding", "chunked")
            self.end_headers()
            for line in upstream:
                self.write_chunk(unwrap(line))
            self.write_chunk(b"")

    def send_body(self, status, body):
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def write_chunk(self, data):
        self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
        self.wfile.flush()


def main():
    try:
        server = http.server.ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as err:
        sys.exit("cannot listen on %s:%d: %s" % (HOST, PORT, err))
    server.serve_forever()


if __name__ == "__main__":
    main()
