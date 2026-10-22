import copy
import json
import os
import socket
import sys
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "src"))
from channel_adapter import rules as R, server  # noqa: E402

RULE = R.REGISTRY["drop-empty-system-message"].apply
# Claude Code 2.1.293 压缩后那一轮的真实形状（文本已脱敏）：messages[1] 是 content 为 [] 的 system 消息。
with open(os.path.join(HERE, "fixtures", "glm-compact-empty-system.json"), encoding="utf-8") as f:
    COMPACTED = f.read()

U = {"role": "user", "content": [{"type": "text", "text": "hi"}]}
A = {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}


def conv(system_content):
    return {"messages": [copy.deepcopy(U), {"role": "system", "content": system_content}, copy.deepcopy(A), copy.deepcopy(U)]}


class Rule(unittest.TestCase):
    def test_compacted_request_drops_empty_system_message(self):
        body = json.loads(COMPACTED)
        self.assertEqual(RULE(body, None), 1)
        self.assertEqual([m["role"] for m in body["messages"]], ["user", "assistant", "user", "system"])
        self.assertEqual(body["thinking"], {"type": "adaptive", "display": "updates"})

    def test_empty_string_and_empty_text_blocks_drop_the_message(self):
        for content in ("", [], [{"type": "text", "text": ""}], [{"type": "text", "text": ""}, {"type": "text", "text": ""}]):
            body = conv(content)
            self.assertEqual(RULE(body, None), 1, content)
            self.assertEqual([m["role"] for m in body["messages"]], ["user", "assistant", "user"])

    def test_mixed_blocks_keep_the_non_empty_ones(self):
        body = conv([{"type": "text", "text": ""}, {"type": "text", "text": "keep", "cache_control": {"type": "ephemeral"}}])
        self.assertEqual(RULE(body, None), 1)
        self.assertEqual(body["messages"][1], {"role": "system", "content": [{"type": "text", "text": "keep", "cache_control": {"type": "ephemeral"}}]})

    def test_non_empty_system_and_other_roles_untouched(self):
        for body in (conv("note"), conv([{"type": "text", "text": "note"}]), conv([{"type": "text", "text": " "}]),
                     {"messages": [{"role": "user", "content": ""}, {"role": "assistant", "content": []}]}, {"input": []}):
            before = copy.deepcopy(body)
            self.assertEqual(RULE(body, None), 0)
            self.assertEqual(body, before)


class Upstream(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        Upstream.seen.append((self.path, self.headers.get("host"), self.rfile.read(int(self.headers["content-length"]))))
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        self.wfile.write(b'event: message_start\ndata: {"type":"message_start"}\n\nevent: message_stop\ndata: {"type":"message_stop"}\n\n')


def serve_socks5(target_port, asked):
    """最小 SOCKS5（无认证、CONNECT、域名）：把名字 upstream.test 连到本地假上游，记下代理收到的目标。"""
    lsock = socket.create_server(("127.0.0.1", 0))

    def pipe(a, b):
        try:
            while True:
                d = a.recv(65536)
                if not d:
                    break
                b.sendall(d)
        except OSError:
            pass
        finally:
            for s in (a, b):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def handle(c):
        c.recv(3)
        c.sendall(b"\x05\x00")
        head = c.recv(5)
        name = c.recv(head[4]).decode()
        port = int.from_bytes(c.recv(2), "big")
        asked.append((name, port))
        if name != "upstream.test":
            c.sendall(b"\x05\x04\x00\x01" + bytes(6))
            c.close()
            return
        up = socket.create_connection(("127.0.0.1", target_port))
        c.sendall(b"\x05\x00\x00\x01" + bytes(6))
        threading.Thread(target=pipe, args=(c, up), daemon=True).start()
        threading.Thread(target=pipe, args=(up, c), daemon=True).start()

    def loop():
        while True:
            c, _ = lsock.accept()
            threading.Thread(target=handle, args=(c,), daemon=True).start()
    threading.Thread(target=loop, daemon=True).start()
    return lsock.getsockname()[1]


class Adapter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=cls.up.serve_forever, daemon=True).start()
        cls.asked = []
        socks_port = serve_socks5(cls.up.server_address[1], cls.asked)
        profile = server.load_profile("glm-gateway", os.path.join(HERE, "..", "profiles"))
        os.environ["UPSTREAM"] = "http://upstream.test:8080"   # 本机解析不到：只有经代理才连得上
        os.environ["UPSTREAM_SOCKS5"] = f"127.0.0.1:{socks_port}"
        try:
            handler = server.make_handler(profile)
        finally:
            os.environ.pop("UPSTREAM")
            os.environ.pop("UPSTREAM_SOCKS5")
        cls.ad = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.ad.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.ad.server_address[1]}/v1/messages"

    @classmethod
    def tearDownClass(cls):
        cls.up.shutdown()
        cls.ad.shutdown()

    def send(self, raw: bytes):
        Upstream.seen.clear()
        r = urllib.request.Request(self.url, data=raw, headers={"content-type": "application/json"})
        with urllib.request.urlopen(r, timeout=10) as x:
            out = (x.status, x.read())
        self.assertEqual(len(Upstream.seen), 1)
        return out, Upstream.seen[0]

    def test_compacted_request_is_fixed_and_streamed_back(self):
        (status, stream), (path, host, raw) = self.send(COMPACTED.encode())
        self.assertEqual((status, path, host), (200, "/v1/messages", "upstream.test:8080"))
        self.assertIn(b'"type":"message_stop"', stream)
        sent = json.loads(raw)
        expected = json.loads(COMPACTED)
        del expected["messages"][1]
        self.assertEqual(sent, expected)
        self.assertEqual(list(sent), list(expected))   # 改写只删那一条，字段顺序不变
        self.assertIn(("upstream.test", 8080), self.asked)

    def test_requests_without_empty_system_are_forwarded_byte_identical(self):
        # 刻意用非常规写法（空白、键序、数字与转义格式），任何重新序列化都会改变它们
        plain = b'{ "stream":true,"model" : "claude-opus-5-5","max_tokens":1.0e3,"messages":[{"role":"user","content":"caf\\u00e9"}],"thinking":{"type":"adaptive","display":"updates"} }'
        with_system = json.dumps(conv([{"type": "text", "text": "note"}]), indent=1).encode()
        for raw in (plain, with_system):
            _, (_, _, got) = self.send(raw)
            self.assertEqual(got, raw)


if __name__ == "__main__":
    unittest.main()
