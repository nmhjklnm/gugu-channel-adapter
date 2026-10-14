# 验收（真客户端，链路通才算通）

「hi 能回」不算通。标准：真 Claude Code（`claude -p`）经网关，一轮里完成 **MCP 工具往返** 和 **Bash 工具往返**，三项全 `is_error=False`。

```
# 1. 在网关机上建一个 1 小时的临时令牌（管理员钥匙读 .env，不打印）
python3 acceptance/make_token.py /data/gugu-dev-gateway/newapi/.control.env http://127.0.0.1:57950 vip   # 预发
python3 acceptance/make_token.py /data/gugu-prod/.env http://127.0.0.1:3000 gugu                          # 生产
# 2. 本机（经 SSH 隧道到网关）跑；强制某渠道：令牌后缀 -<渠道id>
python3 acceptance/run_cc.py http://127.0.0.1:<隧道端口> sk-xxx-77 staging-forced-77
python3 acceptance/run_cc.py http://127.0.0.1:<隧道端口> sk-xxx    staging-unforced
# 3. 用完删令牌
python3 acceptance/delete_token.py <同上 env> <同上 url> <令牌 id>
```

- `stub_mcp.py`：两个工具，schema 故意带 Gemini 后端拒收的写法（数组缺 items、required 含未定义字段）。
- 判是否经适配器：看网关 logs 的 channel_id 落在哪个渠道、适配器 journald 里有没有 `[schema-array-items=… pad-tool-result=…]`。
- 删某条规则前：停用它（或用 `UPSTREAM` 直连上游）重跑本验收，仍全绿才可删。
