#!/usr/bin/env python3
"""Loopback proxy between maki's Gemini requests and Antigravity.

maki posts `/models/<id>:streamGenerateContent` with the bearer token, user
agent, and project as headers. The proxy adds tool call ids, wraps the body in
the Cloud Code Assist envelope, and strips the `response` wrapper from each
streamed chunk.
"""

import http.server
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HOST = "127.0.0.1"
PORT = 51123
API_URL = "https://daily-cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse"
PROJECT_HEADER = "x-antigravity-project"
MODEL_PREFIX = "/models/"
STREAM_SUFFIX = ":streamGenerateContent"
XHIGH_SUFFIX = "-xhigh"
XHIGH_THINKING_LEVEL = 100
STREAM_TIMEOUT_S = 600
SYSTEM_CA_FILES = ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt")


def ssl_context():
    """python.org macOS installers ship with no default CA bundle; fall back to
    the OS root store when OpenSSL reports neither cafile nor capath."""
    paths = ssl.get_default_verify_paths()
    if paths.cafile or paths.capath:
        return None
    for path in SYSTEM_CA_FILES:
        if os.path.exists(path):
            return ssl.create_default_context(cafile=path)
    return None


SSL_CONTEXT = ssl_context()


def apply_xhigh(model, request):
    """maki's google codec caps thinkingLevel at high, while Antigravity sends
    the proto enum value 100 for -xhigh models."""
    if not model.endswith(XHIGH_SUFFIX):
        return
    config = request.get("generationConfig", {}).get("thinkingConfig")
    if isinstance(config, dict):
        config["thinkingLevel"] = XHIGH_THINKING_LEVEL


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
        apply_xhigh(model, request)
        add_call_ids(request.get("contents", []))
        envelope = {
            "project": self.headers.get(PROJECT_HEADER),
            "model": model,
            "request": request,
            "requestType": "agent",
            "userAgent": "antigravity",
            "requestId": "agent/maki/%d/%s/%d" % (time.time() * 1000, uuid.uuid4(), len(request.get("contents", []))),
        }
        headers = {
            "authorization": self.headers.get("authorization", ""),
            "content-type": "application/json",
            "user-agent": self.headers.get("user-agent", ""),
        }
        try:
            upstream = urllib.request.urlopen(
                urllib.request.Request(API_URL, json.dumps(envelope).encode(), headers),
                timeout=STREAM_TIMEOUT_S,
                context=SSL_CONTEXT,
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
