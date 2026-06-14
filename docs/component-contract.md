# 组件与封装合同

本仓库没有前端 UI 组件库；这里的“组件”指 Hermes coding 插件中的二次封装层、runner adapter、source adapter、report gate 和可复用 runtime abstraction。后续改动应优先走这些封装，不直接绕过到外部命令或裸数据结构。

## 封装层定位索引表

| 场景 | 优先 import | 包入口 | 关键源码入口 | 代表导出 |
| --- | --- | --- | --- | --- |
| Hermes plugin 注册 | `from coding_orchestration import register` | `coding_orchestration/__init__.py` | `coding_orchestration/__init__.py` | `register` |
| Gateway 事件与 `/coding` 编排 | `from coding_orchestration.orchestrator import CodingOrchestrator` | `coding_orchestration/orchestrator.py` | `coding_orchestration/orchestrator.py` | `CodingOrchestrator` |
| Hermes native tools | `from coding_orchestration.plugin_tools import register_coding_tools` | `coding_orchestration/plugin_tools.py` | `coding_orchestration/plugin_tools.py` | `register_coding_tools` |
| Hermes CLI 子命令 | `from coding_orchestration.cli import register_cli` | `coding_orchestration/cli.py` | `coding_orchestration/cli.py` | `register_cli` |
| 任务状态模型 | `from coding_orchestration.models import TaskStatus, TaskPhase, RunMode` | `coding_orchestration/models.py` | `coding_orchestration/models.py` | `TaskStatus`、`TaskPhase`、`RunMode` |
| 状态转换 | `from coding_orchestration.state_machine import TaskStateMachine` | `coding_orchestration/state_machine.py` | `coding_orchestration/state_machine.py` | `TaskStateMachine` |
| Task Ledger | `from coding_orchestration.ledger import TaskLedger` | `coding_orchestration/ledger.py` | `coding_orchestration/ledger.py` | `TaskLedger` |
| 项目识别 | `from coding_orchestration.project_resolver import ProjectResolver` | `coding_orchestration/project_resolver.py` | `coding_orchestration/project_resolver.py`、`project_knowledge_resolver.py` | `ProjectResolver`、`ProjectKnowledgeResolver` |
| 项目知识初始化 | `from coding_orchestration.project_knowledge_initializer import ProjectKnowledgeInitializer` | `coding_orchestration/project_knowledge_initializer.py` | `coding_orchestration/project_knowledge_initializer.py` | `ProjectKnowledgeInitializer` |
| 外部来源解析 | `from coding_orchestration.source_resolver import SourceResolver` | `coding_orchestration/source_resolver.py` | `coding_orchestration/source_resolver.py`、`feishu_project_reader.py`、`meegle_reader.py` | `SourceResolver`、`FeishuProjectReader`、`MeegleReader` |
| 飞书项目 MCP | `from coding_orchestration.feishu_project_mcp import FeishuProjectMcpAdapter` | `coding_orchestration/feishu_project_mcp.py` | `coding_orchestration/feishu_project_mcp.py`、`orchestrator.py` | `FeishuProjectMcpAdapter`、`FeishuProjectMcpConfig` |
| 飞书项目 intake 规则与编排 | `from coding_orchestration.project_intake import ProjectIntakeRule` | `coding_orchestration/project_intake.py` | `coding_orchestration/project_intake.py`、`orchestrator.py` | `ProjectIntakeRule` |
| 飞书项目工作项绑定 | `from coding_orchestration.project_workitem_binding import ProjectWorkitemIdentity` | `coding_orchestration/project_workitem_binding.py` | `coding_orchestration/project_workitem_binding.py`、`ledger.py` | `ProjectWorkitemIdentity`、`project_workitem_bindings` |
| Prompt 构建 | `from coding_orchestration.prompt_builder import PromptBuilder` | `coding_orchestration/prompt_builder.py` | `coding_orchestration/prompt_builder.py` | `PromptBuilder` |
| 上下文组装 | `from coding_orchestration.context_assembler import ContextAssembler` | `coding_orchestration/context_assembler.py` | `coding_orchestration/context_assembler.py` | `ContextAssembler` |
| Runner 选择 | `from coding_orchestration.runner_router import RunnerRouter` | `coding_orchestration/runner_router.py` | `coding_orchestration/runner_router.py` | `RunnerRouter` |
| Codex CLI runner | `from coding_orchestration.runners.codex_cli import CodexCliRunner` | `coding_orchestration/runners/codex_cli.py` | `coding_orchestration/runners/codex_cli.py` | `CodexCliRunner` |
| Hermes autonomous Codex runner | `from coding_orchestration.runners.hermes_autonomous_codex import HermesAutonomousCodexRunner` | `coding_orchestration/runners/hermes_autonomous_codex.py` | `coding_orchestration/runners/hermes_autonomous_codex.py` | `HermesAutonomousCodexRunner` |
| Generic CLI runner | `from coding_orchestration.runners.generic_cli import GenericCliRunner` | `coding_orchestration/runners/generic_cli.py` | `coding_orchestration/runners/generic_cli.py` | `GenericCliRunner` |
| Report 完整性检查 | `from coding_orchestration.report_contract import validate_codex_semantic_report` | `coding_orchestration/report_contract.py` | `coding_orchestration/report_contract.py` | `validate_codex_semantic_report` |
| 交付拆解准入 | `from coding_orchestration.report_admission import admit_report` | `coding_orchestration/report_admission.py` | `coding_orchestration/report_admission.py` | `admit_report` |
| Diff 边界审计 | `from coding_orchestration.diff_guard import DiffGuard` | `coding_orchestration/diff_guard.py` | `coding_orchestration/diff_guard.py` | `DiffGuard` |
| 安装/卸载逻辑 | `from coding_orchestration.install import run_install_preflight` | `coding_orchestration/install.py` | `coding_orchestration/install.py`、`scripts/install_symlink.py`、`scripts/uninstall_legacy.py` | `run_install_preflight`、`install_from_current_repo`、`uninstall_hermes_coding_components` |
| Dashboard API | `from coding_orchestration.dashboard.plugin_api import router` | `coding_orchestration/dashboard/plugin_api.py` | `coding_orchestration/dashboard/plugin_api.py` | `router` |

## 组件/符号可检索索引

| 符号或关键词 | 先查 |
| --- | --- |
| `register(ctx)` | `coding_orchestration/__init__.py` |
| `pre_gateway_dispatch`、`pre_llm_call` | `coding_orchestration/__init__.py`、`coding_orchestration/orchestrator.py` |
| `command_coding_*`、`tool_task_*` | `coding_orchestration/orchestrator.py` |
| `TaskStatus`、`TaskPhase`、`RunMode`、`AgentRunStatus` | `coding_orchestration/models.py` |
| `TaskStateMachine.transition` | `coding_orchestration/state_machine.py` |
| `report.json`、`summary.md`、`diff.patch` | `coding_orchestration/runners/codex_cli.py`、`coding_orchestration/orchestrator.py` |
| `validate_codex_semantic_report` | `coding_orchestration/report_contract.py` |
| `merge_readiness`、`materialization_allowed` | `coding_orchestration/report_contract.py`、`coding_orchestration/report_admission.py` |
| `SourceResolver.preflight_lark` | `coding_orchestration/source_resolver.py` |
| `FeishuProjectMcpAdapter`、`MCP_USER_TOKEN`、`coding_project_*` | `coding_orchestration/feishu_project_mcp.py`、`coding_orchestration/orchestrator.py`、`coding_orchestration/plugin_tools.py` |
| `project_workitem_bindings`、`source_workitem_key`、`branch_policy=inherit_root_branch` | `coding_orchestration/ledger.py`、`coding_orchestration/project_workitem_binding.py` |
| `ProjectIntakeRule`、`coding_project_intake_sync`、`dry_run` | `coding_orchestration/project_intake.py`、`coding_orchestration/orchestrator.py` |
| `lark_cli_command`、`deferred_source_resolution` | `coding_orchestration/source_resolver.py`、`coding_orchestration/prompt_builder.py` |
| `CODEX_CLI_COMMAND`、`--dangerously-bypass-approvals-and-sandbox` | `coding_orchestration/install.py`、`coding_orchestration/runners/codex_cli.py` |
| `run_install_preflight` | `coding_orchestration/install.py` |
| `uninstall_hermes_coding_components` | `coding_orchestration/install.py` |
| `ProjectInitializationQuality` | `coding_orchestration/project_initialization_quality.py` |
| `ContextAssembler._BUDGETS` | `coding_orchestration/context_assembler.py` |

## 不要绕过的封装

- 不要在 orchestrator 外部直接写 Task Ledger 状态；通过 `TaskLedger` 方法和现有状态流维护 task/run/artifact。
- 不要在 runner 外部手写 Codex CLI flag；通过 `CodexCliRunner.build_command` 和 manifest 字段维护 sandbox 与 resume 语义。
- 不要在 prompt 中猜测飞书/Meegle 正文；通过 `SourceResolver`、reader 和 `lark_cli_command` 传递可恢复读取路径。
- 不要绕过 `FeishuProjectMcpAdapter` 直接调用飞书项目内部接口；Story / Issue / WBS / 状态流转读写统一走插件内私有 MCP adapter。
- 不要用标题、URL 文本或临时字段推断飞书工作项和 Hermes task 关系；通过 `ProjectWorkitemIdentity` 和 `project_workitem_bindings` 落库，bugfix 归属用 `source_workitem_key`。
- 不要在 intake 中按标题去重或直接创建裸 task；飞书项目 Story / Issue 必须先规范化为 `ProjectWorkitemIdentity`，再通过 `ProjectIntakeRule` 和 binding 表保证幂等。
- 不要把 `MCP_USER_TOKEN`、`X-Mcp-Token`、Bearer token 或 `.env*` 内容写入仓库、LLM Wiki、run artifacts、prompt 或测试 fixture。
- 不要用裸 dict 替代 `TaskStatus`、`TaskPhase`、`RunMode` 的公共 contract；状态和阶段需要和测试保持一致。
- 不要跳过 `validate_codex_semantic_report` 或 `admit_report` 直接推进任务阶段。
- 不要把项目初始化事实直接写入 LLM Wiki 当作仓库事实；仓库事实以 `AGENTS.md`、`docs/`、`contracts/` 为源，LLM Wiki 消费这些事实。

## 找不到组件时的定位顺序

1. 先用 `rg` 查公共符号名：`rtk rg -n "class CodingOrchestrator|def command_coding|TaskStatus|RunMode" coding_orchestration tests`。
2. 查测试里的期望行为：`rtk rg -n "merge-test|plan-only|lark|report|TaskStatus" tests`。
3. 查用户文档中的运行约束：`rtk rg -n "plan-only|implementation|merge-test|lark-cli|Gateway" README.md PLUGIN_USAGE.md PLUGIN_PREREQUISITES.md`。
4. 查 plugin manifest 和注册入口：`rtk rg -n "provides_hooks|register_hook|register_command|register_tool" coding_orchestration/plugin.yaml coding_orchestration`。
5. 如果仍无法定位，先在 `docs/project-map.md` 的顶层结构表里找模块边界，再回到源码。

## 常用检索命令

```bash
rtk rg -n "class |def " coding_orchestration
rtk rg -n "command_coding_|tool_task_|handle_gateway_event" coding_orchestration/orchestrator.py
rtk rg -n "TaskStatus|TaskPhase|RunMode|AgentRunStatus" coding_orchestration tests
rtk rg -n "CodexCliRunner|build_command|dangerously-bypass|sandbox" coding_orchestration tests
rtk rg -n "SourceResolver|FeishuProjectReader|MeegleReader|lark_cli_command" coding_orchestration tests
rtk rg -n "validate_codex_semantic_report|admit_report|merge_readiness" coding_orchestration tests
```
