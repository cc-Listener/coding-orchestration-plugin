import unittest

from coding_orchestration.tool_specs import coding_tool_specs


class ToolSpecTest(unittest.TestCase):
    def test_specs_include_existing_public_tools(self):
        names = [spec.name for spec in coding_tool_specs()]

        self.assertIn("coding_task_create", names)
        self.assertIn("coding_task_status", names)
        self.assertIn("coding_task_run", names)
        self.assertIn("coding_project_mcp_preflight", names)

    def test_specs_have_operation_ids_and_schemas(self):
        for spec in coding_tool_specs():
            self.assertTrue(spec.operation_id)
            self.assertEqual(spec.input_schema.get("type"), "object")
            self.assertIsInstance(spec.description, str)
            self.assertEqual(spec.schema()["parameters"].get("type"), "object")

    def test_specs_are_host_agnostic_except_public_tool_names(self):
        joined = "\n".join(spec.description for spec in coding_tool_specs())

        self.assertNotIn("Hermes runtime", joined)
        self.assertNotIn("Hermes coding task", joined)
