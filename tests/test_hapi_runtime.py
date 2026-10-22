import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from channel_adapter import __main__, server

ROOT = Path(__file__).resolve().parents[1]


class HapiRuntimeTest(unittest.TestCase):
    def test_profile_uses_only_its_documented_runtime_rule(self):
        p = server.load_profile("hapi-errors", str(ROOT / "profiles"))
        self.assertEqual(p["runtime"], "node")
        self.assertEqual(p["rules"], ["hapi-error-envelope", "responses-reasoning-content"])
        with self.assertRaisesRegex(ValueError, "Node HTTP runtime"):
            server.make_handler(p)

    def test_mixed_rules_or_changed_fixed_upstream_cannot_be_silently_ignored(self):
        original = json.loads((ROOT / "profiles/hapi-errors.json").read_text())
        for change in ({"runtime": "python"}, {"rules": ["schema-array-items", "hapi-error-envelope"]}, {"upstream": "https://other.invalid"}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as d:
                p = Path(d) / "p.json"
                p.write_text(json.dumps({**original, **change}))
                with self.assertRaises(SystemExit):
                    server.load_profile(str(p), d)

    def test_cli_dispatches_without_parsing_or_reimplementing_node_rules(self):
        with patch.dict(os.environ, {"PROFILE": "hapi-errors", "BIND": "127.0.0.1", "PORT": "18318"}, clear=True), patch("shutil.which", return_value="/test/node"), patch("os.execvpe") as execute:
            self.assertEqual(__main__.main(["serve"]), 0)
        node, args, env = execute.call_args.args
        self.assertEqual(node, "/test/node")
        self.assertTrue(Path(args[1]).is_file())
        self.assertEqual(env["HOST"], "127.0.0.1")
        self.assertEqual(env["PORT"], "18318")

    def test_missing_node_or_upstream_override_fails_loudly(self):
        with patch.dict(os.environ, {"PROFILE": "hapi-errors"}, clear=True), patch("shutil.which", return_value=None):
            with self.assertRaisesRegex(SystemExit, "Node 24"):
                __main__.main(["serve"])
        with patch.dict(os.environ, {"PROFILE": "hapi-errors", "UPSTREAM": "http://elsewhere.invalid"}, clear=True):
            with self.assertRaisesRegex(SystemExit, "固定上游"):
                __main__.main(["serve"])


if __name__ == "__main__":
    unittest.main()
