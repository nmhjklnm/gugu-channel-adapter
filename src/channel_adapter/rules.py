"""适配规则注册表。

每条规则 = 一段代码 + 一份必填的说明（是什么 / 何时用 / 为什么 / 证据 / 何时可删）。
tests/test_docs.py 会检查：说明缺项、或 docs/adapters.md 与注册表不一致，都会失败。
增删规则 = 改这里 + 改 profiles/*.json + 重新生成文档（python -m channel_adapter docs）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Optional

DOC_FIELDS = ("what", "when", "why", "evidence", "added", "remove_when")


@dataclass(frozen=True)
class Rule:
    id: str
    kind: str            # "request"（改发给上游的请求体）| "response"（改上游的响应）
    what: str            # 这条规则做什么
    when: str            # 什么情况下用（触发场景）
    why: str             # 为什么要有它（上游的毛病/症状）
    evidence: str        # 证据：reqid、复现方式、日志
    added: str           # 加入日期
    remove_when: str     # 什么条件下可以删
    apply: Optional[Callable] = None
    runtime: str = "python"


REGISTRY: dict[str, Rule] = {}


def rule(**meta):
    def deco(fn):
        r = Rule(apply=fn, **meta)
        assert r.id not in REGISTRY, r.id
        REGISTRY[r.id] = r
        return fn
    return deco


# ---------------------------------------------------------------- 请求规则

def _walk_schema(node, visit):
    """对 JSON Schema 的每个子节点（dict）调用 visit(node)。"""
    if isinstance(node, list):
        for x in node:
            _walk_schema(x, visit)
        return
    if not isinstance(node, dict):
        return
    visit(node)
    for k in ("items", "additionalProperties", "not", "if", "then", "else", "contains", "propertyNames"):
        if isinstance(node.get(k), (dict, list)):
            _walk_schema(node[k], visit)
    for k in ("prefixItems", "anyOf", "oneOf", "allOf"):
        if isinstance(node.get(k), list):
            for x in node[k]:
                _walk_schema(x, visit)
    for k in ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas"):
        if isinstance(node.get(k), dict):
            for v in node[k].values():
                _walk_schema(v, visit)


def _tool_schemas(body):
    """取出请求里所有工具的参数 schema（Anthropic input_schema / OpenAI function.parameters / Responses parameters）。"""
    for tool in body.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        for key in ("input_schema", "parameters"):
            if isinstance(tool.get(key), dict):
                yield tool[key]
        fn = tool.get("function")
        if isinstance(fn, dict) and isinstance(fn.get("parameters"), dict):
            yield fn["parameters"]


@rule(
    id="schema-array-items", kind="request",
    what="工具参数 schema 里 type 为 array（或带 prefixItems）却没有 items 的节点，补 `items: {}`。",
    when="请求带 tools，且上游会把 schema 交给 Gemini 做 function_declarations 校验；schema 里有缺 items 的数组时。"
         "Claude Code 自带的 ArtifactData 工具（query.where 是「数组的数组」，只有 prefixItems）就是这种。",
    why="Gemini 后端校验直接 400：`tools[0].function_declarations[N]…properties[where].items: missing field`。"
        "Anthropic 的 API 不要求 items，所以 Claude Code 照常发。",
    evidence="4router 渠道 2026-10-14 13:28 owner 的真实会话（请求号 202610140528165969417023ew3UQZS）；"
             "复现：任意 /v1/messages 带一个 type=array 缺 items 的工具，经 4router 即 400。hapi 直连对此写法放行。",
    added="2026-10-14",
    remove_when="4router（及其后的 Gemini 后端）对缺 items 的数组放行，且用 acceptance/ 的真 Claude Code 验收在不开此规则时仍全绿。",
)
def schema_array_items(body, ctx):
    n = [0]

    def visit(node):
        t = node.get("type")
        is_array = t == "array" or (isinstance(t, list) and "array" in t)
        if (is_array or "prefixItems" in node) and "items" not in node:
            node["items"] = {}
            n[0] += 1
    for s in _tool_schemas(body):
        _walk_schema(s, visit)
    return n[0]


@rule(
    id="schema-required-undefined", kind="request",
    what="工具参数 schema 里 `required` 列了 `properties` 中没有的字段时，把这些字段从 required 里去掉。",
    when="请求带 tools，上游把 schema 交给 Gemini 校验；MCP 工具里这种写法不少见（手写 schema、字段改名后 required 没跟着改）。",
    why="Gemini 后端 400：`schema at top-level requires unspecified property 'xxx'`（INVALID_ARGUMENT）。",
    evidence="hapi 直连最小复现（model alice/gemini-3.8-flash，tools.required=['zzz']）：reqid f54e20aa-f30b-4505-9fa2-52dfcfb186cf（14:32:59）、"
             "0108e187-a25c-420e-9540-fd682944704d（14:33:53，UTC+8，2026-10-14）；4router 同样 400。",
    added="2026-10-14",
    remove_when="hapi 与 4router 在转换时自行清理或放行；用 acceptance/ 验收在不开此规则时仍全绿。",
)
def schema_required_undefined(body, ctx):
    n = [0]

    def visit(node):
        req = node.get("required")
        if isinstance(req, list):
            props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
            keep = [r for r in req if r in props]
            if len(keep) != len(req):
                n[0] += len(req) - len(keep)
                if keep:
                    node["required"] = keep
                else:
                    node.pop("required")
    for s in _tool_schemas(body):
        _walk_schema(s, visit)
    return n[0]


@rule(
    id="pad-tool-result", kind="request",
    what="messages 里「最后一条非 system 消息」只含 tool_result（Anthropic 形态的 user 消息）或是 role=tool（OpenAI 形态）时，补一个最小文本 `.`（前者补成该消息的文本块，后者在末尾追加一条 user）。",
    when="经 hapi 访问 Gemini 的任何带工具调用的第 2 轮及以后：Claude Code、Codex（responses 转 chat 后）、任何 OpenAI 兼容 Agent。"
         "Claude Code 的第 2 轮形如 [user, system, assistant(tool_use), user(tool_result), system]——末尾还跟着 role=system 消息，所以必须跳过 system 去看。",
    why="hapi 的 Gemini 转换里 role=system 消息不算数：去掉 system 后若最后一个轮次只有工具结果，就 400001 `Invalid request parameters`；"
        "补任意文本块（含空串）即通。是「末条只有工具结果」触发，不是 system 角色本身（去掉所有 system 仍失败；保留 system 但补文本即通）。",
    evidence="真 Claude Code 第 2 轮请求对 hapi 直连变体二分（2026-10-14 15:10–15:13 UTC+8）：原样/去中间 system/去末条 system/两条都去掉 → 全 400；"
             "末条 system 并入、两条都并入、末尾补 user、tool_result 补 `.`（system 全保留）→ 全通；OpenAI 形态 [user, assistant tool_calls, tool, system] 400，"
             "末尾补 user `.` 通。早先最小复现 reqid：ef8c52ba-d9e0-49dc-921e-8f900389b925、b431a5b5-d4b5-4d72-8285-d555bd5beb64；"
             "真实 Claude Code：96be2b6b-d557-49b1-bad1-6ce5429bdd7f、831ddc1d-201d-4173-a284-92134352cd81、d424ccfe-c6c4-4448-a3a6-eee923114eaf。"
             "详见 docs/vendor-reports/hapi-2026-10-14.md。",
    added="2026-10-14",
    remove_when="HAPI 修复「末个非 system 轮次只有工具结果」的转换；用 acceptance/gateway_tool_result.py 与 acceptance/run_cc.py 在不开此规则时仍全绿。",
)
def pad_tool_result(body, ctx):
    msgs = body.get("messages")
    if not isinstance(msgs, list):
        return 0
    idx = next((i for i in range(len(msgs) - 1, -1, -1) if isinstance(msgs[i], dict) and msgs[i].get("role") != "system"), None)
    if idx is None:
        return 0
    last = msgs[idx]
    if last.get("role") == "user" and isinstance(last.get("content"), list):
        blocks = [b for b in last["content"] if isinstance(b, dict)]
        if blocks and all(b.get("type") == "tool_result" for b in blocks):
            last["content"].append({"type": "text", "text": "."})
            return 1
    if last.get("role") == "tool":
        msgs.append({"role": "user", "content": "."})
        return 1
    return 0


# ---------------------------------------------------------------- 响应规则

@rule(
    id="error-200-to-502", kind="response",
    what="上游对非流式请求回「HTTP 200 + 错误 JSON」（`{\"type\":\"error\"…}` 或只有 `error` 字段）时，把状态码改成 502，响应体原样。",
    when="上游是 hapi（它把自己的 400/500 包成 200）。流式（text/event-stream）响应不处理。",
    why="网关与客户端按 200 当成功：不换渠道、也不触发重试，客户端拿到一个「不是 Message 的 JSON」后报错。改成 5xx，网关才能落到兜底渠道。",
    evidence="hapi 直连最小复现的所有失败用例状态码均为 200（reqid 同 pad-tool-result）；故障注入验证：预发 hapi 渠道返回 200+错误时，"
             "4router 兜底渠道接住 5/5 请求。",
    added="2026-10-14",
    remove_when="hapi 对错误返回真实 4xx/5xx。注意生产网关（fork gugu.9）已有「包装 400 还原」逻辑，删除前确认两者行为。",
)
def error_200_to_502(status, content_type, body_bytes):
    """返回应改成的状态码；不需要改返回 None。（响应规则的签名与请求规则不同）"""
    if status != 200 or not content_type.lower().startswith("application/json"):
        return None
    try:
        d = json.loads(body_bytes)
    except Exception:
        return None
    if isinstance(d, dict) and (d.get("type") == "error" or ("error" in d and not any(k in d for k in ("choices", "content", "output", "id")))):
        return 502
    return None


def request_rules(ids):
    return [REGISTRY[i] for i in ids if REGISTRY[i].kind == "request"]


def response_rules(ids):
    return [REGISTRY[i] for i in ids if REGISTRY[i].kind == "response"]


# The stream boundary belongs to the Node HTTP runtime, not to a buffered Python response callback.
REGISTRY["hapi-error-envelope"] = Rule(
    id="hapi-error-envelope", kind="response", runtime="node",
    what="在响应尚未提交时恢复 HAPI JSON/SSE 包装的错误状态与 request_id/trace_id；正常请求及响应字节透传，不自行重试。",
    when="普通 HAPI 渠道的 Messages、Responses、Chat；JSON 最多检查 1 MiB，SSE 起始最多 64 KiB / 30 秒。输出、工具调用或边界到达后不再改状态或重放。",
    why="HAPI 把上游 400/过载包成 HTTP 200 流事件，官方 New API 无法按 HTTP 状态作正确恢复/换路。原有 error-200-to-502 只覆盖非流式 JSON，且不能区分参数错误。",
    evidence="2026-10-20 直连 HAPI Luna Messages 为 HTTP 200 + 上游 400 InvalidParameter；经规则为 400，保留 request_id 1de187dc-1c79-4de5-a174-1e3e50af5a5b、trace_id a4a2e83f78a5dfe432a6f967fdc2cddc。隔离官方 New API 三协议换路、真实工具往返及 Windows Codex 两轮通过。详见 docs/vendor-reports/hapi-errors-2026-10-20.md。",
    added="2026-10-20",
    remove_when="HAPI 在提交响应前对参数拒绝、限流、过载直接返回正确 4xx/5xx，且绕过本实例重跑三协议流式、工具往返和真客户端均通过。已提交响应后的流内错误本身是正常协议行为，不作为永远保留此规则的理由。",
)
