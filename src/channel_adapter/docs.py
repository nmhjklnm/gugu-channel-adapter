"""从规则注册表与 profiles 生成 docs/adapters.md（tests/test_docs.py 保证文件与代码一致）。"""
from __future__ import annotations

import glob
import json
import os

from . import rules as R


def load_profiles(profiles_dir: str) -> list[dict]:
    out = []
    for p in sorted(glob.glob(os.path.join(profiles_dir, "*.json"))):
        with open(p, encoding="utf-8") as f:
            out.append(json.load(f))
    return out


def render(profiles_dir: str) -> str:
    profiles = load_profiles(profiles_dir)
    used = {i: [p["name"] for p in profiles if i in p["rules"]] for i in R.REGISTRY}
    L = ["# 适配器清单（自动生成，别手改）", "",
         "生成：`PYTHONPATH=src python3 -m channel_adapter docs > docs/adapters.md`。改规则或 profile 后必须重新生成，否则测试失败。", "",
         "## 实例（profile）：每个挂在网关渠道前面的适配器", ""]
    for p in profiles:
        L += [f"### {p['name']}", f"- 是什么：{p['what']}", f"- 谁在用：{p['used_by']}", f"- 上游：{p['upstream']}",
              f"- 启用的规则：{'、'.join(p['rules'])}", f"- 何时整个撤掉：{p['remove_when']}", ""]
    L += ["## 规则目录：每条规则是什么、何时用、为什么、何时可删", ""]
    for rid, r in R.REGISTRY.items():
        L += [f"### {rid}（{'请求' if r.kind == 'request' else '响应'}规则 · {r.added} 加入）",
              f"- 是什么：{r.what}", f"- 何时用：{r.when}", f"- 为什么：{r.why}", f"- 证据：{r.evidence}",
              f"- 何时可删：{r.remove_when}", f"- 被哪些实例启用：{'、'.join(used[rid]) or '（无）'}", ""]
    return "\n".join(L).rstrip() + "\n"
