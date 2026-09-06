import unittest

from backend.mcp_tool_router import validate_tool_calls


class MCPToolRouterTests(unittest.TestCase):
    def test_validation_rejects_unknown_tools_and_arguments(self):
        tools = [{
            "name": "get_invoice", "inputSchema": {
                "type": "object",
                "properties": {"searchKey": {"type": "string"}},
                "required": ["searchKey"],
            },
        }]
        calls = validate_tool_calls(
            [
                {"name": "invented", "arguments": {"secret": "x"}},
                {"name": "get_invoice", "arguments": {"searchKey": "wrong", "extra": "drop"}},
            ],
            tools,
            argument_overrides={"searchKey": "canonical company"},
        )
        self.assertEqual(calls, [{
            "name": "get_invoice", "arguments": {"searchKey": "canonical company"},
        }])

    def test_validation_enforces_required_parameters_and_call_limit(self):
        tools = [
            {"name": f"tool_{index}", "inputSchema": {
                "properties": {"query": {"type": "string"}}, "required": ["query"],
            }}
            for index in range(3)
        ]
        calls = validate_tool_calls(
            [{"name": f"tool_{index}", "arguments": {"query": "q"}} for index in range(3)],
            tools,
            max_calls=2,
        )
        self.assertEqual([call["name"] for call in calls], ["tool_0", "tool_1"])


if __name__ == "__main__":
    unittest.main()
