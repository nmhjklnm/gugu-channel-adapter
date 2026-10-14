# 部署

## 布局（网关机上）

| 位置 | 内容 |
|---|---|
| `/opt/gugu-channel-adapter/{src,profiles,deploy}` | 代码（`deploy/push.sh` 整体替换） |
| `/etc/gugu-channel-adapter/<profile>.env` | 该实例的 `BIND`、`PORT`（安装脚本写） |
| `gugu-channel-adapter@<profile>.service` | systemd 模板实例；日志 `journalctl -u gugu-channel-adapter@hapi-gemini` |

适配器绑在 docker 网桥 IP（预发 `172.19.0.1`、生产 `172.20.0.1`），网关容器经它访问；不监听公网。端口固定：hapi-gemini 18770、4router-gemini 18771，与网关渠道 base_url 对应。

## 部署 / 升级

```
deploy/push.sh ali2 172.19.0.1      # 预发
deploy/push.sh ali1 172.20.0.1      # 生产，须 owner 授权
```

脚本先跑测试，再 tar 过去，逐实例切换：停旧手工 shim（`gugu-gemini-shim`、`gugu-gemini-shim-4router`，单元文件保留）→ 起新实例 → 探测上游可达 → 任一实例失败即自动把旧服务拉回。

之后必做：`acceptance/` 真客户端验收（强制渠道 + 不强制各一遍），日志里应见 `[schema-array-items=… pad-tool-result=…]`。

## 日志怎么看

每个请求一行：`POST /v1/messages -> 200 [规则名=命中次数 …]`，括号里是这次生效的规则；`error-200-to-502:200->502` 表示上游假 200 被改回。无括号 = 原样透传。

## 回滚

```
systemctl disable --now gugu-channel-adapter@hapi-gemini gugu-channel-adapter@4router-gemini
systemctl enable --now gugu-gemini-shim gugu-gemini-shim-4router   # 旧服务（迁移完成并稳定后可清理）
```

## 下线某个实例

1. 网关渠道改回直连上游（base_url 改成上游，去掉 model_mapping 之外的适配依赖）；
2. `systemctl disable --now gugu-channel-adapter@<profile>`，删 `/etc/gugu-channel-adapter/<profile>.env`；
3. 删 `profiles/<profile>.json`，重新生成 `docs/adapters.md`；规则若无实例使用，一并删。
