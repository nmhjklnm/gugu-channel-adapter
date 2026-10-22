"""转发服务：按 profile 里启用的规则修请求/改响应，其余原样透传（含流式）。只用标准库。"""
from __future__ import annotations

import http.client
import json
import os
import socket
import ssl
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import rules as R

HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
       "transfer-encoding", "upgrade", "content-length", "host"}


# The Node runtime implements exactly these rules; a profile cannot switch one of them off or add a Python rule.
NODE_RULES = ["hapi-error-envelope", "responses-reasoning-content"]


def _recv_exact(sock, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise OSError("socks5: proxy closed the connection")
        buf += chunk
    return buf


def socks5_connect(proxy: str, host: str, port: int, timeout: float) -> socket.socket:
    """经 SOCKS5（无认证）连到 host:port；域名交给代理解析（有的上游只在出口那头解析得到）。"""
    ph, pp = proxy.rsplit(":", 1)
    s = socket.create_connection((ph, int(pp)), timeout=timeout)
    try:
        s.sendall(b"\x05\x01\x00")
        if _recv_exact(s, 2) != b"\x05\x00":
            raise OSError("socks5: proxy refused no-auth")
        h = host.encode("idna")
        s.sendall(b"\x05\x01\x00\x03" + bytes([len(h)]) + h + port.to_bytes(2, "big"))
        rep = _recv_exact(s, 4)
        if rep[1] != 0:
            raise OSError(f"socks5: connect to {host}:{port} failed, reply {rep[1]}")
        _recv_exact(s, {1: 4, 4: 16}.get(rep[3]) or _recv_exact(s, 1)[0])
        _recv_exact(s, 2)
        return s
    except BaseException:
        s.close()
        raise


def load_profile(name_or_path: str, profiles_dir: str) -> dict:
    path = name_or_path if name_or_path.endswith(".json") else os.path.join(profiles_dir, name_or_path + ".json")
    with open(path, encoding="utf-8") as f:
        p = json.load(f)
    unknown = [i for i in p.get("rules", []) if i not in R.REGISTRY]
    if unknown:
        raise SystemExit(f"profile {p.get('name')} 引用了不存在的规则: {unknown}")
    runtime = p.get("runtime", "python")
    if runtime not in ("python", "node"):
        raise SystemExit(f"未知 runtime: {runtime}")
    if any(R.REGISTRY[i].runtime != runtime for i in p.get("rules", [])):
        raise SystemExit(f"profile {p.get('name')} 的规则与 runtime 不匹配")
    if runtime == "node" and (p.get("rules") != NODE_RULES or p.get("upstream") != "https://hapi.hc11.org"):
        raise SystemExit(f"HAPI Node runtime 只支持固定 HAPI 上游及 {NODE_RULES} 规则")
    return p


def make_handler(profile: dict, read_timeout: int = 900):
    if profile.get("runtime", "python") != "python":
        raise ValueError("此 profile 使用 Node HTTP runtime，请通过 channel_adapter serve 启动")
    upstream = os.environ.get("UPSTREAM") or profile["upstream"]   # 允许部署时/测试时覆盖
    proxy = os.environ.get("UPSTREAM_SOCKS5")   # 部署时给：上游只能经这个出口到达（host:port）
    req_rules = R.request_rules(profile["rules"])
    resp_rules = R.response_rules(profile["rules"])

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"      # 以关连接结束响应：流式不用算长度

        def log_message(self, *a):
            pass

        def _proxy(self):
            n = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(n) if n else b""
            note = []
            if raw and "json" in (self.headers.get("content-type") or ""):
                try:
                    body = json.loads(raw)
                    if isinstance(body, dict):
                        for r in req_rules:
                            c = r.apply(body, None)
                            if c:
                                note.append(f"{r.id}={c}")
                        if note:
                            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
                except Exception as e:
                    note.append(f"json-parse-failed:{type(e).__name__}")
            u = urllib.parse.urlparse(upstream)
            kw = {"context": ssl.create_default_context()} if u.scheme == "https" else {}
            cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
            conn = cls(u.hostname, u.port, timeout=read_timeout, **kw)
            hdr = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
            hdr["Host"] = u.netloc
            if raw:
                hdr["Content-Length"] = str(len(raw))
            try:
                if proxy:
                    port = u.port or (443 if u.scheme == "https" else 80)
                    sock = socks5_connect(proxy, u.hostname, port, read_timeout)
                    conn.sock = kw["context"].wrap_socket(sock, server_hostname=u.hostname) if u.scheme == "https" else sock
                conn.request(self.command, self.path, body=raw or None, headers=hdr)
                r = conn.getresponse()
            except Exception as e:
                msg = json.dumps({"error": {"type": "adapter_upstream_error", "message": f"适配层连不上上游: {type(e).__name__}"}}).encode()
                self.send_response(502)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(msg)
                return
            status, first = r.status, None
            ctype = r.getheader("content-type") or ""
            if resp_rules and ctype.lower().startswith("application/json"):
                first = r.read()
                for rr in resp_rules:
                    new = rr.apply(status, ctype, first)
                    if new and new != status:
                        note.append(f"{rr.id}:{status}->{new}")
                        status = new
            self.send_response(status)
            for k, v in r.getheaders():
                if k.lower() not in HOP:
                    self.send_header(k, v)
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                if first is not None:
                    self.wfile.write(first)
                    self.wfile.flush()
                else:
                    while True:
                        chunk = r.read(4096)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                conn.close()
            sys.stderr.write(f"{self.command} {self.path} -> {status}" + (" [" + " ".join(note) + "]" if note else "") + "\n")
            sys.stderr.flush()

        do_POST = do_GET = _proxy

    return H


def serve(profile: dict, bind: str, port: int):
    srv = ThreadingHTTPServer((bind, port), make_handler(profile))
    srv.daemon_threads = True
    via = f" via socks5 {os.environ['UPSTREAM_SOCKS5']}" if os.environ.get("UPSTREAM_SOCKS5") else ""
    sys.stderr.write(f"gugu-channel-adapter profile={profile['name']} {bind}:{port} -> {os.environ.get('UPSTREAM') or profile['upstream']}{via}\n")
    for i in profile["rules"]:
        sys.stderr.write(f"  规则 {i}: {R.REGISTRY[i].what}\n")
    sys.stderr.flush()
    srv.serve_forever()
