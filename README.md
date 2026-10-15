# gugu-channel-adapter（渠道适配层）

挡在咕咕模型网关（New API 原版，不 fork）与某个上游之间的小转发服务：**上游的请求格式/报错与客户端期望不合时，在这里就地修，网关和客户端都不用改。** 一个适配器实例 = 一个上游 + 一组启用的规则（profile）。

```
客户端(Claude Code/Codex…) → 网关(New API) → [渠道适配层:18770/18771] → 上游(HAPI / 4Router …)
```

## 维护约定（最重要）

上游改了之后，适配器可能该删。所以：

1. **每个适配器实例、每条规则都必须写明：是什么 / 何时用 / 为什么 / 证据 / 何时可删。** 缺字段 → 测试失败（`tests/test_docs.py`），CI 不过。
2. 规则登记在 `src/channel_adapter/rules.py`（`@rule(...)`），实例登记在 `profiles/*.json`。
3. 清单 `docs/adapters.md` 由代码生成，**改规则/实例后必须重新生成**：
   `PYTHONPATH=src python3 -m channel_adapter docs > docs/adapters.md`
4. 删规则前：不开它，用 `acceptance/` 的真客户端验收重跑，全绿才删（规则的「何时可删」写了判据）。
5. 给上游厂商的上报单放 `docs/vendor-reports/`，规则的「证据」引用它。

## 现有适配器

见 [docs/adapters.md](docs/adapters.md)（自动生成，含每个实例、每条规则的说明）。

配置做得到的兼容不写适配器，直接配在网关渠道的 param_override 上，登记在 [docs/config-overrides.md](docs/config-overrides.md)（同样要写明用途与可删条件）。

| 实例 | 上游 | 端口 | 网关渠道 |
|---|---|---|---|
| hapi-gemini | HAPI | 18770 | gugu-hapi-gemini（Gemini 首选档） |
| 4router-gemini | 4Router | 18771 | 4router-gemini（Gemini 兜底档） |

## 不做什么

- ❌ 不碰网关代码、不碰客户端；只在网关与上游之间改请求/响应。
- ❌ 不存钥匙：认证头原样透传，钥匙只在网关渠道配置里。
- ❌ 不做路由/重试/计费；换渠道仍是网关的事（适配器只负责把上游的假 200 改回 5xx，让网关能换）。
- 流式（SSE）响应只透传，不改。

## 使用

```
# 本地起一个（默认 127.0.0.1:18770）
PROFILE=hapi-gemini PYTHONPATH=src python3 -m channel_adapter serve
# 测试
PYTHONPATH=src python3 -m unittest discover -s tests
# 部署（预发）
deploy/push.sh ali2 172.19.0.1
```

部署细节、回滚见 [docs/deploy.md](docs/deploy.md)；验收见 [acceptance/README.md](acceptance/README.md)。

## 新增一条规则/实例的流程

1. 先在 `docs/vendor-reports/` 留下复现与请求号（能给厂商上报的最小请求）。
2. `rules.py` 里加规则（只改请求/响应的最小一块），`tests/test_rules.py` 加用例。
3. `profiles/` 里新建或修改实例；重新生成 `docs/adapters.md`。
4. 预发部署 → `acceptance/run_cc.py` 真客户端验收（含工具往返）→ 再上生产。
