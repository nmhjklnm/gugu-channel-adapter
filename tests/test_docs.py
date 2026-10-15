import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
from channel_adapter import docs, rules as R  # noqa: E402

PROFILES = os.path.join(ROOT, "profiles")


class DocsContract(unittest.TestCase):
    """维护约定：每条规则、每个实例都必须写明「是什么 / 何时用 / 为什么 / 何时可删」。"""

    def test_every_rule_is_documented(self):
        for rid, r in R.REGISTRY.items():
            for f in R.DOC_FIELDS:
                self.assertTrue(str(getattr(r, f)).strip(), f"规则 {rid} 缺说明字段 {f}")

    def test_every_profile_is_documented_and_valid(self):
        for p in docs.load_profiles(PROFILES):
            for f in ("name", "what", "used_by", "upstream", "rules", "remove_when"):
                self.assertTrue(p.get(f), f"profile {p.get('name')} 缺 {f}")
            for i in p["rules"]:
                self.assertIn(i, R.REGISTRY, f"profile {p['name']} 引用了不存在的规则 {i}")

    def test_generated_doc_is_current(self):
        with open(os.path.join(ROOT, "docs", "adapters.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), docs.render(PROFILES), "docs/adapters.md 过期：PYTHONPATH=src python3 -m channel_adapter docs > docs/adapters.md")


    def test_config_overrides_are_documented(self):
        """配置级适配（param_override）同样必须写明 是什么/何时用/为什么/证据/何时可删。"""
        with open(os.path.join(ROOT, "docs", "config-overrides.md"), encoding="utf-8") as f:
            parts = f.read().split("\n## ")[1:]
        self.assertTrue(parts)
        for p in parts:
            head = p.split("\n", 1)[0]
            for label in ("渠道：", "是什么：", "何时用：", "为什么：", "证据：", "何时可删："):
                self.assertIn(label, p, f"配置级适配 {head} 缺「{label}」")


if __name__ == "__main__":
    unittest.main()
