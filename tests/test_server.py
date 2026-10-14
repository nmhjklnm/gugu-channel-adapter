import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from channel_adapter import server  # noqa: E402

SEEN = []


class Up(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        SEEN.append(json.loads(body))
        if b"SSE" in body:
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data: {"type":"message_start"}\n\ndata: {"type":"message_stop"}\n\n')
            return
        if b"ERR" in body:
            out = {"type": "error", "error": {"type": "hapi_upstream_error", "message": "x"}}
        else:
            out = {"id": "m", "type": "message", "role": "assistant", "content": [{"type": "text", "text": "ok"}]}
        d = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.up = ThreadingHTTPServer(("127.0.0.1", 0), Up)
        threading.Thread(target=cls.up.serve_forever, daemon=True).start()
        os.environ["UPSTREAM"] = f"http://127.0.0.1:{cls.up.server_address[1]}"
        profile = {"name": "t", "upstream": os.environ["UPSTREAM"], "rules": ["schema-array-items", "pad-tool-result", "error-200-to-502"]}
        cls.ad = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(profile))
        threading.Thread(target=cls.ad.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.ad.server_address[1]}/v1/messages"
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("UPSTREAM", None)
        cls.up.shutdown()
        cls.ad.shutdown()

    def post(self, body):
        r = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
        try:
            x = urllib.request.urlopen(r, timeout=10)
            return x.status, x.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_request_is_fixed_before_forwarding(self):
        SEEN.clear()
        st, _ = self.post({"tools": [{"name": "t", "input_schema": {"type": "object", "properties": {"a": {"type": "array"}}}}],
                           "messages": [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "r"}]}]})
        self.assertEqual(st, 200)
        self.assertEqual(SEEN[-1]["tools"][0]["input_schema"]["properties"]["a"]["items"], {})
        self.assertEqual(SEEN[-1]["messages"][-1]["content"][-1]["text"], ".")

    def test_200_error_becomes_502_body_unchanged(self):
        st, body = self.post({"messages": [{"role": "user", "content": "ERR"}]})
        self.assertEqual(st, 502)
        self.assertEqual(json.loads(body)["type"], "error")

    def test_sse_passthrough(self):
        st, body = self.post({"messages": [{"role": "user", "content": "SSE"}]})
        self.assertEqual(st, 200)
        self.assertIn(b"message_stop", body)


if __name__ == "__main__":
    unittest.main()
