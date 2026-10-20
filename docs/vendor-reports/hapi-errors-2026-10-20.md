# HAPI 早期错误包装（2026-10-20）

跟踪：https://github.com/nmhjklnm/gugu-channel-adapter/issues/1 （从 gugu-newapi#37 转入）。

## 复现

向 HAPI `/v1/messages` 发一条模型 `sarah/gpt-6-luna`、`stream:true`、`max_tokens:256` 的最小请求。HAPI 返回 HTTP 200、`text/event-stream`，正文是单个 `error` 事件；type 为 `hapi_upstream_error`，message 包装上游 400 InvalidParameter，内容要求改用 max_completion_tokens。

实际 adapter 验证的上游 request_id：`1de187dc-1c79-4de5-a174-1e3e50af5a5b`；trace_id：`a4a2e83f78a5dfe432a6f967fdc2cddc`。这些是厂商实际返回的标识，不是 New API 内部请求号。没有保存或提交密钥。

## 期望与适配边界

在发送响应前已知的参数错误应返回 400；过载、限流应返回可识别的相应错误。已发出响应头后的流内错误是协议允许的，不能一概视为供应商错误。

`hapi-errors` 在有限起始窗口中恢复包装的状态和请求号，不改工具/模型/请求，不自行重试。真实参数错误保留 400，供应商凭据错误转为 502；错误后是否换渠道由原版 New API 判断。已输出后或触及窗口上限只透传，不重放。

## 验证与删除条件

17 项 Node socket 回归覆盖分片 SSE、包装 JSON、400/429/503、输出/工具后不重放、断开取消、请求号恢复等。最终实现的隔离官方 New API 三协议故障注入换路通过；真实 HAPI 三协议工具往返、Sonnet 两轮 Messages 与 Windows Codex 连续两轮通过。具体设备读数保存在设备笔记，不把密钥、渠道配置备份或机器连接资料放入仓库。

HAPI 对早期失败恢复正确 HTTP 状态后，绕过该实例，重跑三协议流式、工具往返与真客户端均通过，才删除 profile/规则。此规则与 Gemini schema、tool_result 兼容规则彼此独立。
