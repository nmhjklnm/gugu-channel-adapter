# 适配器清单（自动生成，别手改）

生成：`PYTHONPATH=src python3 -m channel_adapter docs > docs/adapters.md`。改规则或 profile 后必须重新生成，否则测试失败。

## 实例（profile）：每个挂在网关渠道前面的适配器

### 4router-gemini
- 是什么：挡在网关与 4Router 之间，只服务 Gemini 的渠道：修工具 schema（4Router 的 Gemini 后端拒数组缺 items、required 含未定义字段）。
- 谁在用：网关渠道 4router-gemini（模型 gemini-3.8-flash），Gemini 的兜底档。
- 上游：https://4router.net
- 运行时：python
- 启用的规则：schema-array-items、schema-required-undefined
- 何时整个撤掉：4Router 的 Gemini 后端放行这两类 schema，并用 acceptance/ 在不经本适配器时验收全绿。

### hapi-errors
- 是什么：普通 HAPI 渠道的专用适配，只修 HAPI 自己读不懂的格式：在响应提交前恢复包装错误、保留厂商请求号；Responses 请求里只有 summary 的 reasoning 项补上 content。其余请求字节、模型和工具形状不变；独立于 Gemini schema 规则。
- 谁在用：共享测试 HAPI 渠道 gugu-hapi-platform（4）和 hapi-free-luna-responses（80）；Docker 内部端口 8318，无宿主发布端口。
- 上游：https://hapi.hc11.org
- 运行时：node
- 启用的规则：hapi-error-envelope、responses-reasoning-content
- 何时整个撤掉：两条规则都满足各自的可删条件（见 docs/adapters.md）后，先恢复渠道直连，再停止实例。

### hapi-gemini
- 是什么：挡在网关与 HAPI 之间，只服务 Gemini 的渠道：修工具 schema、给「末个非 system 轮次只有工具结果」的请求补文本、把 HAPI 的「200 加错误」改回 502，网关才能落到兜底渠道。
- 谁在用：网关渠道 gugu-hapi-gemini（模型 gemini-3.8-flash，模型名映射为 alice/gemini-3.8-flash），Gemini 的首选档。
- 上游：https://hapi.hc11.org
- 运行时：python
- 启用的规则：schema-array-items、schema-required-undefined、pad-tool-result、error-200-to-502
- 何时整个撤掉：HAPI 修好「末个非 system 轮次仅 tool_result」「required 含未定义字段」「错误回 200」三个问题，并用 acceptance/ 在不经本适配器时验收全绿。

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
- 是什么：messages 里「最后一条非 system 消息」只含 tool_result（Anthropic 形态的 user 消息）或是 role=tool（OpenAI 形态）时，补一个最小文本 `.`（前者补成该消息的文本块，后者在末尾追加一条 user）。
- 何时用：经 hapi 访问 Gemini 的任何带工具调用的第 2 轮及以后：Claude Code、Codex（responses 转 chat 后）、任何 OpenAI 兼容 Agent。Claude Code 的第 2 轮形如 [user, system, assistant(tool_use), user(tool_result), system]——末尾还跟着 role=system 消息，所以必须跳过 system 去看。
- 为什么：hapi 的 Gemini 转换里 role=system 消息不算数：去掉 system 后若最后一个轮次只有工具结果，就 400001 `Invalid request parameters`；补任意文本块（含空串）即通。是「末条只有工具结果」触发，不是 system 角色本身（去掉所有 system 仍失败；保留 system 但补文本即通）。
- 证据：真 Claude Code 第 2 轮请求对 hapi 直连变体二分（2026-10-14 15:10–15:13 UTC+8）：原样/去中间 system/去末条 system/两条都去掉 → 全 400；末条 system 并入、两条都并入、末尾补 user、tool_result 补 `.`（system 全保留）→ 全通；OpenAI 形态 [user, assistant tool_calls, tool, system] 400，末尾补 user `.` 通。早先最小复现 reqid：ef8c52ba-d9e0-49dc-921e-8f900389b925、b431a5b5-d4b5-4d72-8285-d555bd5beb64；真实 Claude Code：96be2b6b-d557-49b1-bad1-6ce5429bdd7f、831ddc1d-201d-4173-a284-92134352cd81、d424ccfe-c6c4-4448-a3a6-eee923114eaf。详见 docs/vendor-reports/hapi-2026-10-14.md。
- 何时可删：HAPI 修复「末个非 system 轮次只有工具结果」的转换；用 acceptance/gateway_tool_result.py 与 acceptance/run_cc.py 在不开此规则时仍全绿。
- 被哪些实例启用：hapi-gemini

### error-200-to-502（响应规则 · 2026-10-14 加入）
- 是什么：上游对非流式请求回「HTTP 200 + 错误 JSON」（`{"type":"error"…}` 或只有 `error` 字段）时，把状态码改成 502，响应体原样。
- 何时用：上游是 hapi（它把自己的 400/500 包成 200）。流式（text/event-stream）响应不处理。
- 为什么：网关与客户端按 200 当成功：不换渠道、也不触发重试，客户端拿到一个「不是 Message 的 JSON」后报错。改成 5xx，网关才能落到兜底渠道。
- 证据：hapi 直连最小复现的所有失败用例状态码均为 200（reqid 同 pad-tool-result）；故障注入验证：预发 hapi 渠道返回 200+错误时，4router 兜底渠道接住 5/5 请求。
- 何时可删：hapi 对错误返回真实 4xx/5xx。注意生产网关（fork gugu.9）已有「包装 400 还原」逻辑，删除前确认两者行为。
- 被哪些实例启用：hapi-gemini

### hapi-error-envelope（响应规则 · 2026-10-20 加入）
- 是什么：在响应尚未提交时恢复 HAPI JSON/SSE 包装的错误状态与 request_id/trace_id；正常请求及响应字节透传，不自行重试。
- 何时用：普通 HAPI 渠道的 Messages、Responses、Chat；JSON 最多检查 1 MiB，SSE 起始最多 64 KiB / 30 秒。输出、工具调用或边界到达后不再改状态或重放。
- 为什么：HAPI 把上游 400/过载包成 HTTP 200 流事件，官方 New API 无法按 HTTP 状态作正确恢复/换路。原有 error-200-to-502 只覆盖非流式 JSON，且不能区分参数错误。
- 证据：2026-10-20 直连 HAPI Luna Messages 为 HTTP 200 + 上游 400 InvalidParameter；经规则为 400，保留 request_id 1de187dc-1c79-4de5-a174-1e3e50af5a5b、trace_id a4a2e83f78a5dfe432a6f967fdc2cddc。隔离官方 New API 三协议换路、真实工具往返及 Windows Codex 两轮通过。详见 docs/vendor-reports/hapi-errors-2026-10-20.md。
- 何时可删：HAPI 在提交响应前对参数拒绝、限流、过载直接返回正确 4xx/5xx，且绕过本实例重跑三协议流式、工具往返和真客户端均通过。已提交响应后的流内错误本身是正常协议行为，不作为永远保留此规则的理由。
- 被哪些实例启用：hapi-errors

### responses-reasoning-content（请求规则 · 2026-10-22 加入）
- 是什么：/v1/responses 请求的 input 里，只有 summary、没有 content 和 encrypted_content 的 reasoning 项，把 summary 文本补成 content:[{type:reasoning_text}]。没有这种项的请求原样转发，字节不变。
- 何时用：同一个模型的渠道池里，别家上游只回 summary 形式的推理（如 kozeai 上的 deepseek-v4.1-flash）；网关失败转移后，下一轮回到 HAPI，Codex 会原样回传这些推理项。
- 为什么：HAPI 只从 content / encrypted_content 读推理，不读 summary。DeepSeek 思考模式要求带工具调用的那一轮把推理正文回传，缺了就是上游 400 InvalidParameter，而且 400 不重试，用户这一轮直接断掉。
- 证据：2026-10-22 共享测试网关：钉渠道 4→60→4 可稳定复现第 3 步 400 InvalidParameter。同一份第 3 步输入交错各发 8 次：补 content 的 200×7（另 1 次 HAPI 卡满 180 s），不补的 400×7（另 1 次 502）。kozeai 回的 summary 就是推理原文，不是二次摘要。补写后的 Codex 形状任务（四次 shell 调用后作答）走完全程，答案正确。
- 何时可删：HAPI 能读 summary 形式的 reasoning（绕过本规则，用 summary-only 推理项重放第 3 步得到 200），或者同一模型的渠道池里不再有只回 summary 的上游。
- 被哪些实例启用：hapi-errors
