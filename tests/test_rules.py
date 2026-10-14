import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from channel_adapter import rules as R  # noqa: E402

# Claude Code 自带 ArtifactData 工具里引发 400 的真实片段：where 是「数组的数组」，内层只有 prefixItems 没有 items
ARTIFACT_QUERY = {"type": "object", "properties": {
    "action": {"type": "string"},
    "query": {"type": "object", "properties": {
        "where": {"type": "array", "maxItems": 10, "items": {"type": "array", "prefixItems": [{"type": "string"}, {"type": "string"}, {}]}},
        "limit": {"type": "integer"}}}},
    "required": ["action", "ghost"]}


class SchemaRules(unittest.TestCase):
    def test_array_items_nested_prefixitems(self):
        body = {"tools": [{"name": "ArtifactData", "input_schema": copy.deepcopy(ARTIFACT_QUERY)}]}
        n = R.REGISTRY["schema-array-items"].apply(body, None)
        self.assertEqual(n, 1)
        inner = body["tools"][0]["input_schema"]["properties"]["query"]["properties"]["where"]["items"]
        self.assertEqual(inner["items"], {})

    def test_array_items_openai_and_responses_shapes(self):
        a = {"tools": [{"type": "function", "function": {"name": "f", "parameters": {"type": "object", "properties": {"a": {"type": "array"}}}}}]}
        b = {"tools": [{"type": "function", "name": "f", "parameters": {"type": "object", "properties": {"a": {"type": "array"}}}}]}
        self.assertEqual(R.REGISTRY["schema-array-items"].apply(a, None), 1)
        self.assertEqual(R.REGISTRY["schema-array-items"].apply(b, None), 1)

    def test_array_with_items_untouched(self):
        body = {"tools": [{"input_schema": {"type": "object", "properties": {"a": {"type": "array", "items": {"type": "string"}}}}}]}
        before = copy.deepcopy(body)
        self.assertEqual(R.REGISTRY["schema-array-items"].apply(body, None), 0)
        self.assertEqual(body, before)

    def test_required_undefined_removed(self):
        body = {"tools": [{"input_schema": copy.deepcopy(ARTIFACT_QUERY)}]}
        self.assertEqual(R.REGISTRY["schema-required-undefined"].apply(body, None), 1)
        self.assertEqual(body["tools"][0]["input_schema"]["required"], ["action"])

    def test_required_all_undefined_drops_key(self):
        body = {"tools": [{"input_schema": {"type": "object", "properties": {}, "required": ["x"]}}]}
        R.REGISTRY["schema-required-undefined"].apply(body, None)
        self.assertNotIn("required", body["tools"][0]["input_schema"])


class PadToolResult(unittest.TestCase):
    def test_anthropic_only_tool_result(self):
        b = {"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "x", "input": {}}]},
                          {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "r"}]}]}
        self.assertEqual(R.REGISTRY["pad-tool-result"].apply(b, None), 1)
        self.assertEqual(b["messages"][-1]["content"][-1], {"type": "text", "text": "."})

    def test_openai_tool_role(self):
        b = {"messages": [{"role": "user", "content": "q"}, {"role": "tool", "tool_call_id": "c", "content": "r"}]}
        self.assertEqual(R.REGISTRY["pad-tool-result"].apply(b, None), 1)
        self.assertEqual(b["messages"][-1], {"role": "user", "content": "."})

    def test_untouched_when_text_present_or_plain(self):
        a = {"messages": [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "r"}, {"type": "text", "text": "继续"}]}]}
        b = {"messages": [{"role": "user", "content": "你好"}]}
        self.assertEqual(R.REGISTRY["pad-tool-result"].apply(a, None), 0)
        self.assertEqual(R.REGISTRY["pad-tool-result"].apply(b, None), 0)


class MergeSystem(unittest.TestCase):
    def test_merge_into_adjacent_user(self):
        b = {"messages": [{"role": "user", "content": [{"type": "text", "text": "a"}]}, {"role": "system", "content": "提醒"},
                          {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "x", "input": {}}]},
                          {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "r"}]}, {"role": "system", "content": "又一条"}]}
        self.assertEqual(R.REGISTRY["merge-system-messages"].apply(b, None), 2)
        self.assertEqual([m["role"] for m in b["messages"]], ["user", "assistant", "user"])
        self.assertEqual([c["type"] for c in b["messages"][-1]["content"]], ["tool_result", "text"])


class Error200(unittest.TestCase):
    def test_cases(self):
        f = R.REGISTRY["error-200-to-502"].apply
        self.assertEqual(f(200, "application/json", b'{"type":"error","error":{"message":"x"}}'), 502)
        self.assertEqual(f(200, "application/json", b'{"error":{"message":"x"}}'), 502)
        self.assertIsNone(f(200, "application/json", b'{"id":"m","type":"message","content":[]}'))
        self.assertIsNone(f(200, "text/event-stream", b'{"type":"error"}'))
        self.assertIsNone(f(400, "application/json", b'{"type":"error"}'))


if __name__ == "__main__":
    unittest.main()
