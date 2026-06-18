# 项目约定

## 基本规则

- 对话、提交说明和项目说明默认使用简体中文。
- 所有 shell 命令必须带 `rtk` 前缀。需要原始输出时使用 `rtk proxy <cmd>`。
- 优先修改现有模块，不新建平行实现；插件边界已经集中在 `coding_orchestration/`。
- 不把运行根、token、auth、`.env*`、本地 LLM Wiki 内容或 Task Ledger 数据提交到仓库。
- 飞书项目 MCP 只读取 `~/.hermes/coding-orchestration/mcp.json`；真实 `MCP_USER_TOKEN` 只允许存在于本机运行配置和 MCP 子进程环境，不允许写入仓库、LLM Wiki、run artifacts、prompt 或测试 fixture。

## 开发入口

- 插件注册入口是 `coding_orchestration/__init__.py`。
- `/coding` 命令执行、人机门禁和运行阶段推进主要在 `coding_orchestration/orchestrator.py`；后台 run 等待完成、后台失败 transition 和 merge-test `human_required` 转 pending action 优先维护在 `coding_orchestration/run_background_orchestration.py`；runner/checkpoint failure report payload 优先维护在 `coding_orchestration/run_failure_report_projection.py`；diff guard / implementation commit missing blocked report 构造和 run report refinement projection 优先维护在 `coding_orchestration/run_report_refinement_projection.py`；run context source、run checkpoint 选择、QA evidence observation、source branch recording、project path requirement、workspace selection 和 manifest checkpoint preparation selection 纯规则优先维护在 `coding_orchestration/run_start_selection_projection.py`；plan report session fields 白名单、plan report session update、run start base/workspace session update、active run session update、runner session update 和 completion session update 优先维护在 `coding_orchestration/run_session_projection.py`；首次/增量 prompt 构造选择和参数合同优先维护在 `coding_orchestration/run_prompt_projection.py`；run context artifact 写入优先维护在 `coding_orchestration/run_context_artifact_service.py`；`report.schema.json`、`input-prompt.md` 和 `run-manifest.json` 启动 artifact 写入优先维护在 `coding_orchestration/run_start_artifact_service.py`；后续 `run-manifest.json` artifact 写回优先维护在 `coding_orchestration/run_manifest_artifact_service.py`；`stderr.log` 写回优先维护在 `coding_orchestration/run_stderr_artifact_service.py`；`report.json` 写回优先维护在 `coding_orchestration/run_report_artifact_service.py`；`summary.md` 读写优先维护在 `coding_orchestration/run_summary_artifact_service.py`；start_run 与 active run reconcile 的 run ledger 写回 payload 聚合优先维护在 `coding_orchestration/run_ledger_projection.py`；fresh/existing run 的 `ArtifactSet` 路径合同优先维护在 `coding_orchestration/run_artifact_paths.py`；启动期 manifest update projection、run-manifest 基础字段和权限 profile 优先维护在 `coding_orchestration/run_manifest_service.py`；observed run report 构造、stale completion 观测、execution policy decision 读取、run-level diff guard violations 组合、verification limitations fallback projection、completion report payload、agent run record 构造、reconciled agent run record 构造、reconcile result payload 构造、existing run mode/changed files 规则、merge-test run record 构造、project writeback payload 构造、start_run result payload 构造和 run completion 状态/phase/report 投影优先维护在 `coding_orchestration/run_orchestration_service.py`，session/prompt projection 仅作为兼容 re-export 暴露；显式 `/coding` / `/commands` 解析、命令归一化、命令 route plan、handler key、reply mode、task id 来源策略、merge-test 参数、rewrite canonical command、确认/取消词、rewrite 风险确认、Gateway event dedupe 和授权探测优先维护在 `coding_orchestration/gateway_command_controller.py`；task/run/delivery/implementation/QA/prepare-merge-test/merge-test 的 Gateway custom route 分发优先维护在 `coding_orchestration/gateway_command_executor.py`；pending action 确认/取消、latest human_required fallback 和确认后显式命令续接优先维护在 `coding_orchestration/gateway_pending_action_executor.py`；active project 应用到缺项目 task 的回填逻辑优先维护在 `coding_orchestration/gateway_active_context.py`。
- Completed run 与 active run reconcile 的 run summary writer payload 聚合优先维护在 `coding_orchestration/run_summary_projection.py`；该模块只返回写入参数，不读取 summary artifact、不调用 summary writer、不写 LLM Wiki、不写 ledger、不推进状态。
- Hermes native tools 注册在 `coding_orchestration/plugin_tools.py`，CLI 子命令注册在 `coding_orchestration/cli.py`。
- 通用 skill 规则维护在 `coding_orchestration/skills/coding-operator-core/` 和 `coding-health-core/`；Hermes 绑定映射维护在 `hermes-coding-operator/` 和 `hermes-coding-health-check/`。
- Codex CLI 命令构造、resume、sandbox、结构化 report 读取在 `coding_orchestration/runners/codex_cli.py`。
- 安装和卸载逻辑优先改 `coding_orchestration/install.py`，脚本只保留入口和用户输出。

## 验证 Gate

| 场景 | 命令 |
| --- | --- |
| 完整单测 | `rtk proxy python3 -m unittest discover -s tests -v` |
| 单个测试文件 | `rtk proxy python3 -m unittest tests.test_install -v` |
| 架构治理检查 | `rtk proxy python3 scripts/architecture_guard.py` |
| 安装前置检查 | `rtk python3 scripts/install_symlink.py --hermes-home ~/.hermes` |
| 卸载 dry-run | `rtk python3 scripts/uninstall_legacy.py --hermes-home ~/.hermes` |
| Hermes 插件状态 | `rtk hermes plugins list` |
| Hermes Gateway 状态 | `rtk hermes gateway status` |
| Gateway health | `rtk proxy curl -sS http://127.0.0.1:8642/health` |

运行安装脚本会访问本机 Hermes、Codex CLI、`lark-cli` 和飞书权限状态；在普通代码改动中，默认先跑单测。只有变更安装链路或本机联调时才执行安装脚本。

## 测试约定

- 测试使用标准库 `unittest`，测试文件位于 `tests/test_*.py`。
- 新增状态、命令、runner、source resolver、report gate 或用户可见文案时，应补充相邻测试。
- 变更父级需求拆解、materialize、delivery status 或 run --next 行为时优先扩展 `tests/test_delivery_service.py` 和 `tests/test_delivery_flow.py`。
- 变更飞书 Project/Docx/Wiki 来源索引、deferred source、source context 修复或 plan 阶段来源读取权限时，优先扩展 `tests/test_source_flow.py`、`tests/test_source_plan_flow.py` 和相邻 source contract tests。
- 变更 `SourcePort`、`SourceResult`、`SourceResolver.resolve_source_result()` 或 source 状态归一化时，优先扩展 `tests/test_ports_contract.py`、`tests/test_source_resolver.py` 和 `tests/test_orchestrator_tools.py`。
- 变更 Feishu Docx/Wiki gateway 读取、`lark-cli docs +fetch`、auth refresh retry 或文档 payload 归一化时，优先扩展 `tests/test_feishu_document_reader.py`；变更 Feishu Project work item gateway/OpenAPI env 读取时，优先扩展 `tests/test_feishu_work_item_reader.py`；变更 Feishu/Meegle work item payload 归一化、raw_fields 或 summary shape 时，优先扩展 `tests/test_source_work_item_context.py`；`tests/test_feishu_project_reader.py` 只保留 Project/文档来源路由兼容覆盖。
- 变更 plan-only run、计划完成通知、只读 gate 或 run summary 写入时，优先扩展 `tests/test_plan_run_flow.py` 和相邻 `RunService` / prompt contract tests。
- 变更 implementation 结果映射、workspace/branch 策略、session 复用、confirmed plan prompt 或 inline implementation 策略时，优先扩展 `tests/test_implementation_result_flow.py`、`tests/test_implementation_workspace_flow.py`、`tests/test_implementation_session_flow.py` 和相邻 runner / status policy tests。
- 变更 `/coding run`、`/coding implement`、后台启动拒绝或已完成任务 run gate 时，优先扩展 `tests/test_command_run_flow.py` 和相邻 `RunService` tests。
- 变更后台 run 线程启动、sender 调度、reply fallback、失败通知模板或 completion notification record 时，优先扩展 `tests/test_background_run_notifier.py`，再按影响范围扩展 `tests/test_plan_run_flow.py`、`tests/test_qa_flow.py`、`tests/test_merge_test_qa_gate_flow.py` 或 `tests/test_command_run_flow.py`。
- 变更后台 run 等待完成、后台启动失败状态收敛、merge-test `human_required` 转 pending action 或对应 orchestrator wrapper 时，优先扩展 `tests/test_run_background_orchestration.py`，再按影响范围扩展 `tests/test_plan_run_flow.py`、`tests/test_command_run_flow.py`、`tests/test_status_reconcile_flow.py`、`tests/test_qa_flow.py` 或 `tests/test_merge_test_qa_gate_flow.py`。
- 变更 run start selection projection，也就是 run context source、QA/merge-test checkpoint 选择、checkpoint failed 判定、QA evidence observation、source branch recording、project path requirement、workspace selection 或 manifest checkpoint preparation selection 时，优先扩展 `tests/test_run_start_selection_projection.py`，再按兼容影响扩展 `tests/test_run_orchestration_start_rules.py` 或 `tests/test_run_orchestration_workspace_rules.py`。变更 `report.schema.json`、`input-prompt.md` 或 `run-manifest.json` 启动 artifact 文件写入时，优先扩展 `tests/test_run_start_artifact_service.py`，再按影响范围扩展 `tests/test_plan_run_flow.py`、`tests/test_source_plan_flow.py`、`tests/test_implementation_session_flow.py`、`tests/test_qa_flow.py` 或 `tests/test_merge_test_basic_flow.py`；变更 `run-manifest.json` artifact 写回边界时，优先扩展 `tests/test_run_manifest_artifact_service.py`，再按影响范围扩展 `tests/test_implementation_session_flow.py`、`tests/test_implementation_workspace_flow.py`、`tests/test_qa_flow.py` 或 `tests/test_merge_test_basic_flow.py`；变更 `stderr.log` artifact 写回边界时，优先扩展 `tests/test_run_stderr_artifact_service.py`，再按影响范围扩展 `tests/test_run_failure_report_projection.py`、`tests/test_run_orchestration_start_rules.py`、`tests/test_qa_flow.py` 或 `tests/test_merge_test_basic_flow.py`；变更 `report.json` artifact 写回边界时，优先扩展 `tests/test_run_report_artifact_service.py`，再按影响范围扩展 `tests/test_status_reconcile_flow.py`、`tests/test_plan_run_flow.py`、`tests/test_source_plan_flow.py`、`tests/test_implementation_session_flow.py`、`tests/test_qa_flow.py` 或 `tests/test_merge_test_basic_flow.py`；变更 `summary.md` artifact 读写边界时，优先扩展 `tests/test_run_summary_artifact_service.py`，再按影响范围扩展同一组 run/status/QA/merge-test flow。
- 变更 runner/checkpoint failure report payload 时，优先扩展 `tests/test_run_failure_report_projection.py`，并按兼容影响扩展 `tests/test_run_orchestration_start_rules.py`。变更 diff guard / implementation commit missing blocked report 构造或 run report refinement projection 时，优先扩展 `tests/test_run_report_refinement_projection.py`，并按兼容影响扩展 `tests/test_run_orchestration_start_rules.py`。变更 plan report session fields / writeback、run start base/workspace session update、active run session update、runner session update 或 completion session update 时，优先扩展 `tests/test_run_session_projection.py`，兼容 re-export 行为再扩展 `tests/test_run_orchestration_plan_report_session.py` 或 `tests/test_run_orchestration_start_rules.py`。变更首次/增量 prompt 构造选择和参数合同时，优先扩展 `tests/test_run_prompt_projection.py`，再按影响范围扩展 `tests/test_prompt_templates.py`、`tests/test_plan_run_flow.py` 或 `tests/test_implementation_session_flow.py`。变更 wiki context、confirmed plan / implementation context、assembled context、run instructions、execution policy 或 context index 文件写入时，优先扩展 `tests/test_run_context_artifact_service.py`，再按影响范围扩展 `tests/test_prompt_templates.py`、`tests/test_plan_run_flow.py`、`tests/test_implementation_session_flow.py`、`tests/test_status_reconcile_flow.py` 或 `tests/test_qa_flow.py`。变更 start_run 或 active run reconcile 的 artifact / agent_run / merge-test record 写回 payload 聚合时，优先扩展 `tests/test_run_ledger_projection.py`，再按影响范围扩展 `tests/test_implementation_session_flow.py`、`tests/test_qa_flow.py`、`tests/test_merge_test_basic_flow.py` 或 `tests/test_status_reconcile_flow.py`；实际 ledger append/upsert 仍由 orchestrator host 边界或后续专用 service 承担。变更 observed run report、stale completion 观测、execution policy decision 读取、run-level diff guard violations 组合、verification limitations fallback projection、completion report payload、agent run record 构造、reconciled agent run record 构造、reconcile result payload 构造、existing run mode/changed files 规则、merge-test run record 构造、project writeback payload 构造、start_run result payload 构造、run completion 状态/phase/report 投影或 run orchestration helper wrapper 时，优先扩展 `tests/test_run_orchestration_service.py`；start_run 观测、blocked/refinement wrapper、execution policy decision 读取、run-level diff guard violations 组合规则和 verification limitations fallback projection 优先扩展 `tests/test_run_orchestration_start_rules.py`，existing run reconcile 规则优先扩展 `tests/test_run_orchestration_reconcile_rules.py`，再按影响范围扩展 `tests/test_bugfix_writeback_flow.py`、`tests/test_plan_run_flow.py`、`tests/test_command_run_flow.py`、`tests/test_status_reconcile_flow.py`、`tests/test_qa_flow.py` 或 `tests/test_merge_test_qa_gate_flow.py`。
- 变更 completed run 或 active run reconcile 的 run summary writer payload 聚合时，优先扩展 `tests/test_run_summary_projection.py`，再按影响范围扩展 `tests/test_plan_run_flow.py` 或 `tests/test_status_reconcile_flow.py`；summary artifact 读取归属 `run_summary_artifact_service.py`，实际 LLM Wiki 写入仍由 `RunSummaryWriter` / `KnowledgePort` 和 orchestrator host 边界承担。
- 变更 fresh run_dir 或 existing run record 的 `ArtifactSet` 路径合同时，优先扩展 `tests/test_run_artifact_paths.py`，再按影响范围扩展 `tests/test_status_reconcile_flow.py`、`tests/test_run_report_artifact_service.py`、`tests/test_run_summary_artifact_service.py` 或 `tests/test_plan_run_flow.py`；实际 artifact 文件读写、ledger append/upsert 和状态推进仍由对应 artifact service / orchestrator host 边界承担。
- 变更 gateway 命令组、`/coding commands`、doctor 拦截或 coding group dispatch 时，优先扩展 `tests/test_gateway_command_group_flow.py`。
- 变更 Gateway event source、binding key、active task、coding mode、active project、pending rewrite/action 或 stale binding cleanup 时，优先扩展 `tests/test_gateway_binding_service.py`，再按影响范围扩展 gateway flow 测试。
- 变更显式 `/coding` / `/commands` parsing、`/coding` command normalization、project subcommand 映射、命令 route plan、handler key、reply mode、task id 来源策略、merge-test flag/task id 解析、rewrite canonical command、确认/取消回复分类、rewrite confirmation gate、plugin-generated message 过滤、Gateway event dedupe 或授权探测时，优先扩展 `tests/test_gateway_command_controller.py`，再按影响范围扩展 gateway flow 测试。
- 变更 Gateway custom route 分发、task/run/delivery/implementation/QA/prepare/merge-test handler selection 或 route metadata 到 host action 的映射时，优先扩展 `tests/test_gateway_command_executor.py`，再按影响范围扩展 `tests/test_gateway_command_group_flow.py`、`tests/test_command_run_flow.py`、`tests/test_merge_test_basic_flow.py`、`tests/test_merge_test_blocked_flow.py` 或 `tests/test_merge_test_qa_gate_flow.py`。
- 变更 Gateway pending action 确认/取消、latest human_required merge-test fallback、取消任务 gate 或确认后显式命令续接时，优先扩展 `tests/test_gateway_pending_action_executor.py`，再按影响范围扩展 `tests/test_gateway_pending_confirmation_flow.py`、`tests/test_cancel_restore_flow.py`、`tests/test_merge_test_blocked_flow.py`、`tests/test_merge_test_qa_gate_flow.py` 或 `tests/test_gateway_rewrite_flow.py`。
- 变更 implementation workspace 复用/创建、source branch/base branch、QA artifact 收集、clean-tree checkpoint、git HEAD 或 diff guard QA artifact 过滤时，优先扩展 `tests/test_workspace_checkpoint_service.py`，再按影响范围扩展 `tests/test_implementation_workspace_flow.py`、`tests/test_qa_flow.py` 或 `tests/test_merge_test_qa_gate_flow.py`。
- 变更 run-manifest 基础字段、启动期 manifest update projection、artifact record、Codex attach/resume 展示命令、manifest session metadata 字段投影与文件回写、controlled bypass 权限 profile 或 source elevated plan 权限判断时，优先扩展 `tests/test_run_manifest_service.py`，再按影响范围扩展 `tests/test_implementation_session_flow.py`、`tests/test_plan_run_flow.py`、`tests/test_source_plan_flow.py`、`tests/test_qa_flow.py` 或 `tests/test_merge_test_basic_flow.py`。
- 变更项目上下文、active project、项目目录识别、Feishu escaped project slug 或项目澄清时，优先扩展 `tests/test_gateway_project_task_flow.py`。
- 变更 active project 应用到 task、project context 回填或对应 human decision 记录时，优先扩展 `tests/test_gateway_active_context.py`，再按影响范围扩展 `tests/test_gateway_project_task_flow.py`、`tests/test_gateway_natural_language_command_flow.py` 或 `tests/test_command_run_flow.py`。
- 变更计划确认、确认过早、`/coding use`、`/coding delete` 或近期 planned task continue 行为时，优先扩展 `tests/test_gateway_task_control_flow.py`。
- 变更 bugfix/change/continue feedback、带图反馈或 failed plan-only restart 行为时，优先扩展 `tests/test_gateway_feedback_flow.py` 和 `tests/test_gateway_change_continue_flow.py`。
- 变更 plugin-generated message 忽略、stale run completion 或无任务强确认拦截时，优先扩展 `tests/test_gateway_safety_lifecycle_flow.py`。
- 变更状态展示、active background run reconcile、implementation not landed reconcile 或 execution policy 写入时，优先扩展 `tests/test_status_reconcile_flow.py`。
- 变更 bugfix 完成后的飞书 Project comment/writeback 时，优先扩展 `tests/test_bugfix_writeback_flow.py` 和 `tests/test_workitem_service.py`。
- 变更手动 QA、QA artifact 收集、QA clean-tree gate 或实现完成后的 QA 提示时，优先扩展 `tests/test_qa_flow.py` 和相邻 `RunService` / prompt contract tests。
- 变更 prepare/merge-test 状态提示、blocked/QA 风险确认、风险放行说明或 merge-test 启动 ACK 文案时，优先扩展 `tests/test_merge_test_presenter.py`，再按影响范围扩展 `tests/test_merge_test_basic_flow.py`、`tests/test_merge_test_blocked_flow.py`、`tests/test_merge_test_qa_gate_flow.py` 或 `tests/test_gateway_natural_language_command_flow.py`。
- 变更 merge-test 手动触发、blocked readiness、QA 风险 gate 或 merge-test 前 clean-tree gate 的状态/策略逻辑时，优先扩展 `tests/test_merge_test_basic_flow.py`、`tests/test_merge_test_readiness_flow.py`、`tests/test_merge_test_blocked_flow.py`、`tests/test_merge_test_qa_gate_flow.py` 和相邻状态策略测试。
- 变更 merged-test 后人工完成、`/coding list` 展示或 complete/list 文案时，优先扩展 `tests/test_completion_flow.py` 和相邻状态策略测试。
- 变更 plan-only/implementation/QA 启动 ACK、active run 重复启动提示或 cannot-start 恢复提示时，优先扩展 `tests/test_run_start_presenter.py`，再按影响范围扩展 `tests/test_command_run_flow.py`、`tests/test_plan_run_flow.py`、`tests/test_qa_flow.py` 或 `tests/test_run_service.py`。
- 变更 `/coding continue/change/bugfix` 反馈、需求变更、图片未捕获或人工澄清用户可见文案时，优先扩展 `tests/test_feedback_presenter.py`，再按影响范围扩展 `tests/test_gateway_feedback_flow.py`、`tests/test_gateway_change_continue_flow.py`、`tests/test_gateway_task_control_flow.py` 或 `tests/test_gateway_natural_language_command_flow.py`。
- 变更 Coding Mode rewrite 确认、低置信度补充或 handoff 用户可见文案时，优先扩展 `tests/test_gateway_rewrite_presenter.py`，再按影响范围扩展 `tests/test_gateway_rewrite_flow.py`、`tests/test_gateway_pending_confirmation_flow.py` 或 `tests/test_gateway_natural_language_command_flow.py`。
- 变更 `/coding list` 任务摘要、项目/描述标签、`/coding status` 详情、Kanban/完成回传/QA 缺口展示或 run completion 用户可见消息时，优先扩展 `tests/test_task_list_presenter.py`、`tests/test_task_status_presenter.py`、`tests/test_run_completion_presenter.py`，再按影响范围扩展 `tests/test_status_reconcile_flow.py`、`tests/test_completion_flow.py`、`tests/test_plan_run_flow.py`、`tests/test_implementation_result_flow.py` 或 `tests/test_gateway_safety_lifecycle_flow.py`。
- 变更任务取消、误取消恢复、已取消任务继续/变更/bugfix 拒绝或取消确认文案时，优先扩展 `tests/test_cancel_restore_flow.py` 和相邻状态机测试。
- 变更 skill core 或 Hermes binding 时优先扩展 `tests/test_plugin_registration.py`，确保 core 不含 host 细节、Hermes binding 仍注册且只做映射。
- 变更 `orchestrator.py` 时先按行为域查找相邻 flow 小文件；只有端到端 smoke、kanban transition、plan-only resume sandbox 或无法归类的 façade 行为才扩展 `tests/test_orchestrator_run_flow.py`，工具层扩展 `tests/test_orchestrator_tools.py`，Gateway 触发入口扩展 `tests/test_gateway_trigger.py`。
- 变更安装链路时优先查找并扩展 `tests/test_install.py`、`tests/test_docs_and_install_entry.py`。
- 变更 report contract 或 runner 输出时优先查找并扩展 `tests/test_report_contract.py`、`tests/test_report_admission.py`、`tests/test_codex_report*.py`、`tests/test_codex_cli_report_facade.py` 和 `tests/test_codex_cli_report_failure_facade.py`；变更 Codex command/process façade 时扩展 `tests/test_codex_cli_command_facade.py` 或 `tests/test_codex_cli_process_facade.py`。

## 发布与运行约束

- 本项目当前只支持本地软链接安装到 Hermes：`~/.hermes/plugins/coding_orchestration -> 当前仓库/coding_orchestration`。
- 插件更新后必须重启 Hermes Gateway；Gateway 不会热加载 Python 插件代码。
- `implementation`、`QA`、`merge-test` 可使用受控高权限 Codex CLI session，但源码修改应落在任务 workspace；项目外写入只允许依赖缓存、git metadata、dev server/browser 临时文件和 QA artifact。
- `plan-only` 无论是否需要读取外部来源，都不应修改项目文件；diff guard 应阻断 plan 阶段写入。
- `merge-test` 和发布仍是人工触发，不由普通 implementation 自动发布或部署。

## 文档约定

- `AGENTS.md` 只做导航和 hard stops。
- `docs/project-map.md`、`docs/conventions.md`、`docs/component-contract.md` 是人类可读项目事实入口。
- `contracts/project-context.yaml` 是 machine-readable 项目事实，不承载 agent topology、角色拆分或执行顺序。
- `docs/deployment.md`、`docs/plugin-prerequisites.md`、`docs/plans/`、状态机/交付流文档属于项目沉淀，可以提交。
- superpowers 生成的执行计划统一放在 `docs/plans/`，不要再分散到 `docs/superpowers/`、`docs/local/superpowers*` 或 `docs/` 根目录。
- 宣讲、demo、分享材料放在 `docs/local/presentations/`；该目录被忽略，不作为 canonical 项目事实来源。
- 历史计划、流程图和阶段性报告不要复制进 canonical 文档；只在需要背景时按链接读取。
