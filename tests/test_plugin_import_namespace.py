import importlib.util
import sys
import types
import unittest
from pathlib import Path


class PluginImportNamespaceTest(unittest.TestCase):
    def test_directory_plugin_imports_under_hermes_namespace(self):
        repo_root = Path(__file__).resolve().parents[1]
        plugin_dir = repo_root / "coding_orchestration"
        module_name = "hermes_plugins.coding_orchestration"

        saved_path = list(sys.path)
        removed_modules = {}
        for key in list(sys.modules):
            if (
                key == "coding_orchestration"
                or key.startswith("coding_orchestration.")
                or key == "hermes_plugins"
                or key.startswith("hermes_plugins.")
            ):
                removed_modules[key] = sys.modules.pop(key)

        try:
            sys.path = [
                item
                for item in sys.path
                if Path(item or ".").resolve() != repo_root
            ]
            namespace = types.ModuleType("hermes_plugins")
            namespace.__path__ = []
            namespace.__package__ = "hermes_plugins"
            sys.modules["hermes_plugins"] = namespace

            spec = importlib.util.spec_from_file_location(
                module_name,
                plugin_dir / "__init__.py",
                submodule_search_locations=[str(plugin_dir)],
            )
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)

            module = importlib.util.module_from_spec(spec)
            module.__package__ = module_name
            module.__path__ = [str(plugin_dir)]
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            self.assertTrue(callable(module.register))
        finally:
            sys.path = saved_path
            for key in list(sys.modules):
                if key == "hermes_plugins" or key.startswith("hermes_plugins."):
                    sys.modules.pop(key, None)
            sys.modules.update(removed_modules)


if __name__ == "__main__":
    unittest.main()
