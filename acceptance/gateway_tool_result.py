"""在网关机上用临时令牌打 gemini-3.8-flash 的「仅 tool_result」第 2 轮(三种协议形态, 无 system 消息), 看是否通、落点是谁。
用法(网关机上, root): gateway_tool_result.py <env文件> <管理地址> <令牌分组> <postgres 容器名>
  预发: /data/gugu-dev-gateway/newapi/.control.env http://127.0.0.1:57950 vip gugu-newapi-99ab3e8209de-postgres-1
  生产: /data/gugu-prod/.env http://127.0.0.1:3000 gugu gugu_newapi_postgres
删 pad-tool-result 规则前，用此脚本在不开该规则时三项必须全「通」。"""
import http.client, json, subprocess, sys, time, urllib.parse, urllib.request, urllib.error
ENV = "gateway"
C = (sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
env = {}
for l in open(C[0]):
    l = l.strip()
    if "=" in l and not l.startswith("#"):
        k, v = l.split("=", 1); env[k] = v.strip().strip("'\"")
NB = C[1]; U = urllib.parse.urlparse(NB)
H = {"Authorization": "Bearer " + env["NEWAPI_MANAGEMENT_ACCESS_TOKEN"], "New-Api-User": str(env["NEWAPI_MANAGEMENT_USER_ID"]), "Content-Type": "application/json"}
def call(m, p, b=None):
    r = urllib.request.Request(NB + p, data=(json.dumps(b).encode() if b is not None else None), headers=H, method=m); return json.loads(urllib.request.urlopen(r, timeout=60).read())
name = f"gw-tr-{int(time.time())}"
call("POST", "/api/token/", {"name": name, "expired_time": int(time.time()) + 900, "unlimited_quota": True, "model_limits_enabled": False, "group": C[2]})
tid = next(int(i["id"]) for i in call("GET", "/api/token/?p=0&page_size=100")["data"]["items"] if i["name"] == name)
TK = "sk-" + call("POST", f"/api/token/{tid}/key")["data"]["key"]
dx = lambda *a: subprocess.run(["docker", "exec", C[3], *a], capture_output=True, text=True).stdout.strip()
DBU, DBN = dx("printenv", "POSTGRES_USER"), dx("printenv", "POSTGRES_DB")
M = "gemini-3.8-flash"; Q = "北京今天天气怎么样?用工具查。"
def post(path, body, style="bearer"):
    h = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
    h.update({"Authorization": "Bearer " + TK} if style == "bearer" else {"x-api-key": TK})
    c = http.client.HTTPConnection(U.hostname, U.port, timeout=120); t = time.time()
    c.request("POST", path, body=json.dumps(body).encode(), headers=h); r = c.getresponse(); raw = r.read().decode("utf-8", "replace")
    return r.status, time.time() - t, raw
def ok(raw):
    try:
        d = json.loads(raw)
        if d.get("type") == "message": return "".join(b.get("text", "") for b in d["content"] if b.get("type") == "text")[:40] or None
        if d.get("choices"): return (d["choices"][0]["message"].get("content") or "")[:40] or None
        if d.get("output"): return "".join(c.get("text", "") for o in d["output"] for c in (o.get("content") or []) if isinstance(c, dict))[:40] or None
    except Exception: pass
    return None
TA = [{"name": "get_weather", "description": "查城市天气", "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}]
TO = [{"type": "function", "function": {"name": "get_weather", "description": "查城市天气", "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]
TR = [{"type": "function", "name": "get_weather", "description": "查城市天气", "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}]
tests = [
 ("messages 仅 tool_result(无 system)", "/v1/messages", "xapi", {"model": M, "max_tokens": 512, "tools": TA, "messages": [{"role": "user", "content": Q}, {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_01X", "name": "get_weather", "input": {"city": "北京"}}]}, {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_01X", "content": "晴, 18 度"}]}]}),
 ("chat 末条 role=tool", "/v1/chat/completions", "bearer", {"model": M, "max_tokens": 512, "tools": TO, "messages": [{"role": "user", "content": Q}, {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": "{\"city\":\"北京\"}"}}]}, {"role": "tool", "tool_call_id": "call_1", "content": "晴, 18 度"}]}),
 ("responses function_call_output", "/v1/responses", "bearer", {"model": M, "max_output_tokens": 512, "tools": TR, "input": [{"role": "user", "content": Q}, {"type": "function_call", "call_id": "call_1", "name": "get_weather", "arguments": "{\"city\":\"北京\"}"}, {"type": "function_call_output", "call_id": "call_1", "output": "晴, 18 度"}]}),
]
print(f"[{ENV}]")
for label, path, style, body in tests:
    try:
        st, dt, raw = post(path, body, style); txt = ok(raw)
        print(f"  [{'通' if txt else '拒'}] {label:30s} HTTP {st} {dt:4.1f}s  {txt if txt else raw[:150]!r}", flush=True)
    except Exception as e:
        print(f"  [EXC] {label} {repr(e)[:100]}")
    time.sleep(1.2)
land = dx("psql", "-U", DBU, "-d", DBN, "-At", "-F", " | ", "-c", f"select l.channel_id, c.name, l.type, count(*) from logs l left join channels c on c.id=l.channel_id where l.token_id={tid} group by 1,2,3 order by 1,3")
print("  落点(渠道|名称|type|次数):", land.replace("\n", " ; "))
call("DELETE", f"/api/token/{tid}")
