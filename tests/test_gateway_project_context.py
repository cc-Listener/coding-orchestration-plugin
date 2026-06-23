import tempfile
import unittest
from pathlib import Path

from coding_orchestration.gateway.gateway_project_context import (
    local_project_path_for_candidate,
    local_project_search_roots,
    project_aliases_from_human_text,
    project_folder_candidates_from_text,
)


class GatewayProjectContextTest(unittest.TestCase):
    def test_project_folder_candidates_from_text_reads_backticks_and_path_labels(self):
        text = "项目名称：商户后台，文件夹名称为`bestvoy-admin`，项目路径是 ~/Desktop/project/oms"

        candidates = project_folder_candidates_from_text(text)

        self.assertEqual(candidates, ["bestvoy-admin", "~/Desktop/project/oms"])

    def test_local_project_path_uses_injected_search_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            explicit_root = root / "projects"
            project = explicit_root / "bestvoy-admin"
            project.mkdir(parents=True)

            resolved = local_project_path_for_candidate(
                "bestvoy-admin",
                search_roots=[explicit_root],
            )

            self.assertEqual(resolved, project.resolve())

    def test_local_project_search_roots_dedupes_registry_parents_and_extra_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_parent = root / "registry"
            registry_project = registry_parent / "known-admin"
            extra_root = root / "extra"
            registry_project.mkdir(parents=True)
            extra_root.mkdir()

            roots = local_project_search_roots(
                registry_project_paths=[str(registry_project)],
                extra_roots=[extra_root, registry_parent],
            )

            self.assertEqual(roots, [registry_parent.resolve(), extra_root.resolve()])

    def test_project_aliases_from_human_text_keeps_project_name_and_human_aliases(self):
        aliases = project_aliases_from_human_text("这是oms后台，项目叫订单后台", "oms_operation_web")

        self.assertEqual(aliases, ["oms_operation_web", "订单后台", "oms后台"])


if __name__ == "__main__":
    unittest.main()
