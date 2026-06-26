import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.models import AgentRunStatus
from coding_orchestration.runners.codex_report import REPORT_CONTRACT_FIELDS
from coding_orchestration.runners.codex_report_schema import build_report_schema, write_report_schema


class CodexReportSchemaTest(unittest.TestCase):
    def test_report_schema_disallows_additional_properties_for_structured_output(self):
        schema = build_report_schema()

        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(schema["properties"]["test_results"]["items"]["additionalProperties"], False)
        self.assertEqual(
            schema["properties"]["status"]["enum"],
            [status.value for status in AgentRunStatus],
        )
        for field in ("raw_status", "status_detail", "failure_type", "known_gaps", "structured"):
            self.assertIn(field, schema["properties"])

    def test_report_schema_requires_contract_fields_and_codex_owned_semantic_fields(self):
        schema = build_report_schema()
        properties = schema["properties"]
        required = set(schema["required"])

        self.assertEqual(schema["required"], list(REPORT_CONTRACT_FIELDS))
        self.assertEqual(set(properties), set(REPORT_CONTRACT_FIELDS))
        for field in (
            "user_facing_summary",
            "technical_summary",
            "implementation_landed",
            "commit_sha",
            "changed_files_summary",
            "branch_slug_candidate",
            "execution_policy_decision",
            "merge_readiness",
        ):
            self.assertIn(field, properties)
            self.assertIn(field, required)

    def test_report_schema_requires_every_declared_property_for_strict_structured_output(self):
        schema = build_report_schema()

        def assert_strict_object(node):
            if not isinstance(node, dict):
                return
            if node.get("type") == "object":
                self.assertIs(
                    node.get("additionalProperties"),
                    False,
                    f"object schema must reject additional properties: {node}",
                )
            if node.get("type") == "object" and "properties" in node:
                self.assertEqual(
                    set(node.get("required") or []),
                    set(node["properties"]),
                    f"object schema must require every property: {node}",
                )
            for value in node.values():
                if isinstance(value, dict):
                    assert_strict_object(value)
                elif isinstance(value, list):
                    for item in value:
                        assert_strict_object(item)

        assert_strict_object(schema)

    def test_write_report_schema_persists_schema_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "report.schema.json"

            write_report_schema(schema_path)

            saved = json.loads(schema_path.read_text(encoding="utf-8"))
            self.assertEqual(saved, build_report_schema())


if __name__ == "__main__":
    unittest.main()
