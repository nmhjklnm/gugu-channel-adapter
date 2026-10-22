# GLM 网关（AWS Bedrock）拒收空 system 消息（2026-10-23）

渠道：共享测试网关 15 `gugu-glm-gateway`（上游 `https://api-gateway.glm.ai`，其后是 AWS Bedrock 上的 Claude；生产同一家是渠道 12）。

## 复现

Claude Code 在 `/compact` 之后的每一轮，`messages[1]` 都是一条 `{"role":"system","content":[]}`（会话中 system 消息，beta `mid-conversation-system-2026-04-07`；压缩前同一位置是非空的环境说明）。Bedrock 拒收：

`ValidationException: messages.1: system content must contain at least one block`

GLM 网关在自己的后端之间重试 6～8 次，返回 400（混有限流时是 429/403，或 503「分组 claude-anthropic 下模型 claude-opus-5-5 无可用渠道」），这一轮失败。客户端不会去掉这条消息，所以压缩过的会话再也问不通。

- 产品内（mac1，Claude Code Work 形态，模型 Gugu Claude Opus 5.5，CLI 2.1.293）：聊 3 轮（含 Bash）→ `/compact` → 再问，第一次即失败。网关日志里 Windows 测试号 2026-10-22 18:29–18:52Z 的 186325、186327 同型。
- CLI 版本：2.1.280、2.1.293、2.1.308 用 `claude -p` 跑「一轮 → /compact → 再问」，同型 400。2.1.250、2.1.226 用不了 claude-opus-5-5（`version 2.1.280 or newer is required`）。即所有能用这个模型的版本都会撞。
- 最小请求（同一张会话票，每种 3 次）：system content 为 `[]` 或 `""` → 400×4，另 2 次 35～45 秒后才由非 Bedrock 后端接住；`[{"type":"text","text":""}]` → 400×3（`system text blocks must contain non-whitespace text`）；非空 system 或不带 system → 200×6（2～6 秒）。

## thinking.display（不修）

同一批日志里还有 `ValidationException: thinking.display: Input should be 'summarized', 'omitted'`，请求带 `thinking.display: "updates"`。单独发 updates / highlights / omitted / summarized 共 12 次全部 200；它只出现在上面那条空 system 引起的 GLM 重试链里（某次重试落到不认 updates 的后端，恰好成了最后一条错误），客户端随后自己去掉 display 重发。空 system 去掉之后这条链不再出现，所以没有为它加规则。

## 适配与验证

规则 `drop-empty-system-message`（实例 `glm-gateway`）删掉空的 system 消息（或 system 消息里的空文本块），其余请求字节不变。

- 真实压缩后请求（128 KB，产品抓包）交错各发：直连渠道 15 失败 5/5（400/403 带上面的 ValidationException 2 次，GLM 503「无可用渠道」3 次），经适配 200 5/5；CLI 2.1.308 的压缩后请求：直连 503 2/2，经适配 200 2/2。
- 产品回合：同一条压缩过的会话，经适配 2/2 正常作答，去掉适配 2/2 失败（同型 400）。

GLM 网关在测试网关机上只能经 SOCKS5 出口（`172.19.0.1:18443`）解析和到达，所以实例部署时带 `UPSTREAM_SOCKS5`。

## 何时可删

绕过本实例，把 `messages[1]` 为 `{"role":"system","content":[]}` 的最小请求直发渠道 15 稳定 200；或 Claude Code 压缩后不再发空 system 消息。
