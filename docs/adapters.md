# 适配器清单（自动生成，别手改）

生成：`PYTHONPATH=src python3 -m channel_adapter docs > docs/adapters.md`。改规则或 profile 后必须重新生成，否则测试失败。

## 实例（profile）：每个挂在网关渠道前面的适配器

### 4router-gemini
- 是什么：挡在网关与 4Router 之间，只服务 Gemini 的渠道：修工具 schema（4Router 的 Gemini 后端拒数组缺 items、required 含未定义字段）。
- 谁在用：网关渠道 4router-gemini（模型 gemini-3.8-flash），Gemini 的兜底档。
- 上游：https://4router.net
- 启用的规则：schema-array-items、schema-required-undefined
- 何时整个撤掉：4Router 的 Gemini 后端放行这两类 schema，并用 acceptance/ 在不经本适配器时验收全绿。

### hapi-gemini
- 是什么：挡在网关与 HAPI 之间，只服务 Gemini 的渠道：修工具 schema、给「仅 tool_result」轮次补文本、把 HAPI 的「200 加错误」改回 502，网关才能落到兜底渠道。
- 谁在用：网关渠道 gugu-hapi-gemini（模型 gemini-3.8-flash，模型名映射为 alice/gemini-3.8-flash），Gemini 的首选档。
- 上游：https://hapi.hc11.org
- 启用的规则：schema-array-items、schema-required-undefined、pad-tool-result、error-200-to-502
- 何时整个撤掉：HAPI 修好「末条仅 tool_result」「required 含未定义字段」「错误回 200」三个问题，并用 acceptance/ 在不经本适配器时验收全绿。

## 规则目录：每条规则是什么、何时用、为什么、何时可删

### schema-array-items（请求规则 · 2026-10-14 加入）
- 是什么：工具参数 schema 里 type 为 array（或带 prefixItems）却没有 items 的节点，补 `items: {}`。
- 何时用：请求带 tools，且上游会把 schema 交给 Gemini 做 function_declarations 校验；schema 里有缺 items 的数组时。Claude Code 自带的 ArtifactData 工具（query.where 是「数组的数组」，只有 prefixItems）就是这种。
- 为什么：Gemini 后端校验直接 400：`tools[0].function_declarations[N]…properties[where].items: missing field`。Anthropic 的 API 不要求 items，所以 Claude Code 照常发。
- 证据：4router 渠道 2026-10-14 13:28 owner 的真实会话（请求号 202610140528165969417023ew3UQZS）；复现：任意 /v1/messages 带一个 type=array 缺 items 的工具，经 4router 即 400。hapi 直连对此写法放行。
- 何时可删：4router（及其后的 Gemini 后端）对缺 items 的数组放行，且用 acceptance/ 的真 Claude Code 验收在不开此规则时仍全绿。
- 被哪些实例启用：4router-gemini、hapi-gemini

### schema-required-undefined（请求规则 · 2026-10-14 加入）
- 是什么：工具参数 schema 里 `required` 列了 `properties` 中没有的字段时，把这些字段从 required 里去掉。
- 何时用：请求带 tools，上游把 schema 交给 Gemini 校验；MCP 工具里这种写法不少见（手写 schema、字段改名后 required 没跟着改）。
- 为什么：Gemini 后端 400：`schema at top-level requires unspecified property 'xxx'`（INVALID_ARGUMENT）。
- 证据：hapi 直连最小复现（model alice/gemini-3.8-flash，tools.required=['zzz']）：reqid f54e20aa-f30b-4505-9fa2-52dfcfb186cf（14:32:59）、0108e187-a25c-420e-9540-fd682944704d（14:33:53，UTC+8，2026-10-14）；4router 同样 400。
- 何时可删：hapi 与 4router 在转换时自行清理或放行；用 acceptance/ 验收在不开此规则时仍全绿。
- 被哪些实例启用：4router-gemini、hapi-gemini

### pad-tool-result（请求规则 · 2026-10-14 加入）
- 是什么：最后一条消息只含 tool_result（Anthropic 形态的 user 消息）或是 role=tool（OpenAI 形态）时，补一个最小文本 `.`。
- 何时用：经 hapi 访问 Gemini 的任何带工具调用的第 2 轮及以后：Claude Code、Codex（responses 转 chat 后）、任何 OpenAI 兼容 Agent。
- 为什么：hapi 的 Gemini 转换遇到「末条只有工具结果」就 400001 `Invalid request parameters`，补任意文本块（含空串）即通；同一请求多带一个文本块就能正常回答。
- 证据：最小复现（messages=[user 文本, assistant tool_use, user 仅 tool_result]）：reqid ef8c52ba-d9e0-49dc-921e-8f900389b925（14:32:57）、b431a5b5-d4b5-4d72-8285-d555bd5beb64（14:33:49）；真实 Claude Code：96be2b6b-d557-49b1-bad1-6ce5429bdd7f（13:49:04）、831ddc1d-201d-4173-a284-92134352cd81（13:49:45）、d424ccfe-c6c4-4448-a3a6-eee923114eaf（13:50:24）；均 2026-10-14 UTC+8。对照：补 `.` 后同一请求 OK。详见 docs/vendor-reports/hapi-2026-10-14.md。
- 何时可删：HAPI 修复「末条仅 tool_result」的转换；用 acceptance/gateway_tool_result.py 在不开此规则时三种形态均通过。
- 被哪些实例启用：hapi-gemini

### merge-system-messages（请求规则 · 2026-10-14 加入）
- 是什么：messages 里 role=system 的消息（Claude Code 的 mid-conversation-system beta）并入相邻 user 消息的文本块，再合并相邻 user。
- 何时用：上游不接受 messages 里的 system 角色时。目前只在 hapi 的 Claude 渠道观察到；Gemini 渠道经测不是必要（默认不开）。
- 为什么：hapi 对 claude-sonnet-5 回 `role 'system' is not supported on this model`（400）。
- 证据：预发 hapi 渠道 14 天 462 次（445 次 500 包装 + 17 次 400），集中在 2026-10-13 下午；Gemini 最小复现里带 system 角色的单轮请求是通的（hapi_repro 用例 D）。
- 何时可删：HAPI 接受 system 角色消息，或我们不再经 hapi 提供 Claude。目前没有 profile 启用它，若一直没人用就删除。
- 被哪些实例启用：（无）

### error-200-to-502（响应规则 · 2026-10-14 加入）
- 是什么：上游对非流式请求回「HTTP 200 + 错误 JSON」（`{"type":"error"…}` 或只有 `error` 字段）时，把状态码改成 502，响应体原样。
- 何时用：上游是 hapi（它把自己的 400/500 包成 200）。流式（text/event-stream）响应不处理。
- 为什么：网关与客户端按 200 当成功：不换渠道、也不触发重试，客户端拿到一个「不是 Message 的 JSON」后报错。改成 5xx，网关才能落到兜底渠道。
- 证据：hapi 直连最小复现的所有失败用例状态码均为 200（reqid 同 pad-tool-result）；故障注入验证：预发 hapi 渠道返回 200+错误时，4router 兜底渠道接住 5/5 请求。
- 何时可删：hapi 对错误返回真实 4xx/5xx。注意生产网关（fork gugu.9）已有「包装 400 还原」逻辑，删除前确认两者行为。
- 被哪些实例启用：hapi-gemini
