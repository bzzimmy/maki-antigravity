"""Tests for the `providers/antigravity` script: paths, token handling, the
auth JSON maki reads, login input parsing, and the request proxy."""

import http.server
import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import tempfile
import threading
import unittest
import urllib.request
from unittest import mock

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "providers" / "antigravity"
LOADER = importlib.machinery.SourceFileLoader("antigravity_provider", str(SCRIPT))
SPEC = importlib.util.spec_from_loader("antigravity_provider", LOADER)
provider = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(provider)

TOKENS = {"access": "tok", "refresh": "r", "expires": 0, "project": "proj-1"}


def isolated_home():
    home = tempfile.TemporaryDirectory()
    patch = mock.patch.dict(os.environ, {"HOME": home.name, "XDG_STATE_HOME": os.path.join(home.name, "st")})
    return home, patch


class PathsTest(unittest.TestCase):
    def test_state_dir_follows_xdg_and_the_legacy_directory(self):
        home, patch = isolated_home()
        with home, patch:
            self.assertEqual(provider.state_dir(), os.path.join(home.name, "st", "maki"))
            self.assertEqual(provider.token_path(), os.path.join(home.name, "st", "maki", "auth", "antigravity.json"))
            os.mkdir(os.path.join(home.name, ".maki"))
            self.assertEqual(provider.state_dir(), os.path.join(home.name, ".maki"))


class TokensTest(unittest.TestCase):
    def test_round_trip_is_private_and_validated(self):
        home, patch = isolated_home()
        with home, patch:
            self.assertIsNone(provider.load_tokens())
            tokens = dict(TOKENS, expires=provider.now_ms() + 10_000)
            provider.save_tokens(tokens)
            self.assertEqual(provider.load_tokens(), tokens)
            self.assertEqual(os.stat(provider.token_path()).st_mode & 0o777, 0o600)
            self.assertFalse(provider.expires_within(tokens, 5))
            self.assertTrue(provider.expires_within(tokens, 20))
            provider.save_tokens({"access": "a", "refresh": "r", "expires": 1})
            self.assertIsNone(provider.load_tokens(), "a token file without a project is not usable")

    def test_tokens_from_response_keeps_project_email_and_previous_refresh(self):
        fresh = provider.tokens_from_response({"access_token": "a", "refresh_token": "r", "expires_in": 3600})
        self.assertGreater(fresh["expires"], provider.now_ms())
        fresh.update(project="proj-1", email="me@example.com")
        rotated = provider.tokens_from_response({"access_token": "b", "expires_in": 60}, fresh)
        self.assertEqual(rotated["refresh"], "r")
        self.assertEqual(rotated["project"], "proj-1")
        self.assertEqual(rotated["email"], "me@example.com")
        with self.assertRaises(provider.Fail):
            provider.tokens_from_response({"access_token": "a"})

    def test_auth_json_points_at_the_proxy_with_the_bearer_header(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            provider.emit_auth(TOKENS)
        self.assertEqual(
            json.loads(out.getvalue()),
            {"base_url": provider.PROXY_URL, "headers": {"authorization": "Bearer tok"}},
        )

    def test_extract_project_reads_every_shape(self):
        self.assertEqual(provider.extract_project({"cloudaicompanionProject": "p"}), "p")
        self.assertEqual(provider.extract_project({"cloudaicompanionProject": {"id": "p"}}), "p")
        self.assertIsNone(provider.extract_project({"other": "p"}))


class CommandsTest(unittest.TestCase):
    def test_info_and_models_describe_a_google_provider(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(provider.main(["antigravity", "info"]), 0)
        info = json.loads(out.getvalue())
        self.assertEqual(info, {"display_name": provider.DISPLAY_NAME, "base": "google", "has_auth": True})
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(provider.main(["antigravity", "models"]), 0)
        models = json.loads(out.getvalue())
        self.assertEqual([m["id"] for m in models], [m[0] for m in provider.MODELS])
        self.assertTrue(all(m["supports_thinking"] for m in models))

    def test_resolve_and_status_without_tokens(self):
        home, patch = isolated_home()
        with home, patch:
            with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
                self.assertEqual(provider.main(["antigravity", "resolve"]), 1)
            self.assertEqual(err.getvalue().strip(), provider.NOT_LOGGED_IN)
            with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                self.assertEqual(provider.main(["antigravity", "status"]), 0)
            self.assertEqual(
                json.loads(out.getvalue()),
                {"logged_in": False, "email": None, "project": None, "expires_in_s": None},
            )

    def test_unknown_command_is_usage(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(provider.main(["antigravity", "bogus"]), 2)
            self.assertEqual(provider.main(["antigravity"]), 2)


class LoginInputTest(unittest.TestCase):
    def test_parse_authorization_input_accepts_every_shape(self):
        url = provider.REDIRECT_URI + "?code=abc&state=xyz"
        self.assertEqual(provider.parse_authorization_input(url), ("abc", "xyz"))
        self.assertEqual(provider.parse_authorization_input("abc#xyz\n"), ("abc", "xyz"))
        self.assertEqual(provider.parse_authorization_input("code=abc&state=xyz"), ("abc", "xyz"))
        self.assertEqual(provider.parse_authorization_input("  abc "), ("abc", None))
        self.assertEqual(provider.parse_authorization_input("   "), (None, None))


class FakeUpstream(http.server.BaseHTTPRequestHandler):
    """Stands in for Antigravity: records the envelope, answers wrapped SSE."""

    received = []

    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        FakeUpstream.received.append((self.path, dict(self.headers), body))
        chunks = [
            b'data: {"response": {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}}\n',
            b"\n",
            b'data: {"response": {"usageMetadata": {"promptTokenCount": 1}}}\n',
        ]
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(sum(len(c) for c in chunks)))
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(chunk)


class ProxyTest(unittest.TestCase):
    def test_unwrap_sse_line(self):
        self.assertEqual(provider.unwrap_sse_line(b'data: {"response": {"a": 1}}\n'), b'data: {"a": 1}\n')
        self.assertEqual(provider.unwrap_sse_line(b'data: {"a": 1}\n'), b'data: {"a": 1}\n')
        self.assertEqual(provider.unwrap_sse_line(b"\n"), b"\n")
        self.assertEqual(provider.unwrap_sse_line(b"data: not json\n"), b"data: not json\n")

    def test_proxy_wraps_the_request_and_unwraps_the_stream(self):
        upstream = http.server.HTTPServer(("127.0.0.1", 0), FakeUpstream)
        proxy = provider.ProxyServer(("127.0.0.1", 0), provider.ProxyHandler)
        for server in (upstream, proxy):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        home, patch = isolated_home()
        api_url = "http://127.0.0.1:%d" % upstream.server_address[1]
        with home, patch, mock.patch.object(provider, "API_URL", api_url):
            provider.save_tokens(TOKENS)
            inner = {"contents": [{"role": "user", "parts": [{"text": "hello"}]}]}
            request = urllib.request.Request(
                "http://127.0.0.1:%d/models/gemini-3.8-flash-high:streamGenerateContent?alt=sse" % proxy.server_address[1],
                data=json.dumps(inner).encode("utf-8"),
                headers={"authorization": "Bearer tok", "content-type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                lines = response.read().split(b"\n")
        for server in (upstream, proxy):
            server.shutdown()
            server.server_close()
        path, headers, envelope = FakeUpstream.received[-1]
        self.assertEqual(path, "/v1internal:streamGenerateContent?alt=sse")
        self.assertEqual(headers["Authorization"], "Bearer tok")
        self.assertEqual(envelope["project"], "proj-1")
        self.assertEqual(envelope["model"], "gemini-3.8-flash-high")
        self.assertEqual(envelope["request"], inner)
        self.assertEqual(envelope["requestType"], "agent")
        self.assertTrue(envelope["requestId"].endswith("/1"))
        self.assertEqual(json.loads(lines[0][5:]), {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]})
        self.assertEqual(lines[1], b"")
        self.assertEqual(json.loads(lines[2][5:]), {"usageMetadata": {"promptTokenCount": 1}})

    def test_proxy_rejects_when_not_logged_in(self):
        proxy = provider.ProxyServer(("127.0.0.1", 0), provider.ProxyHandler)
        threading.Thread(target=proxy.serve_forever, daemon=True).start()
        home, patch = isolated_home()
        with home, patch:
            request = urllib.request.Request(
                "http://127.0.0.1:%d/models/x:streamGenerateContent" % proxy.server_address[1],
                data=b"{}",
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=5)
        proxy.shutdown()
        proxy.server_close()
        with caught.exception as error:
            self.assertEqual(error.code, 401)
            self.assertEqual(json.loads(error.read())["error"]["message"], provider.NOT_LOGGED_IN)


if __name__ == "__main__":
    unittest.main()
