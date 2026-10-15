# 配置级适配（New API 渠道 param_override）

适配器（`src/`）只做 New API **配置表达不了**的事（改响应、跨多条消息判断、需要自己的转发进程）。
能用渠道 `param_override` 表达的兼容，直接配在网关渠道上：零额外转发、少一个故障点。
但配置藏在网关库里看不见，所以和适配器一样登记在这里：是什么 / 何时用 / 为什么 / 证据 / 何时可删。

选型：能配置 → 配置；配置做不到 → 适配器（`docs/adapters.md`）。

## kozeai-effort

- 渠道：预发 60 kozeai、61 kozeai-free、生产 22 kozeai（均 2026-10-15 已上，生产为 owner 当日授权）。
- 是什么：请求里 `output_config.effort` 为 `xhigh`/`max` → 顶层 `reasoning_effort="max"`；为 `medium` → `reasoning_effort="high"`；之后删掉 `output_config.effort`。`low`/`high` 原样。
- 配置（渠道 param_override，4 条 operations；条件均为 `output_config.effort` 全等于该值）：
  `set reasoning_effort=max`（xhigh）、`set reasoning_effort=max`（max）、`set reasoning_effort=high`（medium）、`delete output_config.effort`（xhigh/max/medium 任一，logic OR）。
- 何时用：客户端发 medium/xhigh/max（Claude Code 的 `/effort xhigh` 等）且请求落到 kozeai——智谱套餐配额耗尽（1310）或优先级最后兜底时。
- 为什么：kozeai 把 `output_config.effort` 翻成 reasoning_effort 后只认 low/high：medium/xhigh/max 全部 400 `'reasoning_effort' must be one of: 'low', 'high', 'max'`（连 max 也拒，疑似内部把 max 翻成 xhigh）；顶层 `reasoning_effort` 为 max/high 能通过。向上取整是因为用户要的是「至少这么强」。
- 证据：预发请求号 202610150231464488893268268d9d6lemwkcZs（2026-10-15 10:31，渠道 60，400）；直连 kozeai 实测 low/high 通、medium/xhigh/max 400、顶层 reasoning_effort=max/high 通；改后经网关强制渠道 60：low/medium/high/xhigh/max 全 200，61 的 flash 同；生产渠道 22 强制渠道同样 5 档全 200；真 Claude Code `--effort xhigh`（含 MCP、Bash 往返）不指定渠道与强制渠道各 3/3。
- 范围：对渠道上所有模型生效（没有按模型限定）。直连实测只有 glm-5.3 会拒；kimi-k3、deepseek-v4-pro、deepseek-v4.1-flash、qwen3.8-max、qwen3.8-flash 原本全接受，改写后经网关同样全通过（预发 6 模型×4 档，2026-10-15）。
- 何时可删：kozeai 接受 medium/xhigh/max（直连复测）；或不再经 kozeai 提供 GLM。
- 验证：`EFFORT=xhigh python3 acceptance/run_cc.py <网关> <令牌> <标签> glm-5.3`。

## hapi-thinking-display

- 渠道：预发 4 gugu-hapi-platform（2026-10-14 已上）；生产 8（2026-10-16 核实已在位：param_override 与预发同一段，强制渠道 8 发 highlights 流式/非流式均 200；近 7 天生产渠道 8 仅 10-11 一次 display 报错，其后为 0）。
- 是什么：`thinking.display` 为 `highlights` 时改成 `omitted`（1 条 set，条件 `thinking.display` 全等于 `highlights`）。
- 何时用：Claude Code 对 claude-opus-5 / claude-sonnet-5 发 `highlights` 且请求落到 hapi。
- 为什么：hapi 的上游只认 summarized/omitted，拒 highlights，并把这个 400 包成 HTTP 500，Claude Code 当服务器故障重试 10 次。
- 证据：预发 2026-10-14 复现：display=highlights → 500，omitted/summarized → 200；改后 highlights 流式/非流式 200，其它值不变。2026-10-16 直连 hapi（不经网关）复测 5 次：highlights 仍回 `ValidationException: thinking.display: Input should be 'summarized', 'omitted'`（包在 HTTP 200 的 hapi_upstream_error 里，1～13 秒），omitted/summarized/不带 thinking 均成功——所以还不能删。
- 何时可删：hapi 接受 highlights，或把它当真 400 返回（客户端会自行降级为 omitted）。
