import unittest

from coding_orchestration.plugin_tools import register_coding_tools
from coding_orchestration.tools.tool_operation_dispatcher import ToolOperationDispatcher
from coding_orchestration.tools.tool_specs import coding_tool_specs


class RecordingContext:
    def __init__(self):
        self.tools = {}

    def register_tool(self, **kwargs):
        self.tools[kwargs["name"]] = kwargs


class RecordingDispatcher:
    def __init__(self):
        self.required = []
        self.calls = []

    def require_operation(self, operation_id):
        self.required.append(operation_id)

    def dispatch(self, operation_id, args=None):
        self.calls.append((operation_id, args))
        return {"operation_id": operation_id, "args": args}


class RecordingHost:
    def __init__(self):
        self.calls = []

    def dispatch_tool_operation(self, operation_id, args=None):
        self.calls.append((operation_id, args))
        return {"ok": True, "operation_id": operation_id}


class ToolOperationDispatcherTest(unittest.TestCase):
    def test_register_coding_tools_delegates_by_operation_id(self):
        ctx = RecordingContext()
        dispatcher = RecordingDispatcher()

        register_coding_tools(ctx, object(), dispatcher=dispatcher)
        result = ctx.tools["coding_task_status"]["handler"](task_id="task_1", _internal="ignored")

        expected_operations = [spec.operation_id for spec in coding_tool_specs()]
        self.assertEqual(dispatcher.required, expected_operations)
        self.assertEqual(result, {"operation_id": "task.status", "args": {"task_id": "task_1"}})
        self.assertEqual(dispatcher.calls, [("task.status", {"task_id": "task_1"})])

    def test_register_coding_tools_can_adapt_host_dispatcher_without_tool_method_map(self):
        ctx = RecordingContext()
        host = RecordingHost()

        register_coding_tools(ctx, host)
        result = ctx.tools["coding_project_workitem_search"]["handler"]({"query": "P0"})

        self.assertEqual(result, {"ok": True, "operation_id": "project.workitem_search"})
        self.assertEqual(host.calls, [("project.workitem_search", {"query": "P0"})])

    def test_dispatcher_rejects_unknown_operation(self):
        dispatcher = ToolOperationDispatcher({"task.status": lambda args: {"ok": True}})

        with self.assertRaises(KeyError):
            dispatcher.dispatch("task.missing", {})


if __name__ == "__main__":
    unittest.main()
