# 项目地图

本仓库是 `coding_orchestration` Hermes 用户插件源码仓库。它把飞书 `/coding` 需求入口、Hermes Gateway、Task Ledger、LLM Wiki 和 Codex CLI runner 组织成一个可审计的编码任务闭环。

## 仓库形态

- 仓库类型：Python Hermes plugin。
- 工作区形态：单包源码仓库，没有 `apps/*` 或独立主前端子域。
- 运行入口：Hermes 通过 `~/.hermes/plugins/coding_orchestration -> 当前仓库/coding_orchestration` 软链接加载插件。
- 运行根：默认固定为 `~/.hermes/coding-orchestration`，用于 ledger、runs、workspaces 和本地 LLM Wiki。

## 顶层结构

| 路径 | 角色 |
| --- | --- |
| `coding_orchestration/__init__.py` | Hermes plugin 注册入口，注册 Gateway hook、`/coding` 命令、native tools 和 operator skill。 |
| `coding_orchestration/orchestrator.py` | 编排主线：处理 Gateway 事件、命令、任务创建、plan、implementation、QA、merge-test 和状态回写。 |
| `coding_orchestration/models.py` | 公共枚举和数据结构：任务状态、phase、run mode、runner capability、artifact contract。 |
| `coding_orchestration/state_machine.py` | 任务状态转换规则，以及 runner/source 状态到 task 状态的映射。 |
| `coding_orchestration/ledger.py` | SQLite Task Ledger，保存运行期事实、active binding、run、artifact 和人工决策。 |
| `coding_orchestration/project_resolver.py`、`project_knowledge_resolver.py`、`project_knowledge_initializer.py` | 项目识别、LLM Wiki project profile 消费和项目知识初始化。 |
| `coding_orchestration/source_resolver.py`、`feishu_project_reader.py`、`meegle_reader.py` | 飞书 Wiki/Docx、飞书 Project/Meegle 来源解析与权限预检。 |
| `coding_orchestration/prompt_builder.py`、`context_assembler.py` | Codex 可见 prompt 与运行上下文 artifact 组装。 |
| `coding_orchestration/runner_router.py`、`coding_orchestration/runners/` | runner 选择与 Codex CLI / Hermes autonomous Codex / generic CLI 适配。 |
| `coding_orchestration/report_contract.py`、`report_admission.py`、`run_summary_writer.py`、`run_log_compactor.py` | runner report 质量门、交付拆解准入、summary 写入和日志压缩。 |
| `coding_orchestration/diff_guard.py` | implementation/QA/merge-test 后的路径边界审计。 |
| `coding_orchestration/dashboard/` | Hermes dashboard tab API 和 manifest。 |
| `scripts/` | 本地软链接安装和卸载入口。 |
| `tests/` | `unittest` 测试，覆盖插件注册、状态机、orchestrator、runner、source、dashboard、安装脚本等。 |
| `examples/` | 项目 registry 与 `WORKFLOW.md` 示例。 |
| `docs/` | 项目沉淀文档、bootstrap 合同文档、部署/前置准备、状态机、交付流和实施计划。 |
| `docs/plans/` | superpowers 或执行计划产出的实施计划归档；该目录作为项目沉淀提交。 |
| `docs/local/presentations/` | 本地宣讲、demo、分享材料目录；该目录被 `.gitignore` 忽略，不作为项目事实来源。 |
| `README.md`、`PLUGIN_USAGE.md`、`PLUGIN_PREREQUISITES.md` | 使用说明、前置准备和运行边界。 |

## 运行链路

```text
Feishu / Hermes Gateway
  -> coding_orchestration pre_gateway_dispatch
  -> CodingOrchestrator
  -> TaskLedger + ProjectResolver + SourceResolver + LLM Wiki
  -> PromptBuilder + ContextAssembler
  -> RunnerRouter
  -> CodexCliRunner / HermesAutonomousCodexRunner / GenericCliRunner
  -> report.json / summary.md / diff.patch / run-log.md
  -> TaskLedger + 飞书状态回写 + LLM Wiki run_summary
```

## Guarded Path

| 路径 | 原因 |
| --- | --- |
| `.env*` | 可能包含 Hermes、飞书、Codex 或项目密钥。 |
| `~/.hermes/.env`、`~/.hermes/auth.json`、`~/.codex/auth.json` | 本地凭据，只能读取必要状态，不得复制进仓库。 |
| `~/.hermes/coding-orchestration/ledger.db`、`runs/`、`workspaces/`、`llm-wiki/` | 运行期事实和产物，不是源码事实层。 |
| `coding_orchestration/orchestrator.py` | 状态流、人工门禁和 runner 调度集中在这里，改动需要配套状态/流程测试。 |
| `coding_orchestration/runners/codex_cli.py` | Codex CLI 权限 flag、sandbox 和 report 写入点，改动可能影响安全边界。 |
| `coding_orchestration/install.py`、`scripts/install_symlink.py`、`scripts/uninstall_legacy.py` | 会影响本机 Hermes 插件安装、卸载和 Gateway 重启，执行前需先 dry-run 或看清参数。 |
| `coding_orchestration/report_contract.py`、`report_admission.py` | 结构化 report 质量门，改动会影响任务是否可进入下一阶段。 |
| `coding_orchestration/state_machine.py`、`models.py` | 公共状态 contract，改动需同步测试和用户可见文案。 |

## 不确定项

- 仓库没有 `pyproject.toml`、`requirements.txt` 或 lockfile；测试当前从文档和现有测试推断为标准库 `unittest`。
- Hermes CLI、Codex CLI、`lark-cli`、飞书权限和 Gateway 状态依赖本机环境，不属于本仓库可静态验证事实。
- `docs/` 下的流程图、部署指南、前置准备和交付流文档作为项目沉淀文档保留；superpowers 生成的执行计划统一放入可提交的 `docs/plans/`。
- 宣讲/demo 材料放入忽略的 `docs/local/presentations/`。
