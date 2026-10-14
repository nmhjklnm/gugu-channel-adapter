#!/usr/bin/env python3
"""最小 MCP stdio 服务: 两个工具, schema 故意带 Gemini 后端拒收的写法(数组缺 items、required 含未定义字段)。"""
import json, sys
TOOLS = [
 {"name": "query_stub", "description": "查询桩(schema 带嵌套数组缺 items 与 required 里的未定义字段)",
  "inputSchema": {"type": "object", "properties": {"action": {"type": "string"},
      "query": {"type": "object", "properties": {"where": {"type": "array", "items": {"prefixItems": [{"type": "string"}, {"type": "string"}, {}], "type": "array"}, "maxItems": 10}, "limit": {"type": "integer"}}}},
    "required": ["action", "ghost_field"]}},
 {"name": "echo_stub", "description": "把 text 原样回显, 并返回固定标记 STUB-OK-7731",
  "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}, "tags": {"type": "array"}}, "required": ["text", "missing_one"]}},
]
def send(o): sys.stdout.write(json.dumps(o, ensure_ascii=False) + "\n"); sys.stdout.flush()
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try: m = json.loads(line)
    except Exception: continue
    mid, meth = m.get("id"), m.get("method")
    if meth == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": (m.get("params") or {}).get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}}, "serverInfo": {"name": "stub", "version": "1"}}})
    elif meth == "tools/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
    elif meth == "tools/call":
        p = m.get("params") or {}; a = p.get("arguments") or {}
        txt = f"STUB-OK-7731 echo={a.get('text')!r}" if p.get("name") == "echo_stub" else "STUB-OK-7731 query-done"
        send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": txt}]}})
    elif mid is not None:
        send({"jsonrpc": "2.0", "id": mid, "result": {}})
