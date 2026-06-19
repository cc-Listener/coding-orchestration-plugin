# Hermes Coding Decoupled Architecture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 Hermes Coding 插件改造成核心域、应用服务、端口和适配器分层的长期可迭代架构，同时保持现有 `/coding` 主流程可运行。

**Architecture:** 先新增配置、ToolSpec、端口和服务 façade，不破坏现有导入路径；再逐步把 `CodingOrchestrator` 的工具、MCP、任务、运行和交付逻辑迁移到应用服务。Hermes plugin 继续作为当前 host adapter，但核心服务不再依赖 Hermes、MCP transport、CLI 命令或本机路径。

**Tech Stack:** Python 3 stdlib, `unittest`, Hermes plugin adapter, SQLite Task Ledger, Codex CLI runner, Feishu Project MCP adapter.

---

## Scope

本计划覆盖从正式设计落地到第一轮全面重构的执行路径，并保留后续长期治理阶段。每个任务都必须保持现有主流程兼容，优先新增 contract tests，再迁移实现，最后清理旧测试。

## Execution Rules

- 所有 shell 命令使用 `rtk` 前缀。
- 不修改 `.env*`、Hermes auth、Codex auth、飞书 token 或本地运行根。
- 不删除旧测试，除非已有等价 contract 或主流程测试覆盖。
- 不在同一任务里同时做大迁移和旧测试删除。
- 每个阶段至少跑对应聚焦测试；阶段结束跑完整单测。
- 若遇到用户未提交改动，先读清楚再在其基础上增量修改，不回滚。

## End-to-End Phase Roadmap

全线阶段按设计文档的 0-17 阶段推进。当前 Task 1-14 是第一轮执行批次，后续如果继续深化，会把 storage/source/governance 拆成独立任务，而不是塞回 orchestrator。

| 设计阶段 | 执行任务 | 当前状态 | 退出标准 |
| --- | --- | --- | --- |
| 0. 现状盘点 | Task 1 / Task 14 | In Progress | 行数、hard code、旧测试清单可复查 |
| 1. 架构合同 | Task 1 / Task 13 | Done | 设计文档、实施计划、component contract 一致 |
| 2. 配置边界 | Task 2 | Done | `RuntimeConfig` / `ToolConfig` contract tests 通过 |
| 3. ToolSpec / IntentSpec | Task 3 | Done | Tool schema 从 host 注册层移出 |
| 4. Ports 反转依赖 | Task 4 | Done | port protocol contract tests 通过 |
| 5. MCP / WorkItem 解耦 | Task 5 | Done | MCP 读写经 `WorkItemService`，写操作保留确认 |
| 6. Task 用例解耦 | Task 6 | Done | task create/status/source indexing 有 service 覆盖 |
| 7. Run 生命周期解耦 | Task 7 | Done | run blocker、timeout、phase、result mapping 已迁出；runner 执行副作用仍由 orchestrator façade 编排 |
| 8. StatusPolicy | Task 8 | Done | 状态详情、known gaps、runner failure 投影已集中到 `status_policy.py` |
| 9. DeliveryService | Task 15 | Done | decomposition session、breakdown approval、materialize 编排、status projection、run-next decision 和 requirement rollup 已迁出；orchestrator 保留 façade、ledger callback 绑定和用户消息渲染 |
| 10. Prompt 模板治理 | Task 9 | Done | run instructions 和 source block 模板已从 `PromptBuilder` 拆出 |
| 11. Runner adapter 拆分 | Task 10 | Done | Codex command builder、process runner、report policy、report loader、report writer 和 artifact collector 已拆出 |
| 12. Storage / Knowledge 拆分 | Task 16 | Done | schema/migration、ledger repositories 和 KnowledgePort adapter 已有独立 contract |
| 13. Source adapter 拆分 | Task 17 | In Progress | URL/identity parser、recovery mapper、Feishu document reader、Feishu work item reader/open-api adapter、Feishu/Meegle common normalizer 和 `SourceResult` 统一结果合同已拆出；后续继续迁移剩余业务层只消费 `SourcePort` 结果 |
| 14. Skill 解耦 | Task 11 | Done | core skill 与 Hermes binding skill 分离，Hermes 只注册 binding skill |
| 15. 旧测试清理 | Task 12 | In Progress | 已开始删除由 contract/main-flow 等价覆盖的旧私有 helper 测试 |
| 16. 文档同步 | Task 13 | Done | 项目地图、组件合同和 conventions 已随新边界同步；无新增用户可见命令语义 |
| 17. 长期治理 | Task 18 | In Progress | 行数、hard code、边界漂移已可通过 guard 发现；service/tool hard-code 已收紧为 fail gate，后续继续收紧大文件债务 |

## Responsibility Ownership

后续迭代按职责域推进，不按文件大小随机拆分。每一轮只允许一个主责域承接业务规则迁移，其他域只做必要协作。

| 职责域 | 主责文件或目录 | 可以承接的变化 | 不应承接的变化 |
| --- | --- | --- | --- |
| 架构治理 | `docs/plans/`、`docs/component-contract.md` | 阶段切分、边界规则、验收口径 | 用户可见命令实现 |
| Config / Tool contract | `config.py`、`tool_specs.py` | 默认路径、默认命令、工具 schema 和 operation id | 业务状态推进 |
| Port contract | `ports.py` | host/runner/source/workitem/storage/knowledge 能力合同 | 具体 Hermes、MCP、Codex、SQLite 实现 |
| Application service | `services/` | task/run/delivery/workitem 用例编排和纯规则 | subprocess、MCP transport、Hermes hook 注册 |
| Domain policy | `models.py`、`state_machine.py`、`status_policy.py`、`report_contract.py` | 状态、phase、report、known gaps 和准入策略 | host 文案和外部命令 |
| Adapter | `runners/`、`source_resolver.py`、`feishu_project_reader.py`、`feishu_document_reader.py`、`feishu_work_item_reader.py`、`feishu_project_mcp.py`、后续 storage/source adapter | 外部系统绑定、脱敏、错误映射、transport | 核心业务决策 |
| Host shell / Presentation | `__init__.py`、`cli.py`、`plugin_tools.py`、orchestrator command façade | 注册、命令解析、用户可见消息 | 新业务规则和状态策略 |
| Tests / Governance | `tests/`、后续 guard scripts | contract、主流程、安全边界、行数/hard code/边界漂移检查 | 只保护旧私有 helper 名称 |

## Follow-up Execution Queue

第一轮 Task 1-14 已经建立合同和拆分主干。剩余工作必须按下面队列继续，不能把 pending 项重新堆回 `orchestrator.py`。

| 后续任务 | 覆盖设计阶段 | 主责 | 状态 | 退出标准 |
| --- | --- | --- | --- | --- |
| Task 15. DeliveryService 副作用迁移 | 9 | Delivery service | Done | materialize/run-next/status delivery 的可测编排从 orchestrator 迁出，orchestrator 只保留 façade |
| Task 16. Storage / Knowledge 拆分 | 12 | Storage + Knowledge adapter | Done | schema/migration、task/run/artifact/binding repositories 和 KnowledgePort adapter 有独立 contract，service 不依赖存储细节 |
| Task 17. Source adapter 拆分 | 13 | Source adapter | In Progress | URL parser、recovery mapper、Feishu document reader、Feishu work item reader/open-api adapter、common normalizer 和 `SourceResult` 已独立；后续继续迁移剩余业务层只看 `SourcePort` 结果 |
| Task 18. 大文件与 hard code 治理 | 0 / 17 | Architecture guard | Done | 行数、hard code、边界漂移可以通过脚本和测试稳定发现；core/service/tool hard-code 回归会失败，剩余遗留大文件默认输出 watchlist |
| Task 19. 测试套件模块化 | 15 / 17 | Test governance | In Progress | `tests/test_orchestrator_run_flow.py` 已从 10005 行拆到 226 行，仅保留 smoke、kanban transition 和 resume sandbox；后续聚焦旧私有 helper 测试继续收敛到 contract tests |
| Task 20. Presentation presenter 拆分 | 17 | Host shell / Presentation | Done | task list 与 run completion 用户可见文案迁出 orchestrator，保留兼容 wrapper，新增 presenter contract tests |
| Task 21. Status presenter 拆分 | 17 | Host shell / Presentation | Done | task status 用户可见详情迁出 orchestrator，保留兼容 wrapper，新增 status presenter contract tests |
| Task 22. Gateway rewrite presenter 拆分 | 17 | Host shell / Presentation | Done | Coding Mode rewrite 确认、低置信度补充和 handoff 文案迁出 orchestrator，保留兼容 wrapper，新增 gateway rewrite presenter contract tests |
| Task 23. Run start presenter 拆分 | 17 | Host shell / Presentation | Done | plan-only/implementation/QA 启动 ACK、active run 和 cannot-start 文案迁出 orchestrator，保留兼容 wrapper，新增 run start presenter contract tests |
| Task 24. Feedback presenter 拆分 | 17 | Host shell / Presentation | Done | `/coding continue/change/bugfix` 反馈、需求变更、图片未捕获和人工澄清文案迁出 orchestrator，保留兼容 wrapper，新增 feedback presenter contract tests |
| Task 25. Merge-test presenter 拆分 | 17 | Host shell / Presentation | Done | prepare/merge-test 状态提示、blocked 风险确认、风险放行说明、QA 风险确认和启动 ACK 迁出 orchestrator，保留兼容 wrapper，新增 merge-test presenter contract tests |
| Task 26. Background run notifier 拆分 | 7 / 17 | Host notification | Done | 后台线程启动、sender 调度、reply fallback、失败通知模板和 completion notification record 迁出 orchestrator；状态推进和 pending action 仍由 orchestrator façade 控制 |
| Task 27. Gateway binding service 拆分 | 6 / 17 | Host binding service | Done | event source、binding key、active task、coding mode、active project、pending rewrite/action 存取迁出 orchestrator；确认后命令执行和业务 gate 仍由 orchestrator façade 控制 |

## Long-term Execution Queue

Task 28 之后进入长期迭代队列。每一项仍按“一个职责域、先 contract、保 façade、跑聚焦测试、同步文档、回流 guard”的节奏推进，避免新能力重新堆回 `orchestrator.py`。

| 后续任务 | 覆盖设计阶段 | 主责 | 状态 | 退出标准 |
| --- | --- | --- | --- | --- |
| Task 28. Workspace / Git / Diff checkpoint service | 7 / 11 / 17 | Run support service + Diff guard | Done | workspace 选择、clean-tree 检查、git HEAD、checkpoint commit、QA/merge-test artifact 收集、run manifest/session policy 从 orchestrator 迁到独立 service；`orchestrator.py` 只保留 runner 启动和状态映射 façade |
| Task 29. Command / Gateway controller 瘦身 | 6 / 17 | Host shell | In Progress | Gateway event 解析、命令分发、确认词路由和 active project/task 应用进入 controller/executor；已迁出显式命令解析、命令归一化、命令 route plan、handler key、reply mode、task id 来源策略、merge-test 参数、rewrite canonical command、确认/取消词、rewrite 风险确认、event dedupe、授权探测、custom route executor、pending action executor 和 active context helper，orchestrator 已集中 immediate reply dispatch 并委托 custom/pending/active-context helper，后续继续迁执行副作用 |
| Task 30. Run orchestration service 闭环 | 9 / 17 | Run application service | Complete | 已新增 `run_orchestration_service.py`、`run_background_orchestration.py`、`run_failure_report_projection.py`、`run_report_refinement_projection.py`、`run_diff_guard_service.py`、`run_dispatch_service.py`、`run_status_transition_service.py`、`run_evidence_observation_service.py`、`run_start_selection_projection.py`、`run_session_projection.py`、`run_session_writeback_service.py`、`run_prompt_projection.py`、`run_context_artifact_service.py`、`run_start_artifact_service.py`、`run_manifest_artifact_service.py`、`run_manifest_session_writeback_service.py`、`run_stderr_artifact_service.py`、`run_report_artifact_service.py`、`run_summary_artifact_service.py`、`run_ledger_projection.py`、`run_ledger_writeback_service.py`、`run_summary_projection.py`、`run_summary_writeback_service.py`、`run_artifact_paths.py`、`run_project_writeback_service.py`、`run_completion_writeback_service.py` 和 `run_reconcile_writeback_service.py`；已迁出后台 orchestration、failure/refinement/start/session/prompt projection、run diff guard observation、runner dispatch、run status transition、run evidence observation、run manifest session metadata host writeback、run artifact 文件写入、run report/summary artifact 读写、run report summary excerpt、execution policy artifact 读取、run artifact path contract、completion/report/project writeback payload、Project writeback host gate/callback、summary writer host callback、start_run 与 active run reconcile 的 artifact / agent_run / merge-test record 写回 payload 聚合、run ledger host callback、run session host callback、completed run 与 active run reconcile 的 run summary writer payload 聚合、fresh completed run 写回协调和 active run reconcile 写回协调等规则。`run_completion_writeback_service.py` 和 `run_reconcile_writeback_service.py` 分别负责 fresh completed 与 active reconcile 的完成态写回协调；Task 30 已关闭，后续大文件治理、hard code 清理和 Hermes/Skill 深度解耦进入 Task 31+ / Task 18/20 长期治理。`orchestrator.py` 当前 4658 行，`run_reconcile_writeback_service.py` 当前 137 行，background notifier 继续只做 host 通知 |

Task 30 最新补充：`run_checkpoint_preparation_service.py` 已承接 QA / merge-test checkpoint preparation callback 选择、调用和 checkpoint payload 到 manifest update 的映射。该 service 只调用注入 callback 并返回 `manifest_updates`，不直接 mutate manifest、不写 artifact/ledger/report/summary、不启动 runner、不推进状态；mode 到 checkpoint kind/target branch 选择仍归 `run_start_selection_projection.py`，manifest 文件写入仍归 artifact service，implementation dirty-check 后置 manifest 写回仍是后续切片。
Task 30 最新补充：`run_implementation_checkpoint_service.py` 已承接 implementation dirty 后置 checkpoint 生成和 manifest artifact writeback callback 接线。该 service 只消费已计算好的 dirty flag，调用注入 checkpoint / manifest writer callback，不判断 dirty、不构造 blocked report、不写 ledger/report/summary、不启动 runner、不推进状态；dirty observation 仍归 `run_evidence_observation_service.py`，blocked report refinement 仍归 `run_report_refinement_projection.py`。
Task 30 最新补充：`run_manifest_session_writeback_service.py` 已承接 runner session metadata 到 run manifest 的 host callback 接线。该 service 只消费已解析 `session_id`，复用 `run_manifest_service.build_manifest_session_fields()` 更新 manifest object/dict 并调用注入 manifest metadata writer；不解析 stdout、不写 ledger/report/summary、不启动 runner、不推进状态。session id 来源、task session ledger update 和 Codex attach/resume command 规则仍归原边界。
Task 30 最新补充：`run_completion_writeback_service.py` 已承接 fresh completed run 的 completion projection、stale observation、状态 transition、ledger/session/summary/project writeback 和 final result payload 协调。该 service 只消费已完成 runner result 的投影数据和注入 callback；不启动 runner、不执行 diff guard、不收集 QA evidence、不判断 dirty、不准备 checkpoint、不解析 stdout、不直接持有 `TaskLedger` / `RunSummaryWriter` / `WorkItemService` / MCP adapter。

Task 30 最新补充：`run_reconcile_writeback_service.py` 已承接 active run reconcile 完成态的 completion projection、最终 `report.json` 写回、状态 transition、ledger upsert、runner session update、summary writer callback 和 result payload 协调。该 service 只消费已归一化 report 与注入 callback；不读取 workspace、不启动 runner、不执行 diff guard、不收集 QA evidence、不判断 dirty、不准备 checkpoint、不解析 stdout、不直接持有 `TaskLedger` / `RunSummaryWriter` 或 MCP adapter。Task 30 closure cleanup 已完成，后续大文件治理、hard code 清理和 Hermes/Skill 深度解耦不再挂入本任务。
| Task 31. SourcePort 消费闭环 | 13 | Source adapter + Task service | Planned | orchestrator、TaskService 和 prompt/context 只消费 `SourceResult` / `SourcePort`；reader-specific dict 仅保留在 adapter 兼容层 |
| Task 32. Tool / MCP operation dispatcher | 3 / 5 | Tool contract + WorkItem adapter | Planned | Hermes native tools、future MCP tool 和 CLI tool handler 通过 `ToolSpec.operation_id -> service` 分发；tool 注册层不直接调用 `CodingOrchestrator.tool_*` |
| Task 33. Skill 零耦合复查 | 14 | Skill contract | Planned | core skill 不包含 Hermes、`/coding`、运行根、ledger、LLM Wiki 或本机命令；Hermes binding skill 只做 host 映射和恢复命令 |
| Task 34. Orchestrator façade 降载 | 0 / 17 | Architecture guard | Planned | `orchestrator.py` 从唯一 large-file watchlist 中逐步退出；第一目标低于 3000 行，后续再收敛到命令 façade 级别 |
| Task 35. Legacy test final cleanup | 15 / 17 | Test governance | Planned | 旧私有 helper / 旧文件形态测试全部有保留、改写或删除记录；剩余测试保护用户行为、contract、安全边界和主流程 |
| Task 36. Release readiness and operating contract | 16 / 17 | 文档合同 + 运行治理 | Planned | README、PLUGIN_USAGE、PLUGIN_PREREQUISITES、project map、component contract 与当前边界一致；完整单测、architecture guard、diff check、敏感扫描和最小 Hermes smoke 形成发布 gate |

## Long-term Iteration Operating Model

后续每一轮都必须先声明“本轮主责域”，再进入实现。阶段不是按文件大小随意切，而是按职责域推进；如果某个文件很大但当前没有清晰职责归属，不做机械拆分。

| 步骤 | 目的 | 必须完成的动作 | 不允许发生的事 |
| --- | --- | --- | --- |
| 1. 定域 | 防止一次改动同时迁多个方向 | 在 `task_plan.md` 增加阶段，写清主责域、协作域和退出标准 | 一轮同时迁 run、source、tool、skill 多条主线 |
| 2. 建基线 | 确认本轮风险和验收点 | 记录目标文件行数、hard code 命中、旧测试绑定、相邻主流程测试 | 只凭感觉判断“文件太大所以拆” |
| 3. 先测 | 让职责边界可验证 | 先补 contract tests；影响用户流程时补 flow tests | 先搬代码再补测试，或只改旧私有 helper 断言 |
| 4. façade 迁移 | 保持现有 `/coding` 行为稳定 | 外部入口不变，orchestrator 只保留 wrapper/callback，业务规则进入主责模块 | 把新业务规则继续写回 orchestrator、controller、presenter 或 adapter |
| 5. 旧耦合处理 | 防止测试阻碍架构演进 | 删除或改写旧测试前，标明等价 contract/main-flow 覆盖 | 删除没有等价覆盖的行为测试 |
| 6. 文档同步 | 让下一轮能接上 | 更新 project map、component contract、conventions、实施计划或技术方案 | 代码边界变了但 canonical docs 仍指向旧模块 |
| 7. 治理回流 | 防止长期回潮 | 运行聚焦测试、必要主流程测试、`architecture_guard.py`、`git diff --check`，必要时更新 guard | 把大文件、hard code 或 host 细节当作临时例外绕过 |

职责归属采用下面的硬规则：

- `gateway_command_controller.py` 只做解析、分类、route metadata 和安全分类，不做 ledger、runner、消息发送或状态推进。
- `run_orchestration_service.py` 可承接 run 生命周期组合规则，但不承接 subprocess、Hermes/Gateway 发送、workspace/git mutation。
- `background_run_notifier.py` 只做后台线程、sender、reply fallback 和 notification record，不做 run result 决策。
- `services/` 承接 task/run/delivery/workitem 用例规则，但不得 import Hermes host、MCP transport、Codex CLI subprocess 或本机路径。
- `runners/`、source reader、MCP adapter、storage adapter 承接外部系统绑定和错误映射，不承接 task 状态决策。
- presenter 和 binding skill 承接用户可见文案和 host 映射，不推进 task/run 状态。

跨切面职责采用下面的执行归属：

| 切面 | 权威归属 | 执行时只允许做的事 | 不允许做的事 |
| --- | --- | --- | --- |
| 工具端 | `ToolSpec` + operation dispatcher | host payload 归一、operation dispatch、response 包装 | 在注册层直接写业务流程、状态推进或 ledger mutation |
| MCP / WorkItem | `WorkItemPort` + `WorkItemService` + MCP adapter | adapter 内 transport/token/allowlist/write gate/audit | core/service 持有 token、拼 JSON-RPC、绕过确认写入 |
| Skill core | core skill contract | 描述 host-agnostic intent、状态口径和恢复策略 | 写 Hermes 命令、运行根、ledger、LLM Wiki 本地路径 |
| Hermes binding skill | host binding skill | 将 core intent 映射到 `/coding`、Hermes CLI、`lark-cli` 恢复命令 | 沉淀通用业务规则或状态机 |
| Source / Lark | `SourcePort` + source adapter | 生成 `SourceResult`、保留可恢复读取命令 | 让业务层消费 reader-specific dict |
| Storage / Knowledge | repository + `KnowledgePort` | schema/query/wiki layout 封装 | application service 手写 SQL 或知道 wiki layout |
| 大文件 / hard code | `architecture_guard.py` + watchlist | 发现、阻断或登记边界漂移 | 将 host command、env、token key 或超阈值文件当临时例外 |

## Current Progress

| 阶段 | 职责边界 | 状态 | 验证 |
| --- | --- | --- | --- |
| Task 1 | 正式设计文档和实施计划 | Done | 文档已落地到 `docs/plans/` |
| Task 2 | `RuntimeConfig` / `ToolConfig` 配置边界 | Done | `tests.test_config_contract` |
| Task 3 | `ToolSpec` 工具规格合同与 Hermes 注册瘦身 | Done | `tests.test_tool_specs`、`tests.test_plugin_registration` |
| Task 4 | `ports.py` 端口合同 | Done | `tests.test_ports_contract` |
| Task 5 | `WorkItemService` 飞书 Project 工作项服务 | Done | `tests.test_workitem_service`、Project MCP / intake 回归 |
| Task 6 | `TaskService` task 创建、source indexing、状态 payload 服务 | Done | `tests.test_task_service`、`tests.test_orchestrator_tools`、`tests.test_orchestrator_run_flow` |
| Task 7 | `RunService` plan/implementation/QA/merge-test 生命周期 | Done | 已新增 `tests.test_run_service`；已迁移启动 blocker、实现前置条件、mode 标签、timeout/running phase 和结果状态映射；runner 执行副作用仍由 orchestrator façade 编排；完整单测 `479 tests OK` |
| Task 8 | `StatusPolicy` 状态策略与回写策略 | Done | 新增 `coding_orchestration/status_policy.py` 和 `tests.test_status_policy`；已迁移 report 状态详情、known gaps、runner_failed、implementation_not_landed 和 verification limitations 判定；完整单测 `483 tests OK` |
| Task 9 | Prompt Builder 模板拆分 | Done | 新增 `coding_orchestration/prompts/run_instructions.py`、`prompts/source_block.py` 和 `tests.test_prompt_templates`；`PromptBuilder` 只组合模板，完整单测 `488 tests OK` |
| Task 10 | Codex Runner internals 拆分 | Done | 新增 `coding_orchestration/runners/codex_command.py`、`runners/codex_process.py`、`runners/codex_report.py`、`runners/codex_report_loader.py`、`runners/codex_report_writer.py`、`runners/codex_artifacts.py`、`tests.test_codex_command`、`tests.test_codex_process`、`tests.test_codex_report`、`tests.test_codex_report_loader`、`tests.test_codex_report_writer` 和 `tests.test_codex_artifacts`；`CodexCliRunner` 已成为 runner façade，command/process/report policy/report loader/report writer/artifact 均委托到独立模块；完整单测 `510 tests OK` |
| Task 11 | Skill core 与 Hermes binding 拆分 | Done | 新增 core skill 与 Hermes binding contract；`tests.test_plugin_registration` 通过，完整单测 `512 tests OK` |
| Task 12 | 旧测试清理 | In Progress | 已删除 status policy、Codex report façade 和 report schema 旧私有 helper 测试；等价覆盖迁移到 `tests/test_status_policy.py`、`tests/test_codex_report.py`、`tests/test_codex_report_writer.py`、`tests/test_codex_report_schema.py`，真实 run path 测试保留；完整单测 `512 tests OK` |
| Task 13 | 文档同步 | Done | `docs/project-map.md`、`docs/component-contract.md`、`docs/conventions.md` 已记录当前解耦边界；本轮无新增用户可见命令语义，不改 README/Usage；`tests.test_docs_and_install_entry` 通过 |
| Task 14 | 最终验证 | Done | 完整单测 `512 tests OK`；主流程关键测试、敏感值扫描、大文件和 hard code 热点已复查，剩余 Delivery 副作用迁移、Storage/Source/治理 follow-up 不作为已完成项 |
| Task 15 | DeliveryService 副作用编排迁移 | Done | 已新增 `ChildTaskSpec`、`MaterializationPlan`、`MaterializationResult`、`RunNextDecision`、`DeliveryStatusProjection`；`orchestrator._materialize_execution_tasks()` 只保留 ledger callback 绑定，`command_coding_status --delivery` 和 `command_coding_run --next` 使用 DeliveryService projection/decision；完整单测 `530 tests OK` |
| Task 16 | Storage / Knowledge 拆分 | Done | 已新增 `coding_orchestration/storage/schema.py`、`storage/repositories.py`、`storage/task_repository.py`、`storage/run_repository.py`、`storage/artifact_repository.py`、`storage/binding_repository.py`、`storage/common.py`、`knowledge_adapter.py`、`tests/test_storage_schema.py`、`tests/test_storage_repositories.py` 和 `tests/test_knowledge_adapter.py`；`TaskLedger` 委托 schema 与 task/run/artifact/binding repositories，`storage/repositories.py` 只保留兼容 re-export，`RunSummaryWriter` 委托 `KnowledgePort`；聚焦测试 `17 tests OK`，完整单测 `537 tests OK` |
| Task 17 | Source adapter 拆分 | In Progress | 已新增 `coding_orchestration/source_links.py`、`source_recovery.py`、`source_work_item_context.py`、`feishu_document_reader.py`、`feishu_work_item_reader.py`、`ports.SourceResult`、`tests/test_source_links.py`、`tests/test_source_recovery.py`、`tests/test_source_work_item_context.py`、`tests/test_feishu_document_reader.py` 和 `tests/test_feishu_work_item_reader.py`；Feishu/Meegle URL identity parsing、deferred recovery payload、CLI command shape、Feishu Docx/Wiki document reader、Feishu Project work item gateway/OpenAPI env reader、Feishu/Meegle payload 归一化已迁出；`TaskService` source indexing/repair helper 已复用 source adapter 合同，不再内联 URL 正则或 source command shape；`SourceResolver.resolve_source_result()` 统一输出 `SourceResult`，`resolve_source()` 仅保留兼容 context，orchestrator source tool / source preflight 读取已优先消费统一结果；聚焦测试 `42 tests OK` |
| Task 18 | 大文件与 hard code 治理 | Done | 已新增并收紧 `scripts/architecture_guard.py` 和 `tests/test_architecture_guard.py`；guard 默认扫描 `coding_orchestration/`、`scripts/`、`tests/`，新增超 1000 行 Python 文件、core/service/tool 层新增 host command/env/subprocess/token key hard code、真实 token 模式会失败；已清除 service/tool hard-code watchlist、`storage/repositories.py`、`project_knowledge_initializer.py` 和 `tests/test_codex_cli_runner.py` 大文件 watch，现有 watchlist 仅为 `orchestrator.py`；聚焦测试 `6 tests OK` |
| Task 19 | 测试套件模块化 | Done | 已新增 `tests/orchestrator_flow_fixtures.py`、delivery/source/QA/completion/cancel/merge-test/plan-run/implementation/command-run/bugfix writeback/gateway/status flow 测试文件；`tests/test_orchestrator_run_flow.py` 从 10005 行降至 226 行。已删除 `tests/test_codex_cli_runner.py`，拆为 `test_codex_cli_command_facade.py`、`test_codex_cli_process_facade.py`、`test_codex_cli_report_facade.py`、`test_codex_cli_report_failure_facade.py` 和 `codex_runner_fixtures.py`，新文件均低于 600 行；`architecture_guard.py` 不再 watch 测试大文件 |
| Task 20 | Presentation presenter 拆分 | Done | 已新增 `coding_orchestration/task_list_presenter.py`、`coding_orchestration/run_completion_presenter.py`、`tests/test_task_list_presenter.py` 和 `tests/test_run_completion_presenter.py`；`CodingOrchestrator._format_task_list()`、`_task_project_label()`、`_task_description_label()`、`_format_*completion_message()`、`_completion_*()` 等方法保留兼容 wrapper 并委托 presenter；新增 presenter tests `6 tests OK`，相关 flow tests `27 tests OK`，完整单测 `572 tests OK`，`architecture_guard.py` 通过，`orchestrator.py` 从 6534 行降至 6334 行 |
| Task 21 | Status presenter 拆分 | Done | 已新增 `coding_orchestration/task_status_presenter.py` 和 `tests/test_task_status_presenter.py`；`CodingOrchestrator._format_task_status_details()`、`_kanban_sync_status_display()`、`_completion_notification_status_display()`、`_latest_qa_run()`、`_read_report_json()` 和 `_qa_health_score_from_report_path()` 保留兼容 wrapper 并委托 presenter；新增/相邻 status tests `8 tests OK`，完整单测 `574 tests OK`，`orchestrator.py` 从 6334 行降至 6244 行 |
| Task 22 | Gateway rewrite presenter 拆分 | Done | 已新增 `coding_orchestration/gateway_rewrite_presenter.py` 和 `tests/test_gateway_rewrite_presenter.py`；`CodingOrchestrator._rewrite_confirmation_message()`、`_rewrite_needs_human_confirmation_message()`、`_rewrite_rejection_user_text()` 和 `_rewrite_handoff_to_hermes_message()` 保留兼容 wrapper/上下文收集并委托 presenter；新增/相邻 gateway rewrite tests `23 tests OK`，`orchestrator.py` 从 6244 行降至 6171 行 |
| Task 23 | Run start presenter 拆分 | Done | 已新增 `coding_orchestration/run_start_presenter.py` 和 `tests/test_run_start_presenter.py`；`CodingOrchestrator._implementation_started_message()`、`_qa_started_message()`、`_implementation_blocked_before_plan_ready_message()`、`_plan_only_started_message()`、`_plan_only_already_running_message()`、`_cannot_start_run_message()` 和 `_active_run_already_running_message()` 保留兼容 wrapper 并委托 presenter；新增/相邻 run start tests `33 tests OK`，`orchestrator.py` 从 6171 行降至 6131 行 |
| Task 24 | Feedback presenter 拆分 | Done | 已新增 `coding_orchestration/feedback_presenter.py` 和 `tests/test_feedback_presenter.py`；`CodingOrchestrator._missing_feedback_media_message()`、`_plan_feedback_received_message()`、`_blocked_plan_feedback_received_message()`、`_requirement_change_received_message()`、`_requirement_change_queued_message()`、`_implementation_feedback_received_message()`、`_runtime_feedback_received_message()`、`_human_clarification_received_message()` 和 `_human_clarification_project_resolved_message()` 保留兼容 wrapper 并委托 presenter；新增/相邻 feedback tests `29 tests OK`，`orchestrator.py` 从 6131 行降至 6095 行 |
| Task 25 | Merge-test presenter 拆分 | Done | 已新增 `coding_orchestration/merge_test_presenter.py` 和 `tests/test_merge_test_presenter.py`；prepare ready/invalid status、merge-test blocker、blocked risk confirmation、release note、fallback evidence、QA risk confirmation 和 started message 迁出 presenter；`CodingOrchestrator` 保留兼容 wrapper 和 readiness/状态流控制；新增/相邻 merge-test tests `37 tests OK`，`orchestrator.py` 从 6095 行降至 6056 行 |
| Task 26 | Background run notifier 拆分 | Done | 已新增 `coding_orchestration/background_run_notifier.py` 和 `tests/test_background_run_notifier.py`；后台线程启动、统一失败通知文案、gateway/adapter sender 调度、reply fallback 和 completion notification record 构造迁出 notifier；`CodingOrchestrator._run_*_and_notify()` 保留回调入口并继续控制 `start_run()`、等待完成、状态失败 transition 和 merge-test pending action；新增 notifier tests `7 tests OK`，相邻后台通知流程 `27 tests OK`，完整单测 `598 tests OK`，`orchestrator.py` 从 6056 行降至 6003 行 |
| Task 27 | Gateway binding service 拆分 | Done | 已新增 `coding_orchestration/gateway_binding_service.py` 和 `tests/test_gateway_binding_service.py`；event source、chat/user binding key、active task stale cleanup、session lookup、coding mode、active project、pending rewrite/action 和 pending action confirmation record 迁出 binding service；`CodingOrchestrator` 保留 wrapper 并继续控制确认后命令执行、cancelled gate、active project 应用和 rewrite 语义；新增 binding tests `8 tests OK`，相邻 gateway flow `49 tests OK`，完整单测 `606 tests OK`，`orchestrator.py` 从 6003 行降至 5843 行 |
| Task 28 | Workspace / Git / Diff checkpoint service | Done | 已新增 `coding_orchestration/workspace_checkpoint_service.py`、`coding_orchestration/run_manifest_service.py`、`tests/test_workspace_checkpoint_service.py` 和 `tests/test_run_manifest_service.py`；implementation workspace 复用/创建、source branch/base branch、QA artifact 收集、clean-tree checkpoint、git HEAD、diff guard QA artifact 过滤、run-manifest 基础字段、artifact record、Codex attach/resume 展示命令、manifest session metadata 字段投影、controlled bypass 权限 profile、source elevated plan 权限判断已迁出，`CodingOrchestrator` 保留兼容 wrapper、runner 启动、状态映射和风险注入；新增 run manifest service tests `11 tests OK`，manifest/session 相关 flow tests `38 tests OK`，Codex command/workspace 相邻 tests `27 tests OK`，`orchestrator.py` 从 5843 行降至 5600 行 |
| Task 29 | Command / Gateway controller 瘦身 | In Progress | 已新增 `coding_orchestration/gateway_command_controller.py`、`gateway_command_executor.py`、`gateway_pending_action_executor.py`、`gateway_active_context.py`、`tests/test_gateway_command_controller.py`、`tests/test_gateway_command_executor.py`、`tests/test_gateway_pending_action_executor.py` 和 `tests/test_gateway_active_context.py`；显式 `/coding` / `/commands` 解析、`/coding` 命令归一化、project 子命令映射、命令 route plan、handler key、reply mode、task id 来源策略、merge-test 参数解析、rewrite canonical command、确认/取消词分类、rewrite 风险确认、plugin-generated message 过滤、Gateway event dedupe key/cache、授权探测、custom route 分发、pending action 确认/取消、latest human_required fallback、确认后显式命令续接和 active project 应用到 task 的回填已迁出；`CodingOrchestrator` 已按 reply mode 集中处理 help/list/project/use/status/complete/cancel/restore/delete 和 diagnostic immediate reply，并委托 custom route executor、pending action executor 与 active context helper；active context/project/run 相邻 flow tests `25 tests OK`，`orchestrator.py` 当前为 5212 行 |
| Task 30 | Run orchestration service 闭环 | Complete | 已新增 `coding_orchestration/run_orchestration_service.py`、`run_background_orchestration.py`、`run_failure_report_projection.py`、`run_report_refinement_projection.py`、`run_diff_guard_service.py`、`run_dispatch_service.py`、`run_status_transition_service.py`、`run_evidence_observation_service.py`、`run_start_selection_projection.py`、`run_session_projection.py`、`run_session_writeback_service.py`、`run_prompt_projection.py`、`run_context_artifact_service.py`、`run_start_artifact_service.py`、`run_manifest_artifact_service.py`、`run_manifest_session_writeback_service.py`、`run_stderr_artifact_service.py`、`run_report_artifact_service.py`、`run_summary_artifact_service.py`、`run_ledger_projection.py`、`run_ledger_writeback_service.py`、`run_summary_projection.py`、`run_summary_writeback_service.py`、`run_artifact_paths.py`、`run_project_writeback_service.py`、`run_completion_writeback_service.py`、`run_reconcile_writeback_service.py` 及对应 contract tests；后台 orchestration、failure/refinement/start/session/prompt projection、run diff guard observation、runner dispatch、run status transition、run evidence observation、run manifest session metadata host writeback、run artifact 文件写入、run report/summary artifact 读写、run report summary excerpt、execution policy artifact 读取、run artifact path contract、completion/report/project writeback payload、Project writeback host gate/callback、summary writer host callback、start_run 与 active run reconcile 的 artifact / agent_run / merge-test record 写回 payload 聚合、run ledger host callback、run session host callback、completed run 与 active run reconcile 的 run summary writer payload 聚合、fresh completed run 写回协调和 active run reconcile 写回协调已迁出 orchestrator。`run_completion_writeback_service.py` 和 `run_reconcile_writeback_service.py` 分别负责 fresh completed 与 active reconcile 的完成态写回协调；后续大文件治理、hard code 清理和 Hermes/Skill 深度解耦进入 Task 31+ / Task 18/20 长期治理。当前行数：`orchestrator.py` 4658 行，`run_reconcile_writeback_service.py` 137 行 |

Task 30 历史补充：`run_checkpoint_preparation_service.py` 已新增为 run lifecycle host service，负责 QA / merge-test checkpoint preparation callback 选择、调用和 manifest update payload 构造；它不承担 checkpoint kind/target branch 选择、不写 manifest 文件、不处理 implementation dirty-check 后置写回、不启动 runner、不推进状态。
Task 30 历史补充：`run_implementation_checkpoint_service.py` 已新增为 run lifecycle host service，负责 implementation dirty 后置 checkpoint 生成和 manifest artifact writeback callback 接线；它不承担 dirty observation、blocked report refinement、状态 transition、ledger writeback、summary/project writeback 或 runner 调度。
Task 30 历史补充：`run_manifest_session_writeback_service.py` 已新增为 run lifecycle host service，负责 runner session metadata 到 run manifest 的 host callback 接线；它不承担 session id 来源探测、stdout 解析、task session ledger update、summary/project writeback、状态推进或 runner 调度。
Task 30 历史补充：`run_completion_writeback_service.py` 已新增为 run lifecycle host service，负责 fresh completed run writeback coordinator；它不承担 runner dispatch、diff guard、QA evidence、implementation dirty-check、checkpoint 准备、manifest session metadata 或 active run reconcile。
Task 30 历史补充：`run_reconcile_writeback_service.py` 已新增为 run lifecycle host service，负责 active run reconcile writeback coordinator；它不承担 runner dispatch、diff guard、QA evidence、implementation dirty-check、checkpoint 准备、manifest session metadata、fresh completed run 或 Project/WorkItem writeback。

## Task 1: Add Architecture Contract Documents

**Files:**
- Create: `docs/plans/2026-06-16-decoupled-architecture-design.md`
- Create: `docs/plans/2026-06-16-decoupled-architecture-implementation.md`

**Step 1: Verify design document exists**

Run:

```bash
rtk test -f docs/plans/2026-06-16-decoupled-architecture-design.md
```

Expected: exit code 0.

**Step 2: Verify implementation plan exists**

Run:

```bash
rtk test -f docs/plans/2026-06-16-decoupled-architecture-implementation.md
```

Expected: exit code 0.

**Step 3: Review for forbidden secrets**

Run:

```bash
rtk rg -n "MCP_USER_TOKEN=[A-Za-z0-9_./+=-]{20,}|Bearer [A-Za-z0-9._-]{20,}|FEISHU_APP_SECRET=[A-Za-z0-9_./+=-]{20,}|CODEX_CLI_COMMAND=/Users/[A-Za-z0-9._/-]{8,}" docs/plans/2026-06-16-decoupled-architecture-design.md docs/plans/2026-06-16-decoupled-architecture-implementation.md
```

Expected: no real token or machine-specific secret. Placeholder names are acceptable.

## Task 2: Introduce Runtime Config Boundary

**Files:**
- Create: `coding_orchestration/config.py`
- Test: `tests/test_config_contract.py`

**Step 1: Write failing tests**

Create `tests/test_config_contract.py`:

```python
import unittest
from pathlib import Path

from coding_orchestration.config import RuntimeConfig, ToolConfig


class RuntimeConfigContractTest(unittest.TestCase):
    def test_default_runtime_config_preserves_existing_paths(self):
        config = RuntimeConfig.default(home=Path("/home/tester"))

        self.assertEqual(config.hermes_home, Path("/home/tester/.hermes"))
        self.assertEqual(config.runtime_root, Path("/home/tester/.hermes/coding-orchestration"))
        self.assertEqual(config.run_root, Path("/home/tester/.hermes/coding-orchestration/runs"))
        self.assertEqual(config.workspace_root, Path("/home/tester/.hermes/coding-orchestration/workspaces"))

    def test_tool_config_preserves_existing_defaults(self):
        config = ToolConfig.default()

        self.assertEqual(config.lark_cli_command, ("rtk", "lark-cli"))
        self.assertEqual(config.feishu_project_domain, "https://project.feishu.cn")
        self.assertEqual(config.feishu_project_mcp_command, ("npx", "-y", "@lark-project/mcp"))
```

**Step 2: Run test to verify it fails**

Run:

```bash
rtk proxy python3 -m unittest tests.test_config_contract -v
```

Expected: FAIL because `coding_orchestration.config` does not exist.

**Step 3: Implement config dataclasses**

Create `coding_orchestration/config.py` with frozen dataclasses:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeConfig:
    hermes_home: Path
    runtime_root: Path
    run_root: Path
    workspace_root: Path

    @classmethod
    def default(cls, home: Path | None = None) -> "RuntimeConfig":
        root_home = home or Path.home()
        hermes_home = root_home / ".hermes"
        runtime_root = hermes_home / "coding-orchestration"
        return cls(
            hermes_home=hermes_home,
            runtime_root=runtime_root,
            run_root=runtime_root / "runs",
            workspace_root=runtime_root / "workspaces",
        )


@dataclass(frozen=True)
class ToolConfig:
    lark_cli_command: tuple[str, ...] = ("rtk", "lark-cli")
    feishu_project_domain: str = "https://project.feishu.cn"
    feishu_project_mcp_command: tuple[str, ...] = ("npx", "-y", "@lark-project/mcp")
    feishu_project_mcp_token_env: str = "MCP_USER_TOKEN"

    @classmethod
    def default(cls) -> "ToolConfig":
        return cls()
```

**Step 4: Run test to verify it passes**

Run:

```bash
rtk proxy python3 -m unittest tests.test_config_contract -v
```

Expected: PASS.

## Task 3: Introduce ToolSpec Contract

**Files:**
- Create: `coding_orchestration/tool_specs.py`
- Modify: `coding_orchestration/plugin_tools.py`
- Test: `tests/test_tool_specs.py`
- Test: `tests/test_plugin_registration.py`

**Step 1: Write failing ToolSpec tests**

Create `tests/test_tool_specs.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run:

```bash
rtk proxy python3 -m unittest tests.test_tool_specs -v
```

Expected: FAIL because `tool_specs.py` does not exist.

**Step 3: Create ToolSpec module**

Move schema definitions out of `plugin_tools.py` into `tool_specs.py`. Keep names and schemas unchanged. Add:

```python
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    operation_id: str
    safety_level: str = "read_write"
```

`coding_tool_specs()` returns all existing tool specs.

**Step 4: Refactor plugin_tools registration**

`register_coding_tools()` should iterate over `coding_tool_specs()` and map `operation_id` to existing orchestrator methods through a small local dispatcher. This preserves behavior while removing schema hard code from host adapter.

**Step 5: Run focused tests**

Run:

```bash
rtk proxy python3 -m unittest tests.test_tool_specs tests.test_plugin_registration -v
```

Expected: PASS.

## Task 4: Introduce Ports Contract

**Files:**
- Create: `coding_orchestration/ports.py`
- Test: `tests/test_ports_contract.py`

**Step 1: Write failing tests**

Create `tests/test_ports_contract.py`:

```python
import unittest

from coding_orchestration.ports import WorkItemPort, RunnerPort, LedgerPort


class PortsContractTest(unittest.TestCase):
    def test_ports_are_runtime_checkable_protocols(self):
        self.assertTrue(getattr(WorkItemPort, "_is_protocol", False))
        self.assertTrue(getattr(RunnerPort, "_is_protocol", False))
        self.assertTrue(getattr(LedgerPort, "_is_protocol", False))
```

**Step 2: Run test to verify it fails**

Run:

```bash
rtk proxy python3 -m unittest tests.test_ports_contract -v
```

Expected: FAIL because `ports.py` does not exist.

**Step 3: Implement Protocol definitions**

Create minimal `typing.Protocol` contracts for:

- `RunnerPort`
- `SourcePort`
- `WorkItemPort`
- `LedgerPort`
- `KnowledgePort`
- `NotifierPort`
- `RuntimePort`

Do not migrate behavior yet.

**Step 4: Run test to verify it passes**

Run:

```bash
rtk proxy python3 -m unittest tests.test_ports_contract -v
```

Expected: PASS.

## Task 5: Extract Project WorkItem Service

**Files:**
- Create: `coding_orchestration/services/__init__.py`
- Create: `coding_orchestration/services/workitem_service.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_workitem_service.py`
- Update: existing MCP-related tests if they assert private orchestrator details.

**Step 1: Write service tests**

Cover:

- search delegates to `WorkItemPort.search`.
- create requires explicit confirmation.
- transition requires explicit confirmation.
- result redaction stays adapter responsibility.

**Step 2: Implement minimal service**

Move logic from `tool_project_workitem_search`, `tool_project_workitem_create`, `tool_project_state_transition`, and WBS helpers into `WorkItemService`.

**Step 3: Keep orchestrator façade**

Existing `tool_project_*` methods remain, but delegate to `self.workitem_service`.

**Step 4: Run focused tests**

Run:

```bash
rtk proxy python3 -m unittest tests.test_workitem_service tests.test_orchestrator_tools tests.test_feishu_project_mcp -v
```

Expected: PASS.

## Task 6: Extract Task Service

**Files:**
- Create: `coding_orchestration/services/task_service.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_task_service.py`
- Update: `tests/test_orchestrator_tools.py`

**Step 1: Write service tests**

Cover:

- empty requirement returns validation error.
- project/source/runner args are normalized.
- source URL indexing is delegated.
- created task response remains compatible.

**Step 2: Move task create/status continuation logic**

Start with `tool_task_create`, `tool_task_status`, and command-level task create helpers. Keep `command_coding_task()` as façade.

**Step 3: Run focused tests**

Run:

```bash
rtk proxy python3 -m unittest tests.test_task_service tests.test_orchestrator_tools tests.test_orchestrator_run_flow -v
```

Expected: PASS.

## Task 7: Extract Run Service

**Files:**
- Create: `coding_orchestration/services/run_service.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_run_service.py`
- Update: `tests/test_orchestrator_run_flow.py`

**Step 1: Write service tests**

Cover:

- plan-only run prepares context and runner manifest.
- implementation requires plan-ready state.
- QA and merge-test keep current gate behavior.
- report status maps to task state through state policy.

**Step 2: Move run lifecycle methods**

Move run start/collect/status mapping logic in small slices. Keep background thread entrypoints in Hermes adapter or orchestrator façade until `RuntimePort` is ready.

**Step 3: Run focused tests**

Run:

```bash
rtk proxy python3 -m unittest tests.test_run_service tests.test_orchestrator_run_flow tests.test_codex_cli_command_facade tests.test_codex_cli_process_facade tests.test_codex_cli_report_facade tests.test_codex_cli_report_failure_facade -v
```

Expected: PASS.

## Task 8: Extract Status Policy

**Files:**
- Create: `coding_orchestration/status_policy.py`
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `coding_orchestration/prompt_builder.py`
- Test: `tests/test_status_policy.py`

**Step 1: Write tests**

Cover:

- runner status to task status mapping.
- known gaps status detail.
- implementation-not-landed handling.
- merge-test readiness status.

**Step 2: Move status string decisions**

Move scattered status detail and failure type decisions from orchestrator into `status_policy.py`.

**Step 3: Run focused tests**

Run:

```bash
rtk proxy python3 -m unittest tests.test_status_policy tests.test_orchestrator_run_flow tests.test_report_contract -v
```

Expected: PASS.

## Task 9: Split Prompt Builder Templates

**Files:**
- Create: `coding_orchestration/prompts/__init__.py`
- Create: `coding_orchestration/prompts/run_instructions.py`
- Create: `coding_orchestration/prompts/source_block.py`
- Modify: `coding_orchestration/prompt_builder.py`
- Test: `tests/test_prompt_builder.py` or existing prompt tests.

**Step 1: Add tests around current prompt output**

Pin key requirements, not full giant strings:

- plan-only says no file modification.
- external source includes `lark_cli_command`.
- implementation requires commit/report fields.
- merge-test says no deploy.

**Step 2: Extract templates**

Move mode-specific text into prompt modules. `PromptBuilder` becomes composition only.

**Step 3: Run prompt tests**

Run:

```bash
rtk proxy python3 -m unittest tests.test_prompt_builder -v
```

Expected: PASS. If no test exists, create one and run it.

## Task 10: Split Codex Runner Internals

**Files:**
- Create: `coding_orchestration/runners/codex_command.py`
- Create: `coding_orchestration/runners/codex_process.py`
- Create: `coding_orchestration/runners/codex_report.py`
- Create: `coding_orchestration/runners/codex_report_loader.py`
- Create: `coding_orchestration/runners/codex_report_writer.py`
- Create: `coding_orchestration/runners/codex_artifacts.py`
- Modify: `coding_orchestration/runners/codex_cli.py`
- Test: `tests/test_codex_command.py`
- Test: `tests/test_codex_process.py`
- Test: `tests/test_codex_report.py`
- Test: `tests/test_codex_report_loader.py`
- Test: `tests/test_codex_report_writer.py`
- Test: `tests/test_codex_artifacts.py`
- Test: `tests/test_codex_cli_command_facade.py`
- Test: `tests/test_codex_cli_process_facade.py`
- Test: `tests/test_codex_cli_report_facade.py`
- Test: `tests/test_codex_cli_report_failure_facade.py`

**Step 1: Pin existing behavior with tests**

Focus on command construction, structured report loading, incomplete report fallback, artifact collection.

**Step 2: Extract one component at a time**

Start with command builder, then report loader, then artifact collector.

**Step 3: Run runner tests**

Run:

```bash
rtk proxy python3 -m unittest tests.test_codex_cli_command_facade tests.test_codex_cli_process_facade tests.test_codex_cli_report_facade tests.test_codex_cli_report_failure_facade -v
```

Expected: PASS.

**Progress log**

- Command builder split：新增 `runners/codex_command.py`，集中维护 read-only plan-only command、controlled bypass、resume command、manifest `resume_session_id` / `dangerous_bypass` 读取；`CodexCliRunner.build_command()` 保持兼容并委托该模块。新增 `tests/test_codex_command.py`，runner façade 覆盖后续归属 `tests/test_codex_cli_command_facade.py`。
- Process runner split：新增 `runners/codex_process.py`，集中维护 `subprocess.Popen`、process group cancel、timeout handling、process_start_failed fallback 和 timing manifest 写入；`CodexCliRunner.run_subprocess()` / `cancel()` 保留兼容 façade。新增 `tests/test_codex_process.py`，runner façade 覆盖后续归属 `tests/test_codex_cli_process_facade.py`。
- Report policy split：新增 `runners/codex_report.py`，集中维护 semantic report 字段归一化、report status details、strict contract field ordering、verification limitation shape、fallback limitation reason、stdout runner failure 识别和 thread id 解析；`CodexCliRunner` 的旧静态 helper 保持兼容 façade。新增 `tests/test_codex_report.py`，runner report façade 覆盖后续归属 `tests/test_codex_cli_report_facade.py` 和 `tests/test_codex_cli_report_failure_facade.py`。
- Report loader split：新增 `runners/codex_report_loader.py`，集中维护 `report.json` 读取、schema required fields gate、semantic completeness、admission gate 和 fallback 分支选择；fallback/report 写入 builder 暂由 callbacks 连接 `CodexCliRunner` 兼容方法。新增 `tests/test_codex_report_loader.py`。
- Report writer split：新增 `runners/codex_report_writer.py`，集中维护 fallback report、incomplete/admission rejected report、report contract 补齐、summary 写入和 operator log compact 触发；`CodexCliRunner` 的同名方法保留兼容 façade。新增 `tests/test_codex_report_writer.py`。
- Artifact collector split：新增 `runners/codex_artifacts.py`，集中维护 `ArtifactSet` 路径合同，`CodexCliRunner.collect_artifacts()` 保留兼容 façade。新增 `tests/test_codex_artifacts.py`。

## Task 11: Split Skill Core and Hermes Binding

**Files:**
- Create: `coding_orchestration/skills/coding-operator-core/SKILL.md`
- Modify: `coding_orchestration/skills/hermes-coding-operator/SKILL.md`
- Create: `coding_orchestration/skills/coding-health-core/SKILL.md`
- Modify: `coding_orchestration/skills/hermes-coding-health-check/SKILL.md`
- Modify: `coding_orchestration/__init__.py`
- Test: `tests/test_plugin_registration.py`

**Step 1: Add registration test**

Assert Hermes-specific skills remain registered and core skill files exist.

**Step 2: Move host-agnostic rules to core skills**

Core skills must not mention `/coding`, Hermes Gateway, Task Ledger path, or LLM Wiki path.

**Step 3: Keep Hermes binding skills**

Hermes skills reference host commands and map core intent to `/coding`.

**Step 4: Run registration tests**

Run:

```bash
rtk proxy python3 -m unittest tests.test_plugin_registration -v
```

Expected: PASS.

## Task 12: Test Cleanup

**Files:**
- Modify: old tests only after replacement coverage exists.
- Add: `docs/plans/2026-06-16-decoupled-architecture-test-cleanup.md` if cleanup spans multiple commits.

**Step 1: Classify old tests**

Create a list:

- Keep: behavior/safety/contract tests.
- Rewrite: private orchestrator implementation tests.
- Delete: tests asserting obsolete helper names or old file placement only.

**Step 2: Delete only replaced tests**

Before deleting a test, identify the new test that covers the same user value.

**Step 3: Run full tests**

Run:

```bash
rtk proxy python3 -m unittest discover -s tests -v
```

Expected: PASS.

**Cleanup log**

- Status policy cleanup：删除 `tests/test_orchestrator_run_flow.py` 中直接绑定 `CodingOrchestrator._normalize_implementation_run_status()` 的旧实现形态测试；新增/扩展 `tests/test_status_policy.py` 覆盖 landed commit gate、control failure、blocked explicit not landed、report incomplete、QA 非 implementation mode 和 verification limitations。保留真实 `start_run()` path 测试，完整单测 `483 tests OK`。
- Codex report façade cleanup：删除 `tests/test_codex_cli_runner.py` 中直接绑定 `CodexCliRunner._report_status_details()` 的旧 façade 测试；等价覆盖在 `tests/test_codex_report.py::test_report_status_details_keeps_report_incomplete_blocked`。将 fallback report 精确字段断言迁移到 `tests/test_codex_report_writer.py::test_fallback_report_matches_report_contract_fields`，避免继续通过 `CodingOrchestrator._write_report_schema()` 校验 runner writer。
- Report schema cleanup：新增 `coding_orchestration/runners/codex_report_schema.py` 和 `tests/test_codex_report_schema.py`，把 `report.schema.json` 合同从 `CodingOrchestrator._write_report_schema()` 迁出；删除 `tests/test_orchestrator_run_flow.py` 中三条直接绑定 `_write_report_schema()` 的旧私有 helper 测试，`CodingOrchestrator._write_report_schema()` 仅保留兼容 façade。
- 2026-06-16 cleanup verification：`rtk proxy python3 -m unittest tests.test_codex_report_schema tests.test_codex_report_writer tests.test_codex_cli_command_facade tests.test_codex_cli_process_facade tests.test_codex_cli_report_facade tests.test_codex_cli_report_failure_facade tests.test_orchestrator_run_flow -v` 通过；完整单测 `rtk proxy python3 -m unittest discover -s tests -v` 通过，`512 tests OK`。

## Task 13: Documentation Update

**Files:**
- Modify: `docs/component-contract.md`
- Modify: `docs/project-map.md`
- Modify: `docs/conventions.md`
- Modify: `README.md`
- Modify: `PLUGIN_USAGE.md`

**Step 1: Update component contract**

Add new entries for config, ToolSpec, ports, services, status policy and adapters.

**Step 2: Update project map**

Reflect the new target architecture and compatibility façade.

**Step 3: Update usage docs only for user-visible changes**

Do not describe internal refactors as user requirements.

**Step 4: Run docs-related tests**

Run:

```bash
rtk proxy python3 -m unittest tests.test_docs_and_install_entry -v
```

Expected: PASS.

## Task 14: Final Verification

**Files:**
- No planned file edits.

**Current audit evidence**

- 完整单测：`rtk proxy python3 -m unittest discover -s tests -v` 通过，`581 tests OK`。
- 文档入口测试：`rtk proxy python3 -m unittest tests.test_docs_and_install_entry -v` 通过。
- 主流程证据：`test_gateway_standard_task_flow_reaches_done`、`test_command_coding_implement_requires_plan_ready_then_starts_implementation`、`test_qa_run_reuses_task_session_collects_qa_artifacts_and_marks_ready`、`test_coding_merge_test_resumes_codex_session_and_marks_merged_test`、`test_coding_complete_marks_merged_test_task_done`、`test_plan_only_blocks_if_runner_modifies_project_files`、`test_project_workitem_create_requires_explicit_write_confirmation`、`test_secret_is_redacted_from_logs` 均在完整单测中通过。
- 大文件热点：`coding_orchestration/orchestrator.py` 6131 行。doctor/preflight/source-resolve 文案已迁出到 `doctor_presenter.py` 335 行，Gateway rewrite 文案已迁出到 `gateway_rewrite_presenter.py` 107 行，run start 文案已迁出到 `run_start_presenter.py` 83 行，task list 文案已迁出到 `task_list_presenter.py` 63 行，task status 文案已迁出到 `task_status_presenter.py` 132 行，run completion 文案已迁出到 `run_completion_presenter.py` 231 行。`project_knowledge_initializer.py` 已从 796 行拆为 30 行兼容入口，扫描/分类/技术栈推断归属 `project_knowledge_inventory.py` 413 行，LLM Wiki 文档生成归属 `project_knowledge_documents.py` 378 行。`storage/repositories.py` 已从 619 行拆为 25 行兼容入口，具体 SQL mutation 分布到 `task_repository.py` 318 行、`binding_repository.py` 143 行、`run_repository.py` 56 行、`artifact_repository.py` 58 行和 `common.py` 68 行。`tests/test_orchestrator_run_flow.py` 已降至 226 行，runner façade 测试已从 `tests/test_codex_cli_runner.py` 936 行拆为 `test_codex_cli_command_facade.py` 221 行、`test_codex_cli_process_facade.py` 156 行、`test_codex_cli_report_facade.py` 253 行、`test_codex_cli_report_failure_facade.py` 314 行和 `codex_runner_fixtures.py` 32 行；所有测试文件均低于 600 行 watch limit。
- hard code 热点治理：service/tool 层的 `/coding`、`lark-cli` 和 MCP token key hard-code watchlist 已清除；相关 host 文案留在 orchestrator/presentation，MCP token key 和 config path 由 Feishu Project MCP adapter 暴露配置引用，source command shape 由 source adapter 合同维护。真实 secret 扫描无命中。
- Architecture guard：`rtk proxy python3 scripts/architecture_guard.py` 当前默认通过，watchlist 只剩 `orchestrator.py`；新增 core/service/tool hard code 或真实 token 模式会作为 fail 阻断。
- DeliveryService progress：新增 `coding_orchestration/services/delivery_service.py` 和 `tests/test_delivery_service.py`，已迁移 decomposition session、breakdown approval、materialization planning、ledger callback 编排、delivery status projection、run-next decision、requirement rollup status/phase 规则；`orchestrator.py` 保留命令 façade、ledger callback 绑定、runner 调用和用户消息渲染。
- 已确认未完成 follow-up：剩余业务层继续迁移到只消费 `SourcePort` / `SourceResult`，并继续拆 `orchestrator.py` 大文件，不应把整体目标标记为完成。

**Step 1: Run full test suite**

Run:

```bash
rtk proxy python3 -m unittest discover -s tests -v
```

Expected: PASS.

**Step 2: Verify no forbidden secrets**

Run:

```bash
rtk rg -n "MCP_USER_TOKEN=[A-Za-z0-9_./+=-]{20,}|Bearer [A-Za-z0-9._-]{20,}|FEISHU_APP_SECRET=[A-Za-z0-9_./+=-]{20,}" .
```

Expected: no real secret values.

**Step 3: Check large-file progress**

Run:

```bash
rtk wc -l coding_orchestration/orchestrator.py coding_orchestration/runners/codex_cli.py coding_orchestration/project_knowledge_initializer.py coding_orchestration/project_knowledge_inventory.py coding_orchestration/project_knowledge_documents.py coding_orchestration/ledger.py coding_orchestration/feishu_project_reader.py
```

Expected: orchestrator and other large files decrease over the migration. Final target: no business module over 1000 lines unless documented.

**Step 4: Main flow audit**

Use tests and code inspection to prove:

- task create still starts plan-only.
- implementation still requires plan-ready.
- QA remains manually triggered.
- merge-test remains manually triggered and does not deploy.
- complete remains human-driven.
- plan-only remains read-only.
- Feishu MCP writes require confirmation and do not expose tokens.

## Task 15: Complete DeliveryService Side-Effect Migration

**Files:**
- Modify: `coding_orchestration/services/delivery_service.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_delivery_service.py`
- Test: `tests/test_orchestrator_run_flow.py`

**Step 1: Add contract tests for materialization planning**

Cover:

- confirmed breakdown rows become deterministic child task specs.
- parent task id, source payload, project, runner, branch policy and dependency metadata are preserved.
- invalid or empty breakdown rows return a service-level error instead of partially writing children.

Run:

```bash
rtk proxy python3 -m unittest tests.test_delivery_service -v
```

Expected: FAIL until the new planner exists.

**Step 2: Extract pure child-spec construction**

Move the pure part of `_materialize_execution_tasks()` into `DeliveryService`. Do not move ledger writes in the same step unless the service already has a port-shaped dependency for them.

**Step 3: Move ledger-backed materialize orchestration behind a port seam**

Introduce only the minimum ledger-facing method needed by `DeliveryService`, or pass existing ledger callbacks explicitly during migration. `CodingOrchestrator.command_coding_materialize()` remains the user-facing façade.

**Step 4: Move delivery status and run-next decisions**

Move command-level delivery status projection and `run --next` child selection into `DeliveryService`, while keeping Hermes message rendering in orchestrator/presentation code.

**Step 5: Run focused and full tests**

Run:

```bash
rtk proxy python3 -m unittest tests.test_delivery_service tests.test_orchestrator_run_flow -v
rtk proxy python3 -m unittest discover -s tests -v
```

Expected: PASS.

**Progress log**

- Materialization planning split：新增 `ChildTaskSpec`、`MaterializationPlan` 和 `DeliveryService.materialization_plan()`，集中维护 delivery unit 校验、child task id 计划、依赖映射、source payload、project path、runner provider、source branch / branch policy 和 child task session。`CodingOrchestrator._materialize_execution_tasks()` 保留兼容 façade 和 ledger 写入，命令入口在 plan errors 时拒绝部分写入。新增 `tests.test_delivery_service` 中 materialization planning contract 和 `tests.test_orchestrator_run_flow::test_materialize_invalid_breakdown_does_not_create_partial_children`。验证：`rtk proxy python3 -m unittest tests.test_delivery_service tests.test_orchestrator_run_flow -v` 通过；完整单测 `rtk proxy python3 -m unittest discover -s tests -v` 通过，`530 tests OK`。
- Materialize orchestration split：新增 `MaterializationResult` 和 `DeliveryService.materialize_execution_tasks()`，通过 `create_child_task` / `get_child_task` callback seam 注入 ledger 写入能力；existing children 短路、plan error 拒绝写入和 created children 收集由服务统一维护。`CodingOrchestrator._materialize_execution_tasks()` 只绑定 `TaskLedger` callbacks 并转换错误。
- Delivery command decision split：新增 `RunNextDecision` 和 `DeliveryStatusProjection`，`command_coding_status --delivery` 委托 `DeliveryService.status_projection()`，`command_coding_run --next` 委托 `DeliveryService.run_next_decision()`；orchestrator 只保留 task 查找、runner 调用、rollup 触发和中文消息渲染。验证：`rtk proxy python3 -m unittest tests.test_delivery_service tests.test_orchestrator_run_flow -v` 通过；完整单测继续作为 Task 15 完成 gate。

## Task 16: Split Storage and Knowledge Adapters

**Files:**
- Modify: `coding_orchestration/ledger.py`
- Create: `coding_orchestration/storage/`
- Modify: `coding_orchestration/llm_wiki_adapter.py`
- Modify: `coding_orchestration/project_knowledge_initializer.py`
- Test: existing ledger / knowledge tests, plus new storage contract tests.

**Step 1: Pin TaskLedger façade behavior**

Add or extend tests for task CRUD, run CRUD, artifact persistence, work item binding, schema migration and backward-compatible public methods.

**Step 2: Extract schema and migration module**

Move table creation and migration logic out of `TaskLedger` into storage-owned functions. `TaskLedger` still calls them.

**Step 3: Extract repositories**

Split task, run, artifact and binding operations into repository classes. Keep `TaskLedger` as compatibility façade until callers migrate to `LedgerPort`.

**Step 4: Extract KnowledgePort adapter**

Move LLM Wiki layout and run summary persistence behind a knowledge adapter. Application services should receive project/run knowledge as data, not file paths.

**Step 5: Run tests**

Run:

```bash
rtk proxy python3 -m unittest discover -s tests -v
```

Expected: PASS, with no service importing storage implementation details.

**Progress log**

- Schema / migration split：新增 `coding_orchestration/storage/schema.py` 和 `tests/test_storage_schema.py`，将 `tasks`、`active_task_bindings`、`project_workitem_bindings` 的 table/index creation 与 legacy column migration 从 `TaskLedger._init_db()` 迁出。`TaskLedger` 仅委托 `initialize_ledger_schema()`，继续保留 CRUD/binding 兼容 façade。验证：`rtk proxy python3 -m unittest tests.test_storage_schema tests.test_ledger_wiki_orchestrator tests.test_project_workitem_binding -v` 通过，`14 tests OK`。
- Repository split：新增 `coding_orchestration/storage/repositories.py` 和 `tests/test_storage_repositories.py`，拆出 `TaskRepository`、`RunRepository`、`ArtifactRepository`、`BindingRepository`。`TaskLedger` 保留公开方法兼容 façade，只负责连接生命周期、schema 初始化和 repository 委托，不再承载 task/run/artifact/binding SQL mutation。验证：`rtk proxy python3 -m unittest tests.test_storage_repositories tests.test_storage_schema tests.test_ledger_wiki_orchestrator tests.test_project_workitem_binding -v` 通过，`17 tests OK`。
- Repository file split：将 `storage/repositories.py` 进一步收缩为 25 行兼容 re-export，新增 `storage/task_repository.py`、`storage/run_repository.py`、`storage/artifact_repository.py`、`storage/binding_repository.py` 和 `storage/common.py`，按 task/run/artifact/binding 归属 SQL mutation 和 row mapper。验证：`rtk proxy python3 -m unittest tests.test_storage_repositories tests.test_storage_schema tests.test_ledger_wiki_orchestrator tests.test_project_workitem_binding -v` 通过，`17 tests OK`；`rtk proxy python3 scripts/architecture_guard.py` 通过，`storage/repositories.py` 不再出现在大文件 watchlist。
- KnowledgePort adapter split：新增 `coding_orchestration/knowledge_adapter.py` 和 `tests/test_knowledge_adapter.py`，`LocalKnowledgeAdapter` 作为本地 LLM Wiki 的 `KnowledgePort` 实现，封装 search/read/upsert/source-task lookup/delete、kind lookup 和 run summary 文档写入。`RunSummaryWriter` 不再拼接 LLM Wiki document，改为委托 `KnowledgePort.write_run_summary()`；`ProjectKnowledgeResolver` 和 `ProjectKnowledgeInitializer` 改为依赖 `KnowledgePort`。验证：`rtk proxy python3 -m unittest tests.test_knowledge_adapter tests.test_ports_contract tests.test_router_prompt_summary tests.test_project_knowledge_resolver tests.test_project_knowledge_initializer tests.test_orchestrator_config -v` 通过，`28 tests OK`。
- Project knowledge initializer split：新增 `coding_orchestration/project_knowledge_inventory.py` 和 `coding_orchestration/project_knowledge_documents.py`，将仓库扫描、文件分类、敏感路径识别、技术栈/包管理器/验证命令推断迁入 inventory scanner，将 project profile/guidance/architecture/tooling/risk 等 LLM Wiki 文档生成迁入 document builder；`project_knowledge_initializer.py` 收缩为 30 行兼容 façade，并继续 re-export `ProjectKnowledgeInventory`。验证：`rtk proxy python3 -m unittest tests.test_project_knowledge_initializer tests.test_project_knowledge_resolver tests.test_orchestrator_config -v` 通过，`8 tests OK`；`rtk proxy python3 scripts/architecture_guard.py` 通过，`project_knowledge_initializer.py` 不再出现在大文件 watchlist。

## Task 17: Split Source Adapters

**Files:**
- Modify: `coding_orchestration/source_resolver.py`
- Modify: `coding_orchestration/feishu_project_reader.py`
- Modify: `coding_orchestration/meegle_reader.py`
- Create: `coding_orchestration/feishu_work_item_reader.py`
- Create: `coding_orchestration/source_work_item_context.py`
- Create: source adapter helper modules as needed.
- Test: `tests/test_source_resolver.py`
- Test: `tests/test_feishu_project_reader.py`
- Test: `tests/test_feishu_document_reader.py`
- Test: `tests/test_feishu_work_item_reader.py`
- Test: `tests/test_source_work_item_context.py`

**Step 1: Add parser/error contract tests**

Cover Feishu Project URL parsing, Docx/Wiki source parsing, Meegle fallback, permission errors and deferred `lark_cli_command` recovery payloads.

**Step 2: Extract URL and identity parsing**

Move URL parsing into a pure module with no network, MCP or `lark-cli` access.

**Step 3: Extract readers and error mapper**

Separate document reading, project work item reading and user-facing recovery mapping. Business code should receive a normalized source result.

**Step 4: Keep prompt behavior compatible**

Verify prompt source blocks still expose recoverable read commands without guessing external content.

**Step 5: Run focused tests**

Run:

```bash
rtk proxy python3 -m unittest tests.test_source_resolver tests.test_feishu_project_reader tests.test_prompt_templates -v
```

Expected: PASS.

**Progress log**

- URL / identity parser split：新增 `coding_orchestration/source_links.py` 和 `tests/test_source_links.py`，将 Feishu Project work item、Feishu Docx/Wiki 和 Meegle URL/identity 解析从 `FeishuProjectReader` / `MeegleReader` 迁到无网络、无 CLI、无 MCP 的纯模块。reader 上原 `extract_first_*` 静态方法保留兼容 façade。验证：`rtk proxy python3 -m unittest tests.test_source_links tests.test_feishu_project_reader tests.test_source_resolver tests.test_prompt_templates -v` 通过，`31 tests OK`。
- Recovery mapper split：新增 `coding_orchestration/source_recovery.py` 和 `tests/test_source_recovery.py`，将 Feishu Docx/Wiki deferred source resolution payload、`lark_cli_command` / auth verify command shape、proxy recovery action、Meegle CLI command 和失败上下文从 reader 迁到无网络、无 subprocess 的纯模块。`FeishuProjectReader` / `MeegleReader` 上原私有 command/failure helper 保留兼容 façade。验证：`rtk proxy python3 -m unittest tests.test_source_links tests.test_source_recovery tests.test_feishu_project_reader tests.test_source_resolver tests.test_prompt_templates -v` 通过，`35 tests OK`。
- Feishu document reader split：新增 `coding_orchestration/feishu_document_reader.py` 和 `tests/test_feishu_document_reader.py`，将 Feishu Docx/Wiki gateway 读取、`lark-cli docs +fetch`、auth refresh retry、文档 payload 归一化和文档失败恢复从 `FeishuProjectReader` 迁出。`FeishuProjectReader` 保留 document reader 注入点和原私有文档 helper 的兼容 façade，仍负责 Project work item 读取和顶层来源路由。验证：`rtk proxy python3 -m unittest tests.test_feishu_document_reader tests.test_feishu_project_reader tests.test_source_resolver tests.test_prompt_templates -v` 通过，`28 tests OK`；`feishu_project_reader.py` 从 551 行降至 361 行。
- Feishu work item reader split：新增 `coding_orchestration/feishu_work_item_reader.py` 和 `tests/test_feishu_work_item_reader.py`，将 Feishu Project work item gateway 读取、OpenAPI env 读取、plugin token header、payload 归一化和失败上下文从 `FeishuProjectReader` 迁出。`FeishuProjectReader` 保留 work item reader 注入点和原私有 work item helper 的兼容 façade，只负责 Project/文档来源路由。验证：`rtk proxy python3 -m unittest tests.test_feishu_work_item_reader tests.test_feishu_document_reader tests.test_feishu_project_reader tests.test_source_resolver tests.test_prompt_templates -v` 通过，`32 tests OK`；`feishu_project_reader.py` 从 361 行降至 188 行，`feishu_work_item_reader.py` 为 237 行。
- Work item common normalizer split：新增 `coding_orchestration/source_work_item_context.py` 和 `tests/test_source_work_item_context.py`，将 Feishu Project 与 Meegle 共用的 payload data 选择、raw_fields 提取、summary shape、success context 和 API failed context coercion 从具体 reader 迁出。`FeishuWorkItemReader` 只保留 gateway/OpenAPI env 读取，`MeegleReader` 只保留 gateway/CLI 读取。验证：`rtk proxy python3 -m unittest tests.test_source_work_item_context tests.test_feishu_work_item_reader tests.test_feishu_project_reader tests.test_meegle_reader tests.test_source_resolver tests.test_prompt_templates -v` 通过，`37 tests OK`；`feishu_work_item_reader.py` 从 237 行降至 150 行，`meegle_reader.py` 从 239 行降至 151 行。
- SourceResult contract split：在 `coding_orchestration/ports.py` 新增 `SourceResult`，`SourcePort` 新增 `resolve_source_result()`；`SourceResolver` 统一把 reader context 包装为稳定 `ok/status/context/source_type/url/title/error/recovery_action`，旧 `resolve_source()` 只保留兼容 dict context。`CodingOrchestrator.tool_source_resolve()`、source 创建读取和 run 前 deferred source refresh 已优先消费 `resolve_source_result()`，`services/task_utils.source_status_from_context()` 改为委托 `SourceResult`，避免 source 状态规则重复。验证：`rtk proxy python3 -m unittest tests.test_ports_contract tests.test_source_resolver tests.test_source_work_item_context tests.test_task_service tests.test_orchestrator_tools tests.test_source_flow tests.test_source_plan_flow -v` 通过，`54 tests OK`。

## Task 18: Add Architecture Guard Checks

**Files:**
- Create: `scripts/architecture_guard.py` or equivalent lightweight test helper.
- Test: `tests/test_architecture_guard.py`
- Modify: `docs/conventions.md`
- Modify: `docs/component-contract.md`

**Step 1: Define guard thresholds**

Encode the current policy:

- business module over 600 lines enters watchlist.
- business module over 1000 lines fails unless explicitly exempted.
- service/core modules must not contain `Path.home()`, `os.getenv()`, `subprocess`, `/coding`, `MCP_USER_TOKEN`, raw Lark command strings or Hermes skill absolute paths.
- adapter modules may contain host binding strings, but must not contain real token values.

**Step 2: Add tests for guard output**

Use fixture paths or a small synthetic directory so the guard behavior is deterministic.

**Step 3: Run guard and tests**

Run:

```bash
rtk proxy python3 -m unittest tests.test_architecture_guard -v
rtk proxy python3 -m unittest discover -s tests -v
```

Expected: PASS. Guard findings should be actionable and should not fail on known documented follow-up until the threshold is promoted.

**Progress log**

- Architecture guard baseline：新增 `scripts/architecture_guard.py` 和 `tests/test_architecture_guard.py`。默认模式扫描 `coding_orchestration/`、`scripts/`、`tests/`；新增超 1000 行 Python 文件、core/service 层新增 `Path.home()`、`os.getenv()`、`subprocess`、`/coding` / `lark-cli`、token/env key hard code 和真实 token 模式会失败；已知遗留大文件和 service 文案债务输出 watchlist。验证：`rtk proxy python3 -m unittest tests.test_architecture_guard -v` 通过，`6 tests OK`；`rtk proxy python3 scripts/architecture_guard.py` 通过，输出 10 条 watchlist、0 条 fail。
- Boundary debt tightening：将 `coding_orchestration/services/workitem_service.py` 的 MCP 配置缺失提示改为消费 Feishu Project MCP adapter 暴露的 `config_file_hint` / `token_config_ref`，将 `tool_specs.py` 的 source preflight 描述改为 host-agnostic，将 `TaskService` / `task_utils.py` 的 `/coding` 用法文案移到 orchestrator façade，将 source indexing/repair 中的 URL 解析和 source command shape 改为复用 `source_links.py` / `source_recovery.py`。随后清空 `architecture_guard.py` 的 boundary debt 白名单，旧 service hard-code 回归会 fail。验证：`rtk proxy python3 -m unittest tests.test_architecture_guard -v` 通过，`6 tests OK`；`rtk proxy python3 scripts/architecture_guard.py` 通过，watchlist 从 hard-code + 大文件收紧为仅大文件。
- Project knowledge large-file retirement：`project_knowledge_initializer.py` 已拆分为 30 行 façade、413 行 inventory scanner 和 378 行 document builder。
- Codex runner façade test split：删除 `tests/test_codex_cli_runner.py`，新增 `tests/codex_runner_fixtures.py`、`tests/test_codex_cli_command_facade.py`、`tests/test_codex_cli_process_facade.py`、`tests/test_codex_cli_report_facade.py` 和 `tests/test_codex_cli_report_failure_facade.py`，分别承载 command/process/report/failure façade flow；底层 command/process/report/writer/artifact 规则继续由 `tests/test_codex_command.py`、`tests/test_codex_process.py`、`tests/test_codex_report*.py` 和 `tests/test_codex_artifacts.py` 维护。验证：`rtk proxy python3 -m unittest tests.test_codex_cli_command_facade tests.test_codex_cli_process_facade tests.test_codex_cli_report_facade tests.test_codex_cli_report_failure_facade tests.test_codex_command tests.test_codex_process tests.test_codex_report tests.test_codex_report_loader tests.test_codex_report_writer tests.test_codex_artifacts tests.test_codex_report_schema -v` 通过，`57 tests OK`；`rtk proxy python3 scripts/architecture_guard.py` 通过，watchlist 只剩 `orchestrator.py`。
- Doctor presenter split：新增 `coding_orchestration/doctor_presenter.py`，将 `/coding doctor`、`lark-preflight`、`project-mcp-preflight` 和 `source-resolve` 的用户可见文案从 `orchestrator.py` 迁出。orchestrator 保留状态收集、adapter preflight 调用和兼容 façade；MCP token 配置引用继续来自 `FeishuProjectMcpConfig`。验证：`rtk proxy python3 -m unittest tests.test_coding_cli tests.test_gateway_command_group_flow tests.test_docs_and_install_entry -v` 通过，`24 tests OK`；`rtk proxy python3 scripts/architecture_guard.py` 通过，`orchestrator.py` 从 6765 行降至 6534 行。
- Presentation presenter split：新增 `coding_orchestration/task_list_presenter.py` 和 `coding_orchestration/run_completion_presenter.py`，将 `/coding list` 任务摘要、项目/描述标签、plan/implementation/QA/merge-test/stale run completion 消息、summary/risk/next_actions fallback 从 `orchestrator.py` 迁出。orchestrator 保留 `_format_task_list()`、`_format_*completion_message()` 和 `_completion_*()` 兼容 wrapper。验证：`rtk proxy python3 -m unittest tests.test_task_list_presenter tests.test_run_completion_presenter -v` 通过，`6 tests OK`；`rtk proxy python3 -m unittest tests.test_completion_flow tests.test_plan_run_flow tests.test_implementation_result_flow tests.test_gateway_safety_lifecycle_flow -v` 通过，`27 tests OK`；`rtk proxy python3 -m unittest discover -s tests -v` 通过，`572 tests OK`；`rtk proxy python3 scripts/architecture_guard.py` 通过，`orchestrator.py` 从 6534 行降至 6334 行。
- Status presenter split：新增 `coding_orchestration/task_status_presenter.py`，将 `/coding status` 任务状态详情、Kanban 同步、完成回传、QA report、QA health score 和 known gaps 展示从 `orchestrator.py` 迁出。orchestrator 保留 `_format_task_status_details()`、`_kanban_sync_status_display()`、`_completion_notification_status_display()`、`_latest_qa_run()`、`_read_report_json()` 和 `_qa_health_score_from_report_path()` 兼容 wrapper。验证：`rtk proxy python3 -m unittest tests.test_task_status_presenter tests.test_status_reconcile_flow -v` 通过，`8 tests OK`；`rtk proxy python3 -m py_compile coding_orchestration/orchestrator.py coding_orchestration/task_status_presenter.py tests/test_task_status_presenter.py` 通过；`rtk proxy python3 -m unittest discover -s tests -v` 通过，`574 tests OK`；`orchestrator.py` 从 6334 行降至 6244 行。
- Gateway rewrite presenter split：新增 `coding_orchestration/gateway_rewrite_presenter.py`，将 Coding Mode rewrite 确认、低置信度补充和 handoff 用户可见文案从 `orchestrator.py` 迁出。orchestrator 保留 `_rewrite_*` 兼容 wrapper 和 `_coding_rewrite_context()` 上下文收集。验证：`rtk proxy python3 -m unittest tests.test_gateway_rewrite_presenter tests.test_gateway_rewrite_flow tests.test_gateway_pending_confirmation_flow tests.test_gateway_natural_language_command_flow -v` 通过，`23 tests OK`；`rtk proxy python3 -m py_compile coding_orchestration/orchestrator.py coding_orchestration/gateway_rewrite_presenter.py tests/test_gateway_rewrite_presenter.py` 通过；`orchestrator.py` 从 6244 行降至 6171 行。
- Run start presenter split：新增 `coding_orchestration/run_start_presenter.py`，将 plan-only/implementation/QA 启动 ACK、active run 重复启动和 cannot-start 恢复提示从 `orchestrator.py` 迁出。orchestrator 保留对应 `_...message()` 兼容 wrapper；`RunService` 继续负责状态 blocker、timeout 和状态映射。验证：`rtk proxy python3 -m unittest tests.test_run_start_presenter tests.test_command_run_flow tests.test_plan_run_flow tests.test_qa_flow tests.test_run_service -v` 通过，`33 tests OK`；`rtk proxy python3 -m py_compile coding_orchestration/orchestrator.py coding_orchestration/run_start_presenter.py tests/test_run_start_presenter.py` 通过；`orchestrator.py` 从 6171 行降至 6131 行。
- Background run notifier split：新增 `coding_orchestration/background_run_notifier.py`，将后台线程启动、sender 调度、reply fallback、失败通知模板和 completion notification record 从 `orchestrator.py` 迁出。orchestrator 保留 `_run_*_and_notify()` 回调入口，并继续负责 `start_run()`、等待完成、失败状态 transition 和 merge-test pending action。验证：`rtk proxy python3 -m unittest tests.test_background_run_notifier -v` 通过，`7 tests OK`；`rtk proxy python3 -m unittest tests.test_plan_run_flow tests.test_qa_flow tests.test_merge_test_qa_gate_flow tests.test_command_run_flow -v` 通过，`27 tests OK`；`rtk proxy python3 -m py_compile coding_orchestration/orchestrator.py coding_orchestration/background_run_notifier.py tests/test_background_run_notifier.py` 通过；`rtk proxy python3 -m unittest discover -s tests -v` 通过，`598 tests OK`；`rtk proxy python3 scripts/architecture_guard.py` 通过，仅 watch `orchestrator.py: 6003 lines`；`orchestrator.py` 从 6056 行降至 6003 行。
- Gateway binding service split：新增 `coding_orchestration/gateway_binding_service.py`，将 event source、binding key、active task、coding mode、active project、pending rewrite/action 和 pending action confirmation record 从 `orchestrator.py` 迁出。orchestrator 保留 wrapper，并继续负责确认后命令执行、cancelled task gate、active project 应用和 rewrite 语义。验证：`rtk proxy python3 -m unittest tests.test_gateway_binding_service -v` 通过，`8 tests OK`；`rtk proxy python3 -m unittest tests.test_gateway_binding_service tests.test_gateway_coding_mode_lifecycle_flow tests.test_gateway_pending_confirmation_flow tests.test_gateway_project_task_flow tests.test_gateway_task_control_flow tests.test_gateway_rewrite_flow tests.test_gateway_natural_language_command_flow -v` 通过，`49 tests OK`；`rtk proxy python3 -m py_compile coding_orchestration/orchestrator.py coding_orchestration/gateway_binding_service.py tests/test_gateway_binding_service.py` 通过；`rtk proxy python3 -m unittest discover -s tests -v` 通过，`606 tests OK`；`rtk proxy python3 scripts/architecture_guard.py` 通过，仅 watch `orchestrator.py: 5843 lines`；`orchestrator.py` 从 6003 行降至 5843 行。
- Workspace checkpoint service split：新增 `coding_orchestration/workspace_checkpoint_service.py`，将 implementation workspace 复用/创建、source branch/base branch、QA artifact 收集、clean-tree checkpoint、git HEAD 和 diff guard QA artifact 过滤从 `orchestrator.py` 迁出。orchestrator 保留兼容 wrapper，并继续负责 runner 启动、状态映射和风险注入。验证：`rtk proxy python3 -m unittest tests.test_workspace_checkpoint_service -v` 通过，`12 tests OK`；`rtk proxy python3 -m unittest tests.test_workspace_checkpoint_service tests.test_implementation_workspace_flow tests.test_qa_flow tests.test_merge_test_qa_gate_flow -v` 通过，`32 tests OK`；`rtk proxy python3 -m py_compile coding_orchestration/orchestrator.py coding_orchestration/workspace_checkpoint_service.py tests/test_workspace_checkpoint_service.py tests/test_implementation_workspace_flow.py` 通过；`orchestrator.py` 从 5843 行降至 5732 行。
- Run manifest service split：新增 `coding_orchestration/run_manifest_service.py` 和 `tests/test_run_manifest_service.py`，将 run-manifest 基础字段、artifact record、Codex attach/resume 展示命令、controlled bypass 权限 profile、source elevated plan 权限判断和 manifest session metadata 字段投影从 `orchestrator.py` 迁出。orchestrator 保留兼容 wrapper，并继续负责上下文收集、runner 启动、状态映射和风险注入。验证：`rtk proxy python3 -m unittest tests.test_run_manifest_service -v` 通过，`8 tests OK`；`rtk proxy python3 -m unittest tests.test_run_manifest_service tests.test_orchestrator_run_flow tests.test_implementation_session_flow tests.test_plan_run_flow tests.test_source_plan_flow tests.test_qa_flow -v` 通过，`39 tests OK`；`rtk proxy python3 -m unittest tests.test_codex_command tests.test_codex_cli_command_facade tests.test_workspace_checkpoint_service -v` 通过，`27 tests OK`；`orchestrator.py` 从 5732 行降至 5600 行。
- Gateway command controller simple dispatch：`gateway_command_controller.py` 的 route metadata 扩展为 command family、handler key、reply mode 和 task id source，`CodingOrchestrator._handle_explicit_gateway_command()` 改为先按 reply mode 处理 help/list/project/use/status/complete/cancel/restore/delete 与 diagnostic immediate reply；复杂 task/run/implement/QA/prepare/merge-test 副作用仍留在 orchestrator。验证：controller + gateway group tests `24 tests OK`；相邻 gateway/project/task/feedback/run/merge-test flow tests `73 tests OK`；完整单测 `639 tests OK`；`architecture_guard.py` 通过，仅 watch `orchestrator.py: 5457 lines`。
- Gateway command executor split：新增 `coding_orchestration/gateway_command_executor.py` 和 `tests/test_gateway_command_executor.py`，将 task creation、feedback、plan run、delivery、implementation、QA、prepare merge-test 和 merge-test 的 Gateway custom route 分发从 `_handle_explicit_gateway_command()` 迁出。orchestrator 只保留 route parsing、pending action 清理、immediate dispatch 和 executor 委托；executor 仍通过 orchestrator façade/callback 调用现有 ledger/runner/status 副作用。验证：executor + controller + 相邻 gateway/project/task/feedback/run/merge-test flow tests `76 tests OK`；`orchestrator.py` 从 5457 行降至 5283 行。
- Gateway pending action executor split：新增 `coding_orchestration/gateway_pending_action_executor.py` 和 `tests/test_gateway_pending_action_executor.py`，将 pending action 确认/取消、latest human_required merge-test fallback、取消任务 gate 和确认后显式命令续接从 `_handle_pending_action_gateway_message()` 迁出。orchestrator 保留兼容 wrapper，并继续通过 façade/callback 提供 binding、ledger、消息回复和显式命令执行入口。验证：`rtk proxy python3 -m py_compile coding_orchestration/orchestrator.py coding_orchestration/gateway_pending_action_executor.py tests/test_gateway_pending_action_executor.py` 通过；`rtk proxy python3 -m unittest tests.test_gateway_pending_action_executor tests.test_gateway_pending_confirmation_flow tests.test_cancel_restore_flow tests.test_merge_test_blocked_flow tests.test_merge_test_qa_gate_flow tests.test_gateway_rewrite_flow tests.test_gateway_natural_language_command_flow -v` 通过，`46 tests OK`；`orchestrator.py` 从 5283 行降至 5238 行。
- Gateway active context split：新增 `coding_orchestration/gateway_active_context.py` 和 `tests/test_gateway_active_context.py`，将 active project 应用到缺项目 task 的 project context 回填和 human decision 记录从 `_apply_active_project_to_task_if_missing()` 迁出。orchestrator 保留兼容 wrapper；active project binding 存取仍归属 `gateway_binding_service.py`。验证：`rtk proxy python3 -m py_compile coding_orchestration/orchestrator.py coding_orchestration/gateway_active_context.py tests/test_gateway_active_context.py` 通过；`rtk proxy python3 -m unittest tests.test_gateway_active_context tests.test_gateway_project_task_flow tests.test_gateway_natural_language_command_flow tests.test_command_run_flow -v` 通过，`25 tests OK`；`orchestrator.py` 从 5238 行降至 5212 行。
- Run orchestration service first slice：新增 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_service.py`，将后台 queued/running 等待完成、后台启动失败状态收敛和 merge-test `human_required` 转 pending action 从 orchestrator 迁出。orchestrator 保留 `_wait_for_background_run_completion()`、`_mark_background_run_failed()` 和 `_store_pending_action_from_merge_test_result()` 兼容 wrapper，并继续控制 `start_run()`、runner 启动、report 写回和完整 run result 映射。验证：`rtk proxy python3 -m py_compile coding_orchestration/orchestrator.py coding_orchestration/run_orchestration_service.py tests/test_run_orchestration_service.py` 通过；`rtk proxy python3 -m unittest tests.test_run_orchestration_service tests.test_background_run_notifier tests.test_plan_run_flow tests.test_command_run_flow tests.test_qa_flow tests.test_merge_test_qa_gate_flow -v` 通过，`41 tests OK`；`rtk proxy python3 -m unittest discover -s tests -v` 通过，`656 tests OK`；`rtk proxy python3 scripts/architecture_guard.py` 通过，仅 watch `orchestrator.py: 5154 lines`；`orchestrator.py` 从 5212 行降至 5154 行。
- Run orchestration completion projection split：扩展 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_service.py`，将 run completion 后的 task status、task phase、run_still_active 和 report status/task_status 字段投影从 orchestrator 迁出。helper 复用 `RunService.task_status_for_run_result()` 与 `RunService.task_phase_for_run_result()`，保留 merge-test `human_required` 回到 `ready_for_merge_test` 的人工续接语义；orchestrator 继续负责 report 文件写回、ledger transition、artifact/agent_run append 和 session metadata 更新。验证：`rtk proxy python3 -m py_compile coding_orchestration/orchestrator.py coding_orchestration/run_orchestration_service.py tests/test_run_orchestration_service.py` 通过；`rtk proxy python3 -m unittest tests.test_run_orchestration_service tests.test_plan_run_flow tests.test_command_run_flow tests.test_status_reconcile_flow tests.test_qa_flow tests.test_merge_test_basic_flow tests.test_merge_test_qa_gate_flow -v` 通过，`50 tests OK`；`orchestrator.py` 从 5154 行降至 5149 行。
- Run orchestration agent run record split：扩展 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_service.py`，将 agent run record 的纯数据构造从 `CodingOrchestrator.start_run()` 迁出。helper 保持 plan-only 不写 source/target/implementation checkpoint、implementation 保留 source branch/checkpoint、merge-test 写 target branch/stale completion/diff guard 的既有字段合同；orchestrator 继续负责 artifact append、agent_run append、merge record 和 session metadata 更新。验证：`rtk proxy python3 -m py_compile coding_orchestration/orchestrator.py coding_orchestration/run_orchestration_service.py tests/test_run_orchestration_service.py` 通过；`rtk proxy python3 -m unittest tests.test_run_orchestration_service tests.test_plan_run_flow tests.test_command_run_flow tests.test_status_reconcile_flow tests.test_qa_flow tests.test_merge_test_basic_flow tests.test_merge_test_qa_gate_flow -v` 通过，`53 tests OK`；`orchestrator.py` 从 5149 行降至 5143 行。
- Run orchestration runner session update split：扩展 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_service.py`，将 completed/reconciled run 的 runner session update 纯数据构造从 `CodingOrchestrator.start_run()` 和 `_reconcile_completed_active_run()` 迁出。helper 统一维护 completed 时清理 active run、保留可恢复 session、runner_failed 时清空 session、still-running 时不覆盖 active run 字段的合同；orchestrator 继续负责 ledger update、attach command 字符串生成和 summary/writeback。验证：`rtk proxy python3 -m py_compile coding_orchestration/orchestrator.py coding_orchestration/run_orchestration_service.py tests/test_run_orchestration_service.py` 通过；`rtk proxy python3 -m unittest tests.test_run_orchestration_service tests.test_plan_run_flow tests.test_command_run_flow tests.test_status_reconcile_flow tests.test_qa_flow tests.test_merge_test_basic_flow tests.test_merge_test_qa_gate_flow -v` 通过，`56 tests OK`；`orchestrator.py` 从 5143 行降至 5129 行。
- Run orchestration merge-test run record split：扩展 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_service.py`，将 merge-test run record 的纯数据构造从 `CodingOrchestrator.start_run()` 迁出。helper 只生成 `merge_test_run` record，orchestrator 继续负责 stale completion gate、ledger append 和 created_at 时间注入。验证：`rtk proxy python3 -m unittest tests.test_run_orchestration_service -v` 通过，`18 tests OK`；`orchestrator.py` 从 5129 行降至 5127 行。
- Run orchestration start_run result payload split：扩展 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_service.py`，将 `CodingOrchestrator.start_run()` 尾部 final result payload 的纯数据构造迁出。helper 统一维护 `run_status/status/task_status/stale_completion/current_task_status/observed_active_run_id/artifacts/report/project_writeback` 字段合同；orchestrator 继续负责 project writeback、summary 写入、ledger append/update 和 runner/report 副作用。验证：`rtk proxy python3 -m unittest tests.test_run_orchestration_service -v` 通过，`20 tests OK`；相邻 run/status/QA/merge-test flow 通过，`59 tests OK`；完整单测通过，`669 tests OK`；`architecture_guard.py` 仅 watch `orchestrator.py: 5126 lines`。
- Run orchestration project writeback payload split：扩展 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_service.py`，将传给 `CodingOrchestrator._writeback_project_bugfix_completion()` 的 run result payload 纯构造迁出。helper 只维护 `run_id/status/task_status/report` 字段合同；orchestrator 继续决定 stale completion skip、调用 workitem writeback、写 summary 和落 ledger。验证：`rtk proxy python3 -m unittest tests.test_run_orchestration_service -v` 通过，`21 tests OK`；相邻 run/status/QA/merge-test/bugfix flow 通过，`61 tests OK`；完整单测通过，`670 tests OK`；`architecture_guard.py` 仅 watch `orchestrator.py: 5126 lines`。
- Run orchestration completion report payload split：扩展 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_service.py`，新增 `build_completion_report_payload()`，将 completion report 写回前的 `run_status/status/task_status/details/known_gaps` 纯字段投影收敛到 helper；`project_run_completion()` 统一调用该 helper，`CodingOrchestrator._reconcile_completed_active_run()` 改为复用 `project_run_completion()`。orchestrator 继续负责实际 `report.json` 写入、状态 transition、summary、ledger update 和 runner/report 副作用。验证：RED 先出现 2 个预期错误；`rtk proxy python3 -m unittest tests.test_run_orchestration_service -v` 通过，`23 tests OK`；相邻 run/status/QA/merge-test/bugfix flow 通过，`63 tests OK`；完整单测 `672 tests OK`；`architecture_guard.py` 仅 watch `orchestrator.py: 5121 lines`；`orchestrator.py` 从 5126 行降至 5121 行。
- Run orchestration reconciled agent run record split：扩展 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_service.py`，新增 `build_reconciled_agent_run_record()`，将 `_reconcile_completed_active_run()` 中 active run agent run upsert payload 的纯字典构造迁出。helper 负责合并 existing run、report、artifact、changed_files、QA artifact fallback、tested commit fallback 和 diff guard violations；orchestrator 继续负责 `ledger.upsert_agent_run()`、artifact upsert、状态 transition、summary 写入和 runner session update。验证：RED 先出现 1 个预期错误；`rtk proxy python3 -m unittest tests.test_run_orchestration_service -v` 通过，`24 tests OK`；相邻 run/status/QA/merge-test/bugfix flow 通过，`64 tests OK`；完整单测通过，`673 tests OK`；文档/架构测试通过，`17 tests OK`；`architecture_guard.py` 仅 watch `orchestrator.py: 5107 lines`；`git diff --check` 通过；敏感扫描无命中；`orchestrator.py` 从 5121 行降至 5107 行。
- Run orchestration reconcile result payload split：扩展 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_service.py`，新增 `build_reconcile_result_payload()`，将 `_reconcile_completed_active_run()` 尾部返回给调用方的纯 result payload 构造迁出。helper 只维护 `task_id/run_id/mode/status/task_status/artifacts/reconciled` 字段合同；orchestrator 继续负责 `report.json` 写入、状态 transition、artifact/agent_run upsert、summary 写入和 runner session update。验证：RED 先出现 1 个预期错误；`rtk proxy python3 -m unittest tests.test_run_orchestration_service -v` 通过，`25 tests OK`；相邻 run/status/QA/merge-test/bugfix flow 通过，`65 tests OK`；完整单测通过，`674 tests OK`；文档/架构测试通过，`17 tests OK`；`architecture_guard.py` 仅 watch `orchestrator.py: 5106 lines`；`git diff --check` 通过；敏感扫描无命中；`orchestrator.py` 从 5107 行降至 5106 行。
- Run orchestration existing run reconcile rules split：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `run_mode_for_existing_run()` 和 `changed_files_for_existing_run()`，将 `_reconcile_completed_active_run()` 中 existing run 的 mode 推断和 changed files fallback 规则迁出。helper 维护 `report -> run -> runner.active_mode -> runner.last_requested_mode -> plan-only` 的 mode 优先级，以及 `report.modified_files -> run.diff_guard.changed_files` fallback；orchestrator 继续负责 report 写回、状态 transition、artifact/agent_run upsert、summary 写入和 runner session update。验证：RED 先出现 2 个预期错误；`rtk proxy python3 -m unittest tests.test_run_orchestration_service tests.test_run_orchestration_reconcile_rules -v` 通过，`27 tests OK`；相邻 run/status/QA/merge-test/bugfix flow 通过，`67 tests OK`；完整单测通过，`676 tests OK`；文档/架构测试通过，`17 tests OK`；`architecture_guard.py` 仅 watch `orchestrator.py: 5076 lines`；`git diff --check` 通过；敏感扫描无命中；测试治理将新增规则合同拆到 61 行的 `tests/test_run_orchestration_reconcile_rules.py`，避免 `tests/test_run_orchestration_service.py` 超过 600 行 watch limit；`orchestrator.py` 从 5106 行降至 5076 行。
- Run orchestration start_run observation rules split：扩展 `coding_orchestration/run_orchestration_service.py` 并新增 80 行的 `tests/test_run_orchestration_start_rules.py`，将 `CodingOrchestrator.start_run()` 中 runner report 的 `modified_files` / QA artifact / tested commit 观测字段构造，以及 stale completion 的 active run mismatch / cancelled task 判定迁出。helper 只维护纯数据观测规则；orchestrator 继续负责 diff guard、QA artifact 收集、git HEAD 获取、report 写回、状态 transition、artifact/agent_run append、summary 和 project writeback。验证：RED 先出现 4 个预期错误；`rtk proxy python3 -m unittest tests.test_run_orchestration_start_rules tests.test_run_orchestration_service tests.test_run_orchestration_reconcile_rules -v` 通过，`31 tests OK`；相邻 run/status/QA/merge-test/bugfix flow 通过，`71 tests OK`；完整单测通过，`680 tests OK`；文档/架构测试通过，`17 tests OK`；`architecture_guard.py` 仅 watch `orchestrator.py: 5073 lines`；`git diff --check` 通过；`orchestrator.py` 从 5076 行降至 5073 行。
- Run orchestration start_run blocked report rules split：扩展 `coding_orchestration/run_orchestration_service.py` 和 131 行的 `tests/test_run_orchestration_start_rules.py`，新增 `BlockedReportProjection`、`build_diff_guard_blocked_report()` 和 `build_implementation_commit_missing_report()`，将 `CodingOrchestrator.start_run()` 中 diff guard violation 与 implementation commit missing 的 blocked report 纯字段拼装迁出。helper 只维护 `human_required/risks/verification_limitations/next_actions/fallback_evidence` report projection；orchestrator 继续负责 diff guard 收集、workspace dirty 判断、checkpoint、report 写回、状态 transition、artifact/agent_run append、summary 和 project writeback。验证：RED 先出现 2 个预期错误；`rtk proxy python3 -m unittest tests.test_run_orchestration_start_rules tests.test_run_orchestration_service tests.test_run_orchestration_reconcile_rules -v` 通过，`33 tests OK`；相邻 run/status/QA/merge-test/bugfix flow 通过，`73 tests OK`；完整单测通过，`682 tests OK`；文档/架构测试通过，`17 tests OK`；`architecture_guard.py` 仅 watch `orchestrator.py: 5056 lines`；`git diff --check` 通过；敏感扫描无命中；`orchestrator.py` 从 5073 行降至 5056 行。
- Run orchestration plan report session fields split：扩展 `coding_orchestration/run_orchestration_service.py` 和 169 行的 `tests/test_run_orchestration_start_rules.py`，新增 `build_plan_report_session_fields()`，将 `CodingOrchestrator.start_run()` 中 plan-only completion 后写入 `task_session.plan_report` 的字段白名单迁出。helper 只维护 `branch_slug_candidate/execution_policy_decision/user_facing_summary/technical_summary/next_actions` 白名单；orchestrator 继续负责 `ledger.update_task_session()`、manifest/context 消费和 implementation branch 策略。验证：RED 先出现 2 个预期错误；`rtk proxy python3 -m unittest tests.test_run_orchestration_start_rules tests.test_run_orchestration_service tests.test_run_orchestration_reconcile_rules -v` 通过，`35 tests OK`；implementation/status/plan/command 相邻 flow 通过，`27 tests OK`；完整单测 `684 tests OK`；文档/架构测试 `17 tests OK`；`architecture_guard.py` 仅 watch `orchestrator.py: 5049 lines`；`git diff --check` 通过；敏感扫描无命中；`orchestrator.py` 从 5056 行降至 5049 行。
- Run orchestration execution policy decision split：扩展 `coding_orchestration/run_orchestration_service.py` 和 208 行的 `tests/test_run_orchestration_start_rules.py`，新增 `latest_execution_policy_decision()`，将 `CodingOrchestrator.start_run()` 中读取 `task_session.plan_report.execution_policy_decision` 的纯规则迁出。helper 只维护 session shape 容错和 dict 决策返回；orchestrator 继续负责 `control_policy_for_mode()`、timeout 选择、manifest/context 写入、ledger update 和 runner 启动。验证：RED 先出现 2 个预期 AttributeError；`rtk proxy python3 -m unittest tests.test_run_orchestration_start_rules tests.test_run_orchestration_service tests.test_run_orchestration_reconcile_rules -v` 通过，`37 tests OK`；status/plan/command/implementation session 相邻 flow 通过，`28 tests OK`；完整单测 `686 tests OK`；文档/架构测试 `17 tests OK`；`architecture_guard.py` 仅 watch `orchestrator.py: 5044 lines`；`git diff --check` 通过；敏感扫描无命中；`orchestrator.py` 从 5049 行降至 5044 行。
- Run orchestration run diff guard violations split：扩展 `coding_orchestration/run_orchestration_service.py` 和 236 行的 `tests/test_run_orchestration_start_rules.py`，新增 `build_run_diff_guard_violations()`，将 `CodingOrchestrator.start_run()` 中 plan-only run 对 changed files 追加违规说明的纯列表组合规则迁出。helper 只复制并扩展 violations 列表；orchestrator 继续负责 diff snapshot、changed files 收集、allowed/forbidden path 检查、diff summary 写入、blocked report 构造、状态推进和 ledger 更新。验证：RED 先出现 2 个预期 AttributeError；`rtk proxy python3 -m unittest tests.test_run_orchestration_start_rules tests.test_run_orchestration_service tests.test_run_orchestration_reconcile_rules -v` 通过，`39 tests OK`；status/plan/command/implementation session 相邻 flow 通过，`28 tests OK`；完整单测 `688 tests OK`；文档/架构测试 `17 tests OK`；`architecture_guard.py` 仅 watch `orchestrator.py: 5044 lines`；`git diff --check` 通过；敏感扫描无命中；`orchestrator.py` 保持 5044 行，`run_orchestration_service.py` 增至 559 行。
- Run orchestration verification limitations fallback split：扩展 `coding_orchestration/run_orchestration_service.py` 和 271 行的 `tests/test_run_orchestration_start_rules.py`，新增 `ensure_verification_limitations()`，将 `CodingOrchestrator._ensure_verification_limitations()` 中 blocked/partial report 缺少结构化恢复详情时的兜底投影迁出。helper 只维护 report 投影、status details 判定和 stdout/stderr fallback evidence 字符串；orchestrator 继续负责 artifact 路径提供、实际 `report.json` 写入、状态 transition、artifact/agent_run append、summary、ledger 更新和 project writeback。验证：RED 先出现 2 个预期 AttributeError；`rtk proxy python3 -m unittest tests.test_run_orchestration_start_rules -v` 通过，`14 tests OK`；run orchestration 合同通过，`41 tests OK`；plan/status/command/implementation/QA 相邻 flow 通过，`39 tests OK`；完整单测 `690 tests OK`；文档/架构测试 `17 tests OK`；`architecture_guard.py` 仅 watch `orchestrator.py: 5033 lines`；`git diff --check` 通过；敏感扫描无命中；`orchestrator.py` 从 5044 行降至 5033 行，`run_orchestration_service.py` 增至 589 行。
- Run background orchestration split：新增 `coding_orchestration/run_background_orchestration.py` 和 `tests/test_run_background_orchestration.py`，将后台 queued/running 等待完成、后台启动失败状态收敛和 merge-test `human_required` pending action host orchestration 从 `run_orchestration_service.py` 拆出。`run_orchestration_service.py` 回到纯 run projection / payload 组合边界，后台 helper 继续只通过 orchestrator façade 调用 ledger/reconcile/report/binding，不承载 runner subprocess、Gateway 发送或 workspace/git 副作用。验证：RED 先出现 1 个预期 ImportError；`rtk proxy python3 -m unittest tests.test_run_background_orchestration -v` 通过，`7 tests OK`；run orchestration/start/reconcile 合同通过，`34 tests OK`；相邻后台/run/status/QA/merge-test flow 通过，`53 tests OK`；完整单测 `690 tests OK`；文档/架构测试 `17 tests OK`；`architecture_guard.py` 仅 watch `orchestrator.py: 5034 lines`；`git diff --check` 通过；敏感扫描无命中；`run_orchestration_service.py` 从 589 行降至 496 行，`run_background_orchestration.py` 为 99 行。
- Run manifest session metadata projection split：扩展 `coding_orchestration/run_manifest_service.py` 和 `tests/test_run_manifest_service.py`，新增 `build_manifest_session_fields()`，将 `CodingOrchestrator.start_run()` 中初始 resume session 和 runner 完成后 manifest session 字段拼装迁出。helper 维护 `session_id`、`resume_session_id`、Codex attach/resume 展示命令、既有 resume session 保留和可见性策略；orchestrator 继续负责 session id 来源探测、manifest 文件写回、runner 启动和状态映射。验证：RED 先出现 1 个预期 ImportError；`rtk proxy python3 -m unittest tests.test_run_manifest_service -v` 通过，`11 tests OK`；manifest/session 相邻 flow 通过，`38 tests OK`；py_compile 通过；`orchestrator.py` 当前为 5034 行，`run_manifest_service.py` 为 309 行。
- Run orchestration pre-run failure report payload split：扩展 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_start_rules.py`，新增 `RunFailureReportProjection`、`build_runner_failed_report_payload()` 和 `build_checkpoint_failed_report_payload()`，将 `CodingOrchestrator._runner_failed_result()` 与 `_checkpoint_failed_result()` 中 runner 异常、QA/merge-test checkpoint 失败的结构化 report payload 拼装迁出。helper 只维护 summary、stderr、status、risk、verification limitations、QA artifact 空对象和 tested commit 合同；orchestrator 继续负责 artifact 文件写入和 `RunResult` 包装。验证：RED 先出现 2 个预期 AttributeError；`rtk proxy python3 -m unittest tests.test_run_orchestration_start_rules tests.test_run_orchestration_service tests.test_run_orchestration_reconcile_rules -v` 通过，`36 tests OK`；plan/run/QA/merge-test 相邻 flow 通过，`33 tests OK`；文档/架构测试 `17 tests OK`；完整单测 `695 tests OK`；`architecture_guard.py` 仅 watch `orchestrator.py: 4986 lines`；`git diff --check` 通过；敏感扫描无命中；`run_orchestration_service.py` 增至 593 行，下一轮继续增长前应优先拆分或压缩。
- Run failure report projection module split：新增 `coding_orchestration/run_failure_report_projection.py` 和 `tests/test_run_failure_report_projection.py`，将 `RunFailureReportProjection`、`build_runner_failed_report_payload()` 与 `build_checkpoint_failed_report_payload()` 从 `run_orchestration_service.py` 拆到独立 projection module。`run_orchestration_service.py` 保留兼容 re-export，旧调用点和旧 tests 不改名；新模块只维护结构化 failure report payload，不写 artifact、不包装 `RunResult`、不启动 runner。验证：RED 先出现 1 个预期 ImportError；新增 projection tests 与 start rules tests 通过，`18 tests OK`；`py_compile` 通过；`run_orchestration_service.py` 从 593 行降至 500 行，新模块为 104 行，新增测试为 48 行。
- Run report refinement projection split：扩展 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_start_rules.py`，新增 `RunReportRefinement` 与 `refine_run_report_projection()`，将 `CodingOrchestrator.start_run()` 中 observed report 初始 status details、diff guard blocked 优先级、implementation 状态归一和 implementation commit-missing blocked 选择迁出。helper 只维护 report/details/status 投影和是否需要 host 做 implementation dirty-check 的布尔信号；orchestrator 继续负责 session metadata、workspace dirty 检查、checkpoint manifest 写入、`report.json` 写入、状态 transition、artifact/agent_run append、summary 和 project writeback。验证：RED 先出现 3 个预期 AttributeError；start rules 定向测试通过，`19 tests OK`；run orchestration/start/reconcile 合同通过，`41 tests OK`；plan/run/QA/merge-test 相邻 flow 通过，`33 tests OK`；`py_compile` 通过；`orchestrator.py` 从 4986 行降至 4978 行，`run_orchestration_service.py` 增至 561 行，仍低于 600 行 watch 阈值。
- Run report refinement projection module split：新增 `coding_orchestration/run_report_refinement_projection.py` 和 `tests/test_run_report_refinement_projection.py`，将 `BlockedReportProjection`、`RunReportRefinement`、`build_diff_guard_blocked_report()`、`build_implementation_commit_missing_report()` 与 `refine_run_report_projection()` 从 `run_orchestration_service.py` 拆到独立 projection module。`run_orchestration_service.py` 保留兼容 re-export，旧调用点和旧 tests 不改名；新模块只维护 diff guard / implementation commit missing blocked report、status/details refinement 和 implementation dirty-check 信号，不执行 diff guard、不判断 workspace dirty、不写 report、不推进 ledger。验证：RED 先出现 1 个预期 ImportError；新增/相邻 contract 43 tests passed；plan/run/QA/merge-test 相邻 flow 33 tests passed；文档/架构测试 17 tests passed；完整单测 702 tests passed；`architecture_guard.py` 仅 watch `orchestrator.py: 4978 lines`；`git diff --check` 通过；敏感扫描无命中；当前行数为 `run_orchestration_service.py` 438 行、新模块 136 行、新增测试 46 行。
- Run orchestration run start session update split：扩展 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_start_rules.py`，新增 `build_run_start_base_session_update()` 与 `build_run_start_workspace_session_update()`，将 `CodingOrchestrator.start_run()` 中 run 启动前 `project_name`、runner provider/last mode、source branch/base、worktree 和 QA/merge-test resume session payload 拼装迁出。helper 只维护 task session update 字段合同；orchestrator 继续负责 workspace 选择/创建、source branch/base 计算、ledger 写入、manifest/prompt、runner 启动和状态推进。验证：RED 先出现 4 个预期 AttributeError；start rules 23 tests passed；相邻 implementation/session/QA/merge-test/run service 46 tests passed；文档/架构测试 17 tests passed；完整单测 706 tests passed；`architecture_guard.py` 仅 watch `orchestrator.py: 4976 lines`；`git diff --check` 通过；敏感扫描无命中；当前行数为 `orchestrator.py` 4976 行、`run_orchestration_service.py` 475 行、`tests/test_run_orchestration_start_rules.py` 467 行。
- Run orchestration active run session update split：扩展 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_start_rules.py`，新增 `build_active_run_session_update()`，将 `CodingOrchestrator.start_run()` 中 runner 启动前 `runner.active_run_id` / `runner.active_mode` payload 拼装迁出。helper 只维护 active run session update 字段合同；orchestrator 继续负责 ledger 写入、running phase、状态 transition、runner 启动和失败清理。验证：RED 先出现 1 个预期 AttributeError；start rules 24 tests passed；run orchestration/start/reconcile contract 44 tests passed；文档/架构测试 17 tests passed；完整单测 707 tests passed；`architecture_guard.py` 仅 watch `orchestrator.py: 4974 lines`；`git diff --check` 通过；敏感扫描无命中；当前行数为 `orchestrator.py` 4974 行、`run_orchestration_service.py` 488 行、`tests/test_run_orchestration_start_rules.py` 483 行。
- Run orchestration run context source split：扩展 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_start_rules.py`，新增 `run_context_source_for_mode()` 和 context source 常量，将 `CodingOrchestrator.start_run()` 中 `RunMode -> confirmed_context` 选择规则迁出。helper 只维护 implementation 使用 `confirmed_plan`、QA/merge-test 使用 `merge_test_context`、其他模式为空的纯规则；orchestrator 继续负责实际读取 confirmed plan / merge-test context、context artifacts、prompt 构造和 runner 启动。验证：RED 先出现 1 个预期 AttributeError；start rules 25 tests passed；run orchestration/start/reconcile contract 45 tests passed；相邻 plan/command/session/QA/merge-test flow 35 tests passed；文档/架构测试 17 tests passed；完整单测 708 tests passed；`architecture_guard.py` 仅 watch `orchestrator.py: 4974 lines`；`git diff --check` 通过；敏感扫描无命中；当前行数为 `orchestrator.py` 4974 行、`run_orchestration_service.py` 500 行、`tests/test_run_orchestration_start_rules.py` 505 行。
- Run orchestration run checkpoint selection split：扩展 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_start_rules.py`，新增 `run_checkpoint_for_mode()` 和 `run_checkpoint_failed()`，将 `CodingOrchestrator.start_run()` 中 QA/merge-test checkpoint 选择和 failed checkpoint 判定迁出。helper 只维护 mode 到 `qa_checkpoint` / `merge_test_checkpoint` / `None` 的选择，以及只有 dict 且 `status=failed` 才触发 checkpoint failed 的纯规则；orchestrator 继续负责 checkpoint 准备、manifest 写入、checkpoint failure `RunResult` 包装、runner 启动和状态推进。验证：RED 先出现 2 个预期 AttributeError；start rules 27 tests passed；run orchestration/start/reconcile contract 47 tests passed；文档/架构测试 17 tests passed；完整单测 710 tests passed；`architecture_guard.py` 仅 watch `orchestrator.py: 4971 lines`；`git diff --check` 通过；敏感扫描无命中；当前行数为 `orchestrator.py` 4971 行、`run_orchestration_service.py` 517 行、`tests/test_run_orchestration_start_rules.py` 540 行。
- Run orchestration QA evidence observation selection split：扩展 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_start_rules.py`，新增 `run_observes_qa_evidence()`，将 `CodingOrchestrator.start_run()` 中是否收集 QA artifacts/tested commit 的 mode 判断迁出。helper 只维护 QA mode 需要观测 QA evidence、其他 mode 不观测的纯规则；orchestrator 继续负责 `_collect_qa_artifacts()`、`_git_head()`、observed report 构造、report 写回和 ledger 状态推进。验证：RED 先出现 1 个预期 AttributeError；start rules 28 tests passed；run orchestration/start/reconcile contract 48 tests passed；文档/架构测试 17 tests passed；完整单测 711 tests passed；`architecture_guard.py` 仅 watch `orchestrator.py: 4972 lines`；`git diff --check` 通过；敏感扫描无命中；当前行数为 `orchestrator.py` 4972 行、`run_orchestration_service.py` 521 行、`tests/test_run_orchestration_start_rules.py` 547 行。
- Run orchestration source branch recording selection split：扩展 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_start_rules.py`，新增 `run_records_source_branch()`，将 `CodingOrchestrator.start_run()` 中是否为 agent run / merge-test run record 计算 source branch 的 mode 判断迁出。helper 只维护 implementation / QA / merge-test mode 需要记录 source branch、plan-only / decomposition 不记录的纯规则；orchestrator 继续负责 `_source_branch_for_task()`、artifact append、agent run append、merge record append 和 ledger 状态推进。验证：RED 先出现 1 个预期 AttributeError；start rules 29 tests passed；run orchestration/start/reconcile contract 49 tests passed；文档/架构测试 17 tests passed；完整单测 712 tests passed；`architecture_guard.py` 仅 watch `orchestrator.py: 4972 lines`；`git diff --check` 通过；敏感扫描无命中；当前行数为 `orchestrator.py` 4972 行、`run_orchestration_service.py` 525 行、`tests/test_run_orchestration_start_rules.py` 554 行。
- Run orchestration project path requirement selection split：扩展 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_start_rules.py`，新增 `run_requires_project_path()`，将 `CodingOrchestrator.start_run()` 中缺少 `project_path` 时只有 decomposition mode 可继续的 mode gate 迁出。helper 只维护 run mode 到 project path requirement 的纯规则；orchestrator 继续负责状态 transition、错误消息、项目路径解析和 runner 启动。验证：RED 先出现 1 个预期 AttributeError；start rules 30 tests passed；run orchestration/start/reconcile contract 50 tests passed；delivery/command/plan 相邻 flow 37 tests passed；文档/架构测试 17 tests passed；完整单测 713 tests passed；`architecture_guard.py` 仅 watch `orchestrator.py: 4972 lines`；`git diff --check` 通过；敏感扫描无命中；当前行数为 `orchestrator.py` 4972 行、`run_orchestration_service.py` 529 行、`tests/test_run_orchestration_start_rules.py` 561 行。
- Run orchestration workspace selection split：新增 `tests/test_run_orchestration_workspace_rules.py`，扩展 `coding_orchestration/run_orchestration_service.py`，新增 `RunWorkspaceSelection`、workspace kind 常量和 `run_workspace_selection_for_mode()`，将 `CodingOrchestrator.start_run()` 中 implementation / QA / merge-test 的 workspace 类型、准备 phase 和缺失 workspace 错误文案选择迁出。helper 只维护 mode 到 workspace selection 的纯投影；orchestrator 继续负责 `_implementation_workspace()`、`_merge_test_workspace()`、状态 transition、ledger 写入、manifest/prompt、runner 启动和后续 report/ledger 副作用。验证：RED 先出现 4 个预期 AttributeError；workspace rules 3 tests passed；run orchestration/start/reconcile contract 53 tests passed；implementation/session/QA/merge-test 相邻 flow 34 tests passed；当前行数为 `orchestrator.py` 4945 行、`run_orchestration_service.py` 558 行、`tests/test_run_orchestration_workspace_rules.py` 50 行、`tests/test_run_orchestration_start_rules.py` 561 行。
- Run start selection projection module split：新增 `coding_orchestration/run_start_selection_projection.py` 和 `tests/test_run_start_selection_projection.py`，将 context source、checkpoint selection、checkpoint failed 判定、QA evidence observation、source branch recording、project path requirement 和 workspace selection 纯规则从 `run_orchestration_service.py` 拆到独立模块。`run_orchestration_service.py` 保留兼容 re-export，旧 orchestrator 调用点和旧 tests 不改名；新模块不读取 workspace、不准备 checkpoint、不写 manifest、不写 ledger、不启动 runner。验证：RED 先出现 1 个预期 ImportError；新增/相邻 contract 58 tests passed；implementation/session/QA/merge-test 相邻 flow 34 tests passed；文档/架构测试 17 tests passed；完整单测 721 tests passed；`architecture_guard.py` 仅 watch `orchestrator.py: 4945 lines`；`git diff --check` 通过；敏感扫描无命中；当前行数为 `run_orchestration_service.py` 503 行、`run_start_selection_projection.py` 76 行、`tests/test_run_start_selection_projection.py` 112 行。
- Run manifest checkpoint preparation selection split：扩展 `coding_orchestration/run_start_selection_projection.py` 和 `tests/test_run_start_selection_projection.py`，新增 `RunManifestCheckpointPreparation`、checkpoint kind 常量和 `run_manifest_checkpoint_preparation_for_mode()`，将 `CodingOrchestrator.start_run()` 中 QA / merge-test 对 manifest target branch 与 checkpoint preparation action 的 mode 选择迁出。helper 只返回目标分支、manifest 字段和 checkpoint kind，不读取 workspace、不准备 checkpoint、不写 manifest；orchestrator 继续负责 `_prepare_qa_checkpoint()`、`_prepare_merge_test_checkpoint()`、manifest 写文件、runner 启动和状态推进。验证：RED 先出现 2 个预期 AttributeError；新增 contract 6 tests passed；run orchestration/start/reconcile/service contract 59 tests passed；implementation/session/QA/merge-test 相邻 flow 34 tests passed；当前行数为 `orchestrator.py` 4953 行、`run_orchestration_service.py` 508 行、`run_start_selection_projection.py` 101 行、`tests/test_run_start_selection_projection.py` 149 行。
- Plan report session writeback projection split：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `build_plan_report_session_update()`，将 `CodingOrchestrator.start_run()` 收尾中“非 stale 的 plan-only run 才写回 `task_session.plan_report`”的 mode/stale gate 迁出。新增 `tests/test_run_orchestration_plan_report_session.py` 承接 plan report session fields 和 writeback contract，避免 `tests/test_run_orchestration_start_rules.py` 超过 600 行治理阈值；orchestrator 继续负责实际 `ledger.update_task_session()`、runner session update、artifact append、summary writer 和 project writeback。验证：RED 先出现 2 个预期 AttributeError；plan report/start/service/reconcile contract 52 tests passed；plan/command/status/source-plan 相邻 flow 26 tests passed；当前行数为 `orchestrator.py` 4956 行、`run_orchestration_service.py` 522 行、`tests/test_run_orchestration_start_rules.py` 523 行、`tests/test_run_orchestration_plan_report_session.py` 108 行。
- Completion session update projection split：扩展 `coding_orchestration/run_orchestration_service.py` 和 `tests/test_run_orchestration_plan_report_session.py`，新增 `build_completion_session_update()`，将 `CodingOrchestrator.start_run()` 收尾中 plan report session update 与 runner session update 的组合规则迁出。helper 只返回 session update payload；fresh plan-only 同时写 `plan_report` 与 `runner`，fresh implementation/QA/merge-test 只写 `runner`，stale completion 不写 session；orchestrator 继续负责实际 `ledger.update_task_session()`、artifact append、summary writer 和 project writeback。验证：RED 先出现 3 个预期 AttributeError；plan report session contract 7 tests passed；run orchestration/start/reconcile/service contract 55 tests passed；plan/command/status/source-plan/implementation session 相邻 flow 34 tests passed；当前行数为 `orchestrator.py` 4952 行、`run_orchestration_service.py` 553 行、`tests/test_run_orchestration_start_rules.py` 523 行、`tests/test_run_orchestration_plan_report_session.py` 181 行。
- Run session projection module split：新增 `coding_orchestration/run_session_projection.py` 和 `tests/test_run_session_projection.py`，将 plan report session fields 白名单、plan report session update、runner session update 和 completion session update 从 `run_orchestration_service.py` 拆到独立模块；`run_orchestration_service.py` 保留兼容 re-export。新模块只返回 session update payload，不写 ledger、不生成 attach command、不读取 artifact、不推进状态。验证：RED 先出现 1 个预期 ImportError；聚焦 contract 28 tests passed；py_compile passed；当前行数为 `orchestrator.py` 4952 行、`run_orchestration_service.py` 465 行、`run_session_projection.py` 99 行、`tests/test_run_session_projection.py` 87 行、`tests/test_run_orchestration_plan_report_session.py` 181 行。
- Run start session projection expansion：扩展 `coding_orchestration/run_session_projection.py` 和 `tests/test_run_session_projection.py`，将 `build_run_start_base_session_update()`、`build_run_start_workspace_session_update()` 和 `build_active_run_session_update()` 从 `run_orchestration_service.py` 迁入 session projection 模块；`run_orchestration_service.py` 保留兼容 re-export。新 helper 仍只返回 session update payload，不选择 workspace、不计算 branch、不写 ledger、不写 manifest、不启动 runner。验证：RED 先出现预期 ImportError；run session/start rules contract 32 tests passed；当前行数为 `run_orchestration_service.py` 418 行、`run_session_projection.py` 149 行、`tests/test_run_session_projection.py` 158 行。
- Run prompt projection module split：新增 `coding_orchestration/run_prompt_projection.py` 和 `tests/test_run_prompt_projection.py`，将 `CodingOrchestrator.start_run()` 中首次 prompt 与增量 prompt 的选择规则和参数合同迁出；`run_orchestration_service.py` 保留兼容 re-export。新 helper 只调用传入的 `PromptBuilder` 生成字符串，不写 `input-prompt.md`、不生成 context artifacts、不写 manifest、不启动 runner、不写 ledger。验证：RED 先出现 1 个预期 `ModuleNotFoundError`；prompt projection contract 3 tests passed；run orchestration/start contract 49 tests passed；prompt/plan/implementation 相邻 flow 20 tests passed；当前行数为 `orchestrator.py` 4943 行、`run_orchestration_service.py` 419 行、`run_prompt_projection.py` 52 行、`tests/test_run_prompt_projection.py` 102 行。
- Run context artifact service split：新增 `coding_orchestration/run_context_artifact_service.py` 和 `tests/test_run_context_artifact_service.py`，将 `CodingOrchestrator._write_prompt_context_artifacts()` 内的 wiki context、confirmed plan / implementation context、assembled context、run instructions、execution policy 和 context index 写入迁出；orchestrator wrapper 只传入 `ContextAssembler`、`PromptBuilder`、dependency tasks 和 sibling tasks。新 service 只写 run_dir 下 context artifact，不写 ledger、manifest、report、summary，不启动 runner、不推进状态。验证：RED 先出现 1 个预期 `ModuleNotFoundError`；context artifact contract 2 tests passed；prompt/plan/implementation/status/QA 相邻 flow 35 tests passed；当前行数为 `orchestrator.py` 4879 行、`run_context_artifact_service.py` 109 行、`tests/test_run_context_artifact_service.py` 110 行。
- Run execution policy artifact read service extension：扩展 `coding_orchestration/run_context_artifact_service.py` 和 `tests/test_run_context_artifact_service.py`，新增 `read_run_execution_policy_artifact()`，将 `CodingOrchestrator._execution_policy_from_run_result()` 中 `execution-policy.json` 的路径 fallback 和 JSON 读取迁出。service 优先消费 result 内联 policy，再读显式 `artifacts.execution_policy`，最后 fallback 到 `run_dir/execution-policy.json`；缺失、无效 JSON 或非 dict 返回空 dict，不写 ledger、manifest、report、summary，不启动 runner、不推进状态。验证：RED 先出现预期 `ImportError`，再出现 wrapper 未委托 service 的预期断言失败；context artifact contract 7 tests passed；当前行数为 `orchestrator.py` 4788 行、`run_context_artifact_service.py` 136 行、`tests/test_run_context_artifact_service.py` 205 行。
- Run project writeback host service split：新增 `coding_orchestration/run_project_writeback_service.py` 和 `tests/test_run_project_writeback_service.py`，将 `CodingOrchestrator.start_run()` completed path 中 Project writeback 的 stale gate、payload 构造委托和 `_writeback_project_bugfix_completion()` callback 调用迁出到 `write_run_project_completion()`。service stale 时直接返回 skipped，不调用 callback；fresh 时复用 `build_project_writeback_payload()` 后调用注入 callback，不直接 import `WorkItemService` 或 MCP adapter，不写 ledger/artifact，不启动 runner、不推进状态。验证：RED 先出现预期 `ModuleNotFoundError`，再出现 orchestrator 未委托 service 的预期 `AttributeError`；run project writeback service contract 3 tests passed；当前行数为 `orchestrator.py` 4785 行、`run_project_writeback_service.py` 34 行、`tests/test_run_project_writeback_service.py` 120 行。
- Run summary writeback host service split：新增 `coding_orchestration/run_summary_writeback_service.py` 和 `tests/test_run_summary_writeback_service.py`，将 `CodingOrchestrator.start_run()` 与 `_reconcile_completed_active_run()` 中 summary writer payload 构造后直接调用 `summary_writer.write_run_summary()` 的 host 副作用迁出到 `write_completed_run_summary()` / `write_reconciled_run_summary()`。service 复用 `run_summary_projection.py` 构造 payload，只调用注入 writer callback；不读取 `summary.md`，不直接 import `RunSummaryWriter` / `KnowledgePort`，不写 ledger/artifact，不启动 runner、不推进状态。验证：RED 先出现预期 `ModuleNotFoundError`，再出现 orchestrator 未委托 service 的预期 `AttributeError`；run summary writeback service contract 4 tests passed；summary projection + plan/status 相邻 flow 21 tests passed；当前行数为 `orchestrator.py` 4785 行、`run_summary_writeback_service.py` 57 行、`tests/test_run_summary_writeback_service.py` 248 行。
- Run ledger writeback host service split：新增 `coding_orchestration/run_ledger_writeback_service.py` 和 `tests/test_run_ledger_writeback_service.py`，将 `CodingOrchestrator.start_run()` 与 `_reconcile_completed_active_run()` 中 run lifecycle ledger mutation callback 迁出到 `write_run_ledger_completion()` / `write_reconciled_run_ledger()`。service 只消费 `run_ledger_projection.py` 生成的 records 并调用注入 ledger callback；不构造 payload、不直接 import `TaskLedger` / storage repository、不写 artifact、不启动 runner、不推进状态。验证：RED 先出现预期 `ModuleNotFoundError`，再出现 orchestrator 未委托 service 的预期 `AttributeError`；run ledger writeback service contract 5 tests passed；projection + plan/status/QA/merge-test 相邻 flow 已定向通过；当前行数为 `orchestrator.py` 4793 行、`run_ledger_writeback_service.py` 32 行、`tests/test_run_ledger_writeback_service.py` 254 行。
- Run session writeback host service split：新增 `coding_orchestration/run_session_writeback_service.py` 和 `tests/test_run_session_writeback_service.py`，将 `CodingOrchestrator.start_run()`、`start_run()` 异常清理与 `_reconcile_completed_active_run()` 中 run lifecycle task session callback 迁出到 `write_run_session_update()`。service 只消费 `run_session_projection.py` 已构造的 update dict 并调用注入 `update_task_session` callback，空 update 跳过；不构造 payload、不直接 import `TaskLedger` / storage repository、不写 artifact、不启动 runner、不推进状态。验证：RED 先出现预期 `ModuleNotFoundError`，再出现 orchestrator 未委托 service 的预期 `AttributeError`，并补充 transition 失败清理路径 RED；run session writeback service contract 5 tests passed；session projection + plan/status/QA/merge-test 相邻 flow 已定向通过；当前行数为 `orchestrator.py` 4805 行、`run_session_writeback_service.py` 16 行、`tests/test_run_session_writeback_service.py` 290 行。
- Run manifest start update projection split：扩展 `coding_orchestration/run_manifest_service.py` 和 `tests/test_run_manifest_service.py`，新增 `build_start_manifest_updates()`，将 `CodingOrchestrator.start_run()` 中启动期 resume session、controlled bypass 权限字段和 merge-test target branch 的 manifest update 投影迁出。helper 只返回字段 update，不写 manifest 文件、不准备 checkpoint、不启动 runner、不更新 ledger；orchestrator 继续负责 checkpoint 准备、manifest 文件写入、runner 启动和状态推进，并删除已无调用的 manifest permission 私有 wrapper。验证：RED 先出现预期 ImportError；manifest service contract 14 tests passed；manifest/run/start 相关 contract 66 tests passed；plan/source/implementation/QA/merge-test 相邻 flow 48 tests passed；当前行数为 `orchestrator.py` 4842 行、`run_manifest_service.py` 355 行、`tests/test_run_manifest_service.py` 298 行。
- Run manifest artifact service split：新增 `coding_orchestration/run_manifest_artifact_service.py` 和 `tests/test_run_manifest_artifact_service.py`，将 `CodingOrchestrator.start_run()` 中 implementation dirty-check checkpoint 后的 `run-manifest.json` 写回迁出到 `write_run_manifest_artifact()`。新 service 只写指定 manifest artifact，不写 report/summary/ledger，不启动 runner、不推进状态；checkpoint 生成、状态 transition、artifact/agent_run append 和 project writeback 继续留在原边界；迁移后删除无调用的 `_json()` helper。验证：RED 先出现预期 `ModuleNotFoundError`；run manifest artifact service contract 2 tests passed；manifest/start/implementation/QA/merge-test 相邻 flow 39 tests passed；当前行数为 `orchestrator.py` 4840 行、`run_manifest_artifact_service.py` 24 行、`tests/test_run_manifest_artifact_service.py` 49 行。
- Run stderr artifact service split：新增 `coding_orchestration/run_stderr_artifact_service.py` 和 `tests/test_run_stderr_artifact_service.py`，将 runner failed 和 checkpoint failed 路径中的 `stderr.log` 写回迁出到 `write_run_stderr_artifact()`。新 service 只写指定 stderr artifact，不写 report/summary/manifest/ledger，不启动 runner、不推进状态；failure payload、RunResult 包装、状态 transition、artifact/agent_run append 和 project writeback 继续留在原边界。验证：RED 先出现预期 `ModuleNotFoundError`；run stderr artifact service contract 2 tests passed；failure/start/QA/merge-test/command 相邻 flow 52 tests passed；当前行数为 `orchestrator.py` 4841 行、`run_stderr_artifact_service.py` 11 行、`tests/test_run_stderr_artifact_service.py` 41 行。
- Run report artifact service split：新增 `coding_orchestration/run_report_artifact_service.py` 和 `tests/test_run_report_artifact_service.py`，将 `CodingOrchestrator._reconcile_completed_active_run()`、`start_run()`、runner failed 和 checkpoint failed 路径中的 `report.json` 写回迁出到 `write_run_report_artifact()`。新 service 只写指定 report artifact，不写 manifest/summary/ledger，不启动 runner、不推进状态；report payload 构造、状态 transition、artifact/agent_run append、summary 和 project writeback 继续留在原边界。验证：RED 先出现预期 `ModuleNotFoundError`；run report artifact service contract 2 tests passed；status/plan/command/implementation/QA/merge-test 相邻 flow 45 tests passed；当前行数为 `orchestrator.py` 4844 行、`run_report_artifact_service.py` 17 行、`tests/test_run_report_artifact_service.py` 40 行。
- Run report artifact read service extension：扩展 `coding_orchestration/run_report_artifact_service.py` 和 `tests/test_run_report_artifact_service.py`，新增 `read_run_report_artifact()`，将 `CodingOrchestrator._reconcile_completed_active_run()` 中 active run `report.json` 读取迁出到 report artifact service。service 只读写指定 `report.json`，缺失、无效 JSON 或非 dict 时返回空 dict，不生成 report、不写 manifest/summary/ledger、不启动 runner、不推进状态；task status presenter 的读取 wrapper 继续保留给 presentation/status 展示路径。验证：RED 先出现预期 `ImportError` 和 active run reconcile 使用 presenter reader 的预期断言；run report artifact service contract 3 tests passed；active run reconcile flow 1 test passed；当前行数为 `orchestrator.py` 4820 行、`run_report_artifact_service.py` 27 行、`tests/test_run_report_artifact_service.py` 61 行。
- Run report summary excerpt service extension：扩展 `coding_orchestration/run_report_artifact_service.py` 和 `tests/test_run_report_artifact_service.py`，新增 `read_run_report_summary_markdown()`，将 `CodingOrchestrator._report_summary_markdown()` 中 `summary_markdown` 读取和截断逻辑迁到 report artifact service。service 只读取指定 `report.json` 的 summary excerpt，不生成 report、不写 manifest/summary/ledger、不启动 runner、不推进状态；orchestrator 保留兼容 wrapper，confirmed plan / merge-test context 的调用路径不变。验证：RED 先出现预期 `ImportError`；run report artifact service contract 5 tests passed；当前行数为 `orchestrator.py` 4808 行、`run_report_artifact_service.py` 35 行、`tests/test_run_report_artifact_service.py` 104 行。
- Run summary artifact service split：新增 `coding_orchestration/run_summary_artifact_service.py` 和 `tests/test_run_summary_artifact_service.py`，将 active run reconcile、runner failed 和 checkpoint failed 路径中的 `summary.md` 写回迁出到 `write_run_summary_artifact()`。新 service 只写指定 summary artifact，不写 report/manifest/ledger，不启动 runner、不推进状态；summary 内容来源、状态 transition、artifact/agent_run append 和 project writeback 继续留在原边界。验证：RED 先出现预期 `ModuleNotFoundError`；run summary artifact service contract 2 tests passed；status/plan/command/implementation/QA/merge-test 相邻 flow 45 tests passed；当前行数为 `orchestrator.py` 4845 行、`run_summary_artifact_service.py` 11 行、`tests/test_run_summary_artifact_service.py` 34 行。
- Run ledger writeback projection split：新增 `coding_orchestration/run_ledger_projection.py` 和 `tests/test_run_ledger_projection.py`，将 `CodingOrchestrator.start_run()` 尾部 artifact record、agent_run record 和 fresh merge-test record 的写回 payload 聚合迁出到 `build_run_ledger_writeback_records()`。新 projection 只返回 `artifact_record`、`agent_run_record` 和可选 `merge_test_record`，不调用 ledger、不写 artifact、不启动 runner、不推进状态；实际 `append_artifact()`、`append_agent_run()` 和 `append_merge_record()` 继续留在 orchestrator host 边界。验证：RED 先出现预期 `ModuleNotFoundError`；run ledger projection + run orchestration service contract 20 tests passed；implementation/workspace/QA/merge-test/status 相邻 flow 34 tests passed；当前行数为 `orchestrator.py` 4836 行、`run_ledger_projection.py` 69 行、`tests/test_run_ledger_projection.py` 135 行。
- Reconciled run ledger writeback projection expansion：扩展 `coding_orchestration/run_ledger_projection.py` 和 `tests/test_run_ledger_projection.py`，将 `CodingOrchestrator._reconcile_completed_active_run()` 中 artifact record 和 merged agent run upsert payload 聚合迁出到 `build_reconciled_run_ledger_writeback_records()`。新 projection 只返回 `artifact_record` 和 `agent_run_record`，不调用 ledger、不写 artifact、不启动 runner、不推进状态；实际 `upsert_artifact()` 和 `upsert_agent_run()` 继续留在 orchestrator host 边界。验证：RED 先出现预期 ImportError；run ledger projection + run orchestration/reconcile contract 23 tests passed；status/implementation/QA/merge-test 相邻 flow 27 tests passed；当前行数为 `orchestrator.py` 4837 行、`run_ledger_projection.py` 103 行、`tests/test_run_ledger_projection.py` 192 行。
- Reconciled run summary writeback projection split：新增 `coding_orchestration/run_summary_projection.py` 和 `tests/test_run_summary_projection.py`，将 `CodingOrchestrator._reconcile_completed_active_run()` 中 run summary writer payload 聚合迁出到 `build_reconciled_run_summary_writeback_payload()`。新 projection 只返回 `RunSummaryWritebackPayload`，不调用 summary writer、不写 LLM Wiki、不写 ledger、不推进状态；实际 `summary_writer.write_run_summary()` 继续留在 orchestrator host 边界。验证：RED 先出现预期 `ModuleNotFoundError`；run summary projection contract 2 tests passed；run summary/status/reconcile/service 相邻 contract 28 tests passed；当时行数为 `orchestrator.py` 4840 行、`run_summary_projection.py` 46 行、`tests/test_run_summary_projection.py` 48 行。
- Completed run summary writeback projection expansion：扩展 `coding_orchestration/run_summary_projection.py` 和 `tests/test_run_summary_projection.py`，将 `CodingOrchestrator.start_run()` 中 run summary writer payload 聚合迁出到 `build_completed_run_summary_writeback_payload()`。新 projection 只返回 `RunSummaryWritebackPayload`，不读取 summary artifact、不调用 summary writer、不写 LLM Wiki、不写 ledger、不推进状态；summary artifact 读取和实际 `summary_writer.write_run_summary()` 继续留在 orchestrator host 边界。验证：RED 先出现预期 ImportError；run summary projection contract 4 tests passed；plan/status/run orchestration 相邻 contract 35 tests passed；当前行数为 `orchestrator.py` 4841 行、`run_summary_projection.py` 65 行、`tests/test_run_summary_projection.py` 89 行。
- Run artifact path projection split：新增 `coding_orchestration/run_artifact_paths.py` 和 `tests/test_run_artifact_paths.py`，将 `CodingOrchestrator._artifact_set_for_run_dir()` 与 `_artifact_set_for_existing_run()` 中 fresh run_dir / existing run record 的 `ArtifactSet` 路径合同迁出。新 projection 只返回路径，不读取 artifact 文件、不创建目录、不写 ledger、不启动 runner、不推进状态；existing run fallback 补齐 `context_manifest`。验证：RED 先出现预期 `ModuleNotFoundError`；run artifact path contract 3 tests passed；status/report/summary/stderr 相邻 artifact flow 15 tests passed；plan/run orchestration 相邻 contract 28 tests passed；当前行数为 `orchestrator.py` 4820 行、`run_artifact_paths.py` 52 行、`tests/test_run_artifact_paths.py` 66 行。
- Completed run summary artifact read service expansion：扩展 `coding_orchestration/run_summary_artifact_service.py` 和 `tests/test_run_summary_artifact_service.py`，将 `CodingOrchestrator.start_run()` completed path 中对 `summary.md` 的直接读取迁出到 `read_run_summary_artifact()`。service 只读取或写入指定 summary artifact，缺失时返回空字符串，不生成 summary、不写 report/manifest/ledger、不启动 runner、不推进状态、不调用 summary writer。验证：RED 先出现预期 `ImportError`；run summary artifact service contract 3 tests passed；plan/status/run summary projection 相邻 flow 20 tests passed；当前行数为 `orchestrator.py` 4820 行、`run_summary_artifact_service.py` 17 行、`tests/test_run_summary_artifact_service.py` 47 行。
- Run diff guard observation host service split：新增 `coding_orchestration/run_diff_guard_service.py` 和 `tests/test_run_diff_guard_service.py`，将 `CodingOrchestrator.start_run()` 中 before snapshot、changed files 观测、QA report artifact 过滤、allowed/forbidden path violations、plan-only 写入 violations 补充和 `diff.patch` summary 写回迁出到 `snapshot_run_diff_guard()` / `observe_run_diff_guard()`。新 service 只返回 `RunDiffGuardObservation(changed_files, violations)` 并写指定 diff artifact，不写 ledger/report/manifest/summary，不启动 runner、不推进状态；QA evidence 收集、implementation dirty-check、report refinement、ledger records 和状态 transition 继续留在原边界。验证：RED 先出现预期 `ModuleNotFoundError`，再出现 orchestrator 未委托 service 的预期 `AttributeError`；run diff guard service contract 3 tests passed；run start/diff guard/plan/implementation 相邻 flow 48 tests passed；当前行数为 `orchestrator.py` 4802 行、`run_diff_guard_service.py` 46 行、`tests/test_run_diff_guard_service.py` 169 行。
- Runner dispatch host service split：新增 `coding_orchestration/run_dispatch_service.py` 和 `tests/test_run_dispatch_service.py`，将 `CodingOrchestrator.start_run()` 中 checkpoint failure gate、`runner.run()` 调度和 runner exception fallback 迁出到 `dispatch_run()`。新 service 只消费已准备好的 checkpoint，调用注入 runner 或失败 result callback，不写 ledger/report/manifest/summary、不执行 diff guard、不收集 QA evidence、不推进状态；checkpoint 准备、状态 transition、diff guard、QA evidence、report refinement 和 ledger/summary/project/session 写回继续留在原边界。验证：RED 先出现预期 `ModuleNotFoundError`，再出现 orchestrator 未委托 service 的预期 `AttributeError`；run dispatch service contract 5 tests passed；run orchestration start/plan/implementation 相邻 flow 46 tests passed；当前行数为 `orchestrator.py` 4792 行、`run_dispatch_service.py` 46 行、`tests/test_run_dispatch_service.py` 342 行。
- Run status transition host service split：新增 `coding_orchestration/run_status_transition_service.py` 和 `tests/test_run_status_transition_service.py`，将 `_transition_task_status()` 的状态机/ledger/Kanban callback shell、run start/completion/reconcile transition、missing project/workspace transition 和 active run cleanup 迁出。新 service 通过注入 callback 工作，不直接持有 `TaskLedger`，不写 report/manifest/summary、不启动 runner、不执行 diff guard、不收集 QA evidence；目标 status/phase 计算、report refinement、QA evidence、implementation dirty-check、ledger run record 和 WorkItemService 写回继续留在原边界。验证：RED 先出现预期 `ModuleNotFoundError`；run status transition service contract 7 tests passed；orchestrator run flow、session writeback 和 run start rules 相邻 tests 43 tests passed；当前行数为 `orchestrator.py` 4766 行、`run_status_transition_service.py` 167 行、`tests/test_run_status_transition_service.py` 367 行。
- Run evidence observation host service split：新增 `coding_orchestration/run_evidence_observation_service.py` 和 `tests/test_run_evidence_observation_service.py`，将 `CodingOrchestrator.start_run()` 中 QA artifacts/tested commit observation 和 implementation dirty-check observation 迁出。新 service 只调用注入 callback 返回 `RunQaEvidenceObservation` 或 dirty flag，不写 ledger/report/manifest/summary、不创建 checkpoint、不启动 runner、不执行 diff guard、不推进状态；checkpoint 创建、manifest 写回、report refinement 和 WorkItemService 业务写回继续留在原边界。验证：RED 先出现预期 `ModuleNotFoundError`；run evidence observation service contract 5 tests passed；QA/implementation/start/docs/architecture 相邻 tests 67 tests passed；完整单测 805 tests passed；architecture guard 仅 watch `orchestrator.py: 4777 lines`；`git diff --check` passed；当前行数为 `orchestrator.py` 4777 行、`run_evidence_observation_service.py` 41 行、`tests/test_run_evidence_observation_service.py` 201 行。
- Run checkpoint preparation host service split：新增 `coding_orchestration/run_checkpoint_preparation_service.py` 和 `tests/test_run_checkpoint_preparation_service.py`，将 `CodingOrchestrator.start_run()` 中 QA / merge-test checkpoint preparation callback 选择、调用和 `checkpoint_payload -> qa_checkpoint / merge_test_checkpoint` manifest update payload 构造迁出。新 service 只调用注入 callback 并返回 `RunCheckpointPreparationResult(manifest_updates=...)`，不直接 mutate manifest、不写 artifact/ledger/report/summary、不启动 runner、不执行 diff guard、不推进状态；mode 到 checkpoint kind/target branch 选择仍归 `run_start_selection_projection.py`，manifest 文件写入仍归 artifact service，implementation dirty-check 后置 manifest 写回仍留在后续切片。验证：run checkpoint preparation service contract 5 tests passed；checkpoint/start/workspace/manifest/dispatch 相邻 tests 46 passed；QA/merge-test/implementation/start 相邻 tests 54 passed；文档/架构测试 17 passed；完整单测 810 passed；当前行数为 `orchestrator.py` 4777 行、`run_checkpoint_preparation_service.py` 40 行、`tests/test_run_checkpoint_preparation_service.py` 202 行。
- Run implementation checkpoint writeback host service split：新增 `coding_orchestration/run_implementation_checkpoint_service.py` 和 `tests/test_run_implementation_checkpoint_service.py`，将 `CodingOrchestrator.start_run()` 中 dirty 后置 `implementation_checkpoint` 生成和 `run-manifest.json` 写回 callback 接线迁出。新 service 只消费已计算好的 dirty flag，调用注入 checkpoint / manifest writer callback，不判断 dirty、不构造 blocked report、不写 ledger/report/summary、不启动 runner、不推进状态；dirty observation、report refinement、状态 transition、artifact/agent_run append、summary 和 project writeback 继续留在原边界。验证：RED 先出现预期 `ModuleNotFoundError`；run implementation checkpoint service contract 4 tests passed；implementation/report refinement/manifest/evidence/start 相邻 tests 48 passed；当前行数为 `orchestrator.py` 4781 行、`run_implementation_checkpoint_service.py` 51 行、`tests/test_run_implementation_checkpoint_service.py` 208 行。
- Run manifest session metadata writeback host service split：新增 `coding_orchestration/run_manifest_session_writeback_service.py` 和 `tests/test_run_manifest_session_writeback_service.py`，将 `CodingOrchestrator.start_run()` 中已解析 runner session id 后的 manifest session 字段设置和 `_update_manifest_session_metadata()` callback 接线迁出。新 service 只消费已解析 `session_id`，复用 `run_manifest_service.build_manifest_session_fields()` 更新 object/dict manifest，并调用注入 manifest metadata writer；不解析 stdout、不写 ledger/report/summary、不启动 runner、不推进状态。验证：RED 先出现预期 `ModuleNotFoundError`；run manifest session writeback service contract 4 tests passed；manifest/session/implementation session 相邻 tests 45 passed；当前行数为 `orchestrator.py` 4775 行、`run_manifest_session_writeback_service.py` 66 行、`tests/test_run_manifest_session_writeback_service.py` 181 行。
- Completed run writeback coordinator service split：新增 `coding_orchestration/run_completion_writeback_service.py` 和 `tests/test_run_completion_writeback_service.py`，将 `CodingOrchestrator.start_run()` 中 fresh completed run 的 completion projection、stale observation、状态 transition、ledger/session/summary/project writeback 和 final result payload 协调迁出。新 service 只消费已完成 runner result 的投影数据和注入 callback；不启动 runner、不执行 diff guard、不收集 QA evidence、不判断 dirty、不准备 checkpoint、不解析 stdout、不直接持有 host adapter。验证：RED 先出现预期 `ModuleNotFoundError`；run completion writeback service contract 3 tests passed；writeback/start 相邻 tests 48 passed；主流程 tests 34 passed；当前行数为 `orchestrator.py` 4704 行、`run_completion_writeback_service.py` 181 行、`tests/test_run_completion_writeback_service.py` 256 行。
- Active run reconcile writeback coordinator service split：新增 `coding_orchestration/run_reconcile_writeback_service.py` 和 `tests/test_run_reconcile_writeback_service.py`，将 `CodingOrchestrator._reconcile_completed_active_run()` 中 active run reconcile 完成态的 completion projection、最终 report 写回、状态 transition、ledger upsert、runner session update、summary writer callback 和 result payload 协调迁出。新 service 只消费已归一化 report 与注入 callback；不读取 workspace、不启动 runner、不执行 diff guard、不收集 QA evidence、不判断 dirty、不准备 checkpoint、不解析 stdout、不直接持有 host adapter；`_reconcile_completed_active_run()` 继续保留 task/session/run/report 读取、cancelled/running early return、mode/status/details/changed_files 观测与 artifact 前置归一化。验证：RED 先出现预期 `ModuleNotFoundError`；run reconcile writeback service contract 2 tests passed；reconcile/status/writeback 相邻 tests 32 passed；当前行数为 `orchestrator.py` 4658 行、`run_reconcile_writeback_service.py` 137 行、`tests/test_run_reconcile_writeback_service.py` 238 行。

## Task 19: Modularize Large Flow Tests

**Files:**
- Modify: `tests/test_orchestrator_run_flow.py`
- Create: new `tests/test_*_flow.py` files by behavior domain.
- Update: any shared test fixtures/helpers.

**Step 1: Classify existing flow tests**

Group by behavior:

- task create / plan-only.
- implementation / QA / merge-test / complete.
- delivery breakdown / materialize / run-next.
- report schema / report admission.
- safety gates and diff guard.

**Step 2: Move one group at a time**

Keep assertions unchanged during the move. Do not combine test moving with behavior changes.

**Step 3: Replace private helper assertions**

Where a moved test still binds an old private helper, migrate it to service/policy contract coverage before deleting the old assertion.

**Step 4: Run split test groups and full suite**

Run:

```bash
rtk proxy python3 -m unittest tests.test_orchestrator_run_flow -v
rtk proxy python3 -m unittest discover -s tests -v
```

Expected: PASS, with `tests/test_orchestrator_run_flow.py` no longer acting as the only owner of unrelated flow coverage.

**Progress log**

- Delivery flow split：新增 `tests/orchestrator_flow_fixtures.py` 和 `tests/test_delivery_flow.py`。将 delivery/materialize/run-next/status delivery 的 6 条 flow 测试迁出 `tests/test_orchestrator_run_flow.py`，并把共享 fake runner/gateway/rewriter/reader fixture 从巨型测试文件抽到独立 fixture 模块。迁移过程中不改断言和业务行为。验证：`rtk proxy python3 -m unittest tests.test_delivery_flow tests.test_orchestrator_run_flow -v` 通过，`182 tests OK`；`rtk proxy python3 scripts/architecture_guard.py` 通过，`tests/test_orchestrator_run_flow.py` watchlist 行数从 10005 降至 9270。
- Source flow split：新增 `tests/test_source_flow.py` 和 `tests/test_source_plan_flow.py`。将 Feishu Project/Docx/Wiki source indexing、deferred source task creation、source context repair、source elevated plan manifest 和 source ledger payload 相关 flow 从 `tests/test_orchestrator_run_flow.py` 迁出；新文件分别为 446 行和 304 行，避免新增 large-file watch。验证：`rtk proxy python3 -m unittest tests.test_source_flow tests.test_source_plan_flow tests.test_orchestrator_run_flow -v` 通过，`176 tests OK`；`tests/test_orchestrator_run_flow.py` watchlist 行数从 9270 降至 8517。
- QA flow split：新增 `tests/test_qa_flow.py`。将实现完成后不自动 QA、手动 QA 启动、QA artifacts 收集、QA clean-tree gate 和 QA completion notification 相关 flow 从 `tests/test_orchestrator_run_flow.py` 迁出；新文件 450 行，避免新增 large-file watch。迁移过程中不改断言和业务行为。验证：`rtk proxy python3 -m unittest tests.test_qa_flow tests.test_orchestrator_run_flow -v` 通过，`163 tests OK`；`tests/test_orchestrator_run_flow.py` watchlist 行数从 8517 降至 8095。
- Completion flow split：新增 `tests/test_completion_flow.py`。将 merged-test 后 `/coding list` 展示、长描述摘要和人工 complete 拒绝/完成相关 flow 从 `tests/test_orchestrator_run_flow.py` 迁出；新文件 139 行，避免新增 large-file watch。迁移过程中不改断言和业务行为。验证：`rtk proxy python3 -m unittest tests.test_completion_flow tests.test_orchestrator_run_flow -v` 通过，`156 tests OK`；`tests/test_orchestrator_run_flow.py` watchlist 行数从 8095 降至 7973。
- Cancel/restore flow split：新增 `tests/test_cancel_restore_flow.py`。将 pending action 对已取消任务的拒绝、自然语言取消确认、已取消任务 continue/change/bugfix 拒绝、runner 命令拒绝、误取消恢复和 done 任务不可取消相关 flow 从 `tests/test_orchestrator_run_flow.py` 迁出；新文件 379 行，避免新增 large-file watch。迁移过程中不改断言和业务行为。验证：`rtk proxy python3 -m unittest tests.test_cancel_restore_flow tests.test_orchestrator_run_flow -v` 通过，`152 tests OK`；`tests/test_orchestrator_run_flow.py` watchlist 行数从 7973 降至 7618。
- Merge-test flow split：新增 `tests/test_merge_test_basic_flow.py`、`tests/test_merge_test_readiness_flow.py`、`tests/test_merge_test_blocked_flow.py` 和 `tests/test_merge_test_qa_gate_flow.py`。将 prepare-merge-test、merge-test session resume、blocked merge readiness、风险确认 pending action、QA risk gate、merge-test human-required 和 clean-tree gate 相关 flow 从 `tests/test_orchestrator_run_flow.py` 迁出；四个新文件分别为 456、566、476、459 行，避免新增 large-file watch。迁移过程中不改断言和业务行为。验证：`rtk proxy python3 -m unittest tests.test_merge_test_basic_flow tests.test_merge_test_readiness_flow tests.test_merge_test_blocked_flow tests.test_merge_test_qa_gate_flow tests.test_orchestrator_run_flow -v` 通过，`143 tests OK`；`rtk proxy python3 scripts/architecture_guard.py` 通过，`tests/test_orchestrator_run_flow.py` watchlist 行数从 7618 降至 5722。
- Plan/implementation/command flow split：新增 `tests/test_plan_run_flow.py`、`tests/test_implementation_result_flow.py`、`tests/test_implementation_workspace_flow.py`、`tests/test_implementation_session_flow.py`、`tests/test_command_run_flow.py` 和 `tests/test_bugfix_writeback_flow.py`。将 plan-only run/completion/只读 gate、implementation 状态结果、workspace/branch、session/prompt、`/coding run` / `/coding implement` command gate 和 bugfix Project writeback flow 从 `tests/test_orchestrator_run_flow.py` 迁出；新文件均低于 600 行。迁移过程中不改断言和业务行为。验证：`rtk proxy python3 -m unittest tests.test_plan_run_flow tests.test_implementation_result_flow tests.test_implementation_workspace_flow tests.test_implementation_session_flow tests.test_command_run_flow tests.test_bugfix_writeback_flow tests.test_orchestrator_run_flow -v` 通过，`117 tests OK`；`rtk proxy python3 scripts/architecture_guard.py` 通过，`tests/test_orchestrator_run_flow.py` watchlist 行数从 5722 降至 3903。
- Gateway/status flow split：新增 `tests/test_gateway_project_task_flow.py`、`tests/test_gateway_command_group_flow.py`、`tests/test_status_reconcile_flow.py`、`tests/test_gateway_task_control_flow.py`、`tests/test_gateway_feedback_flow.py`、`tests/test_gateway_change_continue_flow.py` 和 `tests/test_gateway_safety_lifecycle_flow.py`。将项目/任务路由、命令组、status reconcile、确认/use/delete/continue、bugfix/change/continue feedback、安全生命周期相关 flow 从 `tests/test_orchestrator_run_flow.py` 迁出；原文件仅保留端到端 smoke、kanban transition 和 plan-only resume sandbox，从 3903 行降至 226 行，新文件均低于 600 行。迁移过程中不改断言和业务行为。验证：`rtk proxy python3 -m unittest tests.test_orchestrator_run_flow tests.test_gateway_project_task_flow tests.test_gateway_command_group_flow tests.test_status_reconcile_flow tests.test_gateway_task_control_flow tests.test_gateway_feedback_flow tests.test_gateway_change_continue_flow tests.test_gateway_safety_lifecycle_flow -v` 通过，`47 tests OK`；`rtk proxy python3 scripts/architecture_guard.py` 通过，`tests/test_orchestrator_run_flow.py` 不再出现在 large-file watchlist。
