# 部署

## 布局（网关机上）

| 位置 | 内容 |
|---|---|
| `/opt/gugu-channel-adapter/{src,profiles,deploy}` | 代码（`deploy/push.sh` 整体替换） |
| `/etc/gugu-channel-adapter/<profile>.env` | 该实例的 `BIND`、`PORT`（安装脚本写） |
| `gugu-channel-adapter@<profile>.service` | systemd 模板实例；日志 `journalctl -u gugu-channel-adapter@hapi-gemini` |

适配器绑在 docker 网桥 IP（预发 `172.19.0.1`、生产 `172.20.0.1`），网关容器经它访问；不监听公网。端口固定：hapi-gemini 18770、4router-gemini 18771、glm-gateway 18772，与网关渠道 base_url 对应。

上游只能经某个 SOCKS5 出口到达时（glm-gateway：GLM 网关在网关机上解析不到，原先由渠道自己的 proxy 走 `172.19.0.1:18443`），实例环境带 `UPSTREAM_SOCKS5=<host>:<port>`，域名交给代理解析；`install.sh glm-gateway=172.19.0.1:18772@172.19.0.1:18443` 会写进该实例的 env 文件。渠道 base_url 指向适配器后，渠道自己的 proxy 要清掉（适配器在网关机本地，出口那头连不到它）。

## HAPI 错误实例

`hapi-errors` 与既有 Gemini systemd 实例独立，使用本仓的 `deploy/hapi-errors/compose.yaml`，只加入现有网关 Docker 网络、不发布宿主端口。源码、镜像定义、配置和回滚说明均归本仓，详见 [hapi-errors.md](hapi-errors.md)。`push.sh` 仍只更新两个 Gemini 实例，不会偷偷启用或替换 HAPI 错误实例。

## 现在跑在哪

- 预发 ali2（`172.19.0.1`）：2026-10-14 起。
- 生产 ali1（`172.20.0.1`）：2026-10-15 起（随咕咕 v0.2.54，owner 授权「预发的渠道配置原样同步给生产端」）。`push.sh ali1 172.20.0.1` 两个实例都探测通过；旧 shim `gugu-gemini-shim`、`gugu-gemini-shim-4router` 已停，单元文件留着可回滚。

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
