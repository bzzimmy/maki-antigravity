import http.server
import json
import pathlib
import sys
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "proxy"))
import antigravity_proxy as proxy  # noqa: E402

PROMPT = {"contents": [{"role": "user", "parts": [{"text": "hello"}]}]}
STREAM = [
    b'data: {"response": {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}, "traceId": "t"}\n',
    b"\n",
]


def thinking(config, max_output=None):
    generation = {"thinkingConfig": config}
    if max_output:
        generation["maxOutputTokens"] = max_output
    return {"generationConfig": generation}


class UpstreamModelTest(unittest.TestCase):
    def test_level_comes_from_the_request(self):
        cases = [
            ("gemini-3.8-flash", thinking({"thinkingLevel": "high"}), "gemini-3.8-flash-high"),
            ("gemini-3.8-flash", thinking({"includeThoughts": True}), "gemini-3.8-flash-medium"),
            ("gemini-3.8-flash", {}, "gemini-3.8-flash-low"),
            ("claude-opus-5-5", thinking({"thinkingBudget": 1638}, 16384), "claude-opus-5-5-low"),
            ("claude-opus-5-5", thinking({"thinkingBudget": 3276}, 16384), "claude-opus-5-5-medium"),
            ("claude-opus-5-5", thinking({"thinkingBudget": 8192}, 16384), "claude-opus-5-5-high"),
            ("claude-opus-5-5", thinking({"thinkingBudget": 13107}, 128000), "claude-opus-5-5-medium"),
            ("claude-opus-5-5", thinking({"thinkingBudget": 19660}, 128000), "claude-opus-5-5-high"),
            ("gpt-oss-120b-medium", thinking({"thinkingBudget": 1024}, 32768), "gpt-oss-120b-medium"),
        ]
        for model, request, expected in cases:
            self.assertEqual(proxy.upstream_model(model, request), expected, (model, request))


class CallIdTest(unittest.TestCase):
    def test_responses_answer_the_oldest_open_call_of_their_name(self):
        def call(name):
            return {"functionCall": {"name": name, "args": {}}}

        def response(name):
            return {"functionResponse": {"name": name, "response": {}}}

        contents = [
            {"role": "user", "parts": [{"text": "go"}]},
            {"role": "model", "parts": [call("read"), call("read"), call("grep")]},
            {"role": "user", "parts": [response("grep"), response("read"), response("read")]},
        ]
        proxy.add_call_ids(contents)
        self.assertEqual([p["functionCall"]["id"] for p in contents[1]["parts"]], ["call_1_0", "call_1_1", "call_1_2"])
        self.assertEqual(
            [p["functionResponse"]["id"] for p in contents[2]["parts"]], ["call_1_2", "call_1_0", "call_1_1"]
        )


class FakeAntigravity(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.server.received = (self.headers, json.loads(self.rfile.read(int(self.headers["content-length"]))))
        body = b"".join(STREAM) if self.server.status == 200 else b'{"error": {"message": "quota"}}'
        self.send_response(self.server.status)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ProxyTest(unittest.TestCase):
    def post(self, status, model="gemini-3.8-flash"):
        upstream = http.server.HTTPServer(("127.0.0.1", 0), FakeAntigravity)
        upstream.status = status
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), proxy.Handler)
        for s in (upstream, server):
            threading.Thread(target=s.serve_forever, daemon=True).start()
            self.addCleanup(s.server_close)
            self.addCleanup(s.shutdown)
        request = urllib.request.Request(
            "http://127.0.0.1:%d/models/%s:streamGenerateContent?alt=sse" % (server.server_address[1], model),
            json.dumps(PROMPT).encode(),
            {"authorization": "Bearer tok", proxy.PROJECT_HEADER: "proj"},
        )
        with mock.patch.object(proxy, "API_URL", "http://127.0.0.1:%d/stream" % upstream.server_address[1]):
            with urllib.request.urlopen(request, timeout=5) as response:
                return upstream.received, response.read()

    def test_wraps_the_request_and_unwraps_the_stream(self):
        (headers, envelope), body = self.post(200)
        self.assertEqual(headers["authorization"], "Bearer tok")
        self.assertEqual(headers["user-agent"], proxy.USER_AGENT)
        self.assertEqual(envelope["project"], "proj")
        self.assertEqual(envelope["model"], "gemini-3.8-flash-low")
        self.assertEqual(envelope["request"], PROMPT)
        first, rest = body.split(b"\n", 1)
        self.assertEqual(json.loads(first[5:]), {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]})
        self.assertEqual(rest, b"\n")

    def test_passes_upstream_errors_through(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post(429)
        with caught.exception as error:
            self.assertEqual(error.code, 429)
            self.assertEqual(json.loads(error.read()), {"error": {"message": "quota"}})


if __name__ == "__main__":
    unittest.main()
