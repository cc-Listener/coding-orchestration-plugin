# Hermes Coding 解耦架构设计

## 背景

当前 `coding_orchestration` 已经跑通 Hermes Gateway、`/coding` 命令、Task Ledger、LLM Wiki、Codex runner、飞书 Project MCP 和飞书通知闭环。但系统的主要风险已经从“能否跑通”转为“能否长期迭代”：

- `coding_orchestration/orchestrator.py` 超过 8000 行，承担命令解析、状态推进、MCP 写入、runner 调度、通知渲染和后台线程管理。
- Hermes host、MCP transport、Codex CLI、飞书来源读取、状态字符串、路径和命令默认值散落在业务流程中。
- Skill 直接表达 `/coding`、Hermes、Task Ledger 和状态细节，难以迁移到 MCP Skill 或其他 host。
- 旧测试大量绑定实现细节和旧耦合形态，后续拆分时会阻碍架构收敛。

本设计目标是把现有插件从“一个大 Hermes 插件对象”演进为“核心域 + 应用服务 + 端口 + 适配器 + Hermes 插件壳”。Hermes 仍然是当前交付 host，但不再是核心域的依赖。

## 目标

1. 核心 task/run/source/report/workitem 逻辑不 import Hermes、MCP transport、CLI subprocess、`Path.home()` 或 host-specific skill。
2. Hermes 插件只做集成：注册 hook、command、tool、skill，转换 host event，调用应用服务。
3. MCP Skill 和工具端通过稳定 ToolSpec / IntentSpec / Port contract 对接，不直接持有 Hermes 细节。
4. 大文件按职责拆分，后续新增能力有明确归属，不继续堆进 orchestrator。
5. hard code 集中进入配置、常量、状态策略或 adapter binding，不能散落在核心流程里。
6. 改造完成后主流程继续跑通：创建任务、生成计划、确认实现、QA、merge-test、complete。
7. 旧测试按“保留行为覆盖、删除实现耦合、补 contract tests”的原则清理。

## 非目标

- 不改变 plan-only 只读语义。
- 不自动发布或部署。
- 不把飞书 token、Hermes auth、Codex auth、`.env*` 或运行根内容写入仓库。
- 不一次性产品化为独立 package；先在当前仓库内形成可迁移边界。
- 不为了拆文件引入平行实现。迁移期允许 façade，但最终业务逻辑只能有一个权威入口。

## 现状证据

| 文件 | 行数 | 当前问题 |
| --- | ---: | --- |
| `coding_orchestration/orchestrator.py` | 4777 | 编排、MCP 和运行副作用仍混在一个类，但 task/run/workitem/status/prompt/delivery 已开始 façade 化；Gateway controller/executor、presenter、background notifier、workspace checkpoint、run manifest/session/start selection/prompt/context artifact/start artifact/report/summary/stderr/manifest artifact service、run diff guard observation service、run dispatch host service、run status transition host service、run evidence observation host service、run session/ledger/summary writeback projection/writeback host service、run artifact path projection、run project writeback host service、failure/refinement projection 和多类 run payload projection 已迁出。当前只应继续保留 host dispatch、剩余 run lifecycle 接线、artifact 读写和兼容 wrapper，并逐步降到 3000 行以内。 |
| `coding_orchestration/gateway_command_controller.py` | 364 | Gateway `/coding` command controller 纯规则，承接显式 `/coding` / `/commands` 解析、命令归一化、命令 route plan、handler key、reply mode、task id 来源策略、merge-test 参数解析、rewrite canonical command、确认/取消词分类、rewrite 风险确认、plugin echo 过滤、Gateway event dedupe key 和授权探测；orchestrator 只保留基于 route metadata 的 immediate dispatch、custom executor 委托和兼容 wrapper |
| `coding_orchestration/gateway_command_executor.py` | 230 | Gateway custom route host shell，消费 controller route metadata，承接 task/run/delivery/implementation/QA/prepare/merge-test 分发；通过 orchestrator façade/callback 触发现有副作用，后续再继续下沉到 RunService/DeliveryService 等应用服务 |
| `coding_orchestration/gateway_pending_action_executor.py` | 73 | Gateway pending action host shell，承接待确认动作的确认/取消回复、latest human_required merge-test fallback、取消任务 gate 和确认后显式命令续接；通过 orchestrator façade/callback 调用 binding、ledger、消息回复和显式命令执行 |
| `coding_orchestration/gateway_active_context.py` | 35 | Gateway active context host helper，承接 active project 应用到缺项目 task 的 project context 回填和 human decision 记录；binding 存取仍归属 `gateway_binding_service.py` |
| `coding_orchestration/doctor_presenter.py` | 335 | doctor、preflight、source-resolve 用户可见文案 presenter，承载 host 恢复命令和配置引用 |
| `coding_orchestration/gateway_rewrite_presenter.py` | 107 | Coding Mode rewrite 确认、低置信度补充和 handoff 用户可见文案 presenter，orchestrator 只保留上下文收集和兼容委托 |
| `coding_orchestration/run_start_presenter.py` | 83 | plan-only/implementation/QA 启动 ACK、active run 重复启动和 cannot-start 恢复提示 presenter，RunService 只保留状态判断和 fallback |
| `coding_orchestration/feedback_presenter.py` | 75 | `/coding continue/change/bugfix` 反馈、需求变更、图片未捕获和人工澄清用户可见文案 presenter，orchestrator 只保留记录决策与启动 run 的控制流 |
| `coding_orchestration/merge_test_presenter.py` | 102 | prepare/merge-test 状态提示、blocked 风险确认、风险放行说明、QA 风险确认和启动 ACK presenter，orchestrator 只保留 readiness 评估、状态切换和风险接受记录 |
| `coding_orchestration/workspace_checkpoint_service.py` | 184 | Workspace/Git checkpoint helper，承接 implementation workspace 复用/创建、source branch/base branch、QA artifact 收集、clean-tree checkpoint、git HEAD 和 QA artifact diff 过滤；orchestrator 只保留 runner 调度、状态映射和兼容 wrapper |
| `coding_orchestration/run_manifest_service.py` | 355 | Run manifest/session policy helper，承接 run-manifest 基础字段、启动期 manifest update projection、artifact record、Codex attach/resume 展示命令、manifest session metadata 字段投影与文件回写、controlled bypass 权限 profile、source elevated plan 权限判断；orchestrator 只保留上下文收集、checkpoint 准备、manifest 文件写入、runner 调度、状态映射和兼容 wrapper |
| `coding_orchestration/run_background_orchestration.py` | 99 | 后台 run host orchestration helper，承接后台 queued/running 等待完成、后台启动失败状态收敛、merge-test `human_required` 转会话级 pending action；通过 orchestrator façade 调用 ledger、reconcile、report 读取和 binding 写入，不承载 runner subprocess、Gateway 发送或 workspace/git 副作用 |
| `coding_orchestration/run_failure_report_projection.py` | 104 | Run failure report projection helper，承接 runner 启动异常和 QA/merge-test checkpoint 失败的结构化 report payload；不写 artifact、不包装 `RunResult`、不启动 runner |
| `coding_orchestration/run_report_refinement_projection.py` | 136 | Run report refinement projection helper，承接 diff guard / implementation commit missing blocked report 构造、observed report status/details refinement 和 implementation dirty-check 信号；不执行 diff guard、不判断 workspace dirty、不写 report、不推进 ledger |
| `coding_orchestration/run_diff_guard_service.py` | 46 | Run diff guard observation host service，承接 before snapshot、changed files 观测、QA report artifact 过滤、policy violations 组合、plan-only 写入 violations 补充和 diff summary 写回；不写 ledger/report/manifest/summary、不启动 runner、不推进状态 |
| `coding_orchestration/run_dispatch_service.py` | 46 | Run dispatch host service，承接 checkpoint failure gate、`runner.run()` 调度和 runner exception fallback；只调用注入 runner 与失败 result callback，不写 ledger/report/manifest/summary、不执行 diff guard、不收集 QA evidence、不推进状态 |
| `coding_orchestration/run_status_transition_service.py` | 167 | Run status transition host service，承接状态机、status/phase/Kanban callback、run start/completion/reconcile transition 和 active run cleanup；通过注入 callback 工作，不写 report/manifest/summary、不启动 runner、不执行 diff guard、不收集 QA evidence |
| `coding_orchestration/run_evidence_observation_service.py` | 41 | Run evidence observation host service，承接 QA artifacts、tested commit 和 implementation dirty-check observation；只调用注入 callback，不写 ledger/report/manifest/summary、不创建 checkpoint、不启动 runner、不推进状态 |
| `coding_orchestration/run_start_selection_projection.py` | 101 | Run start selection projection helper，承接 context source、checkpoint selection、QA evidence observation、source branch recording、project path requirement、workspace selection 和 manifest checkpoint preparation selection 纯规则；不读取 workspace、不准备 checkpoint、不写 manifest、不推进 ledger |
| `coding_orchestration/run_session_projection.py` | 149 | Run session projection helper，承接 plan report session fields 白名单、plan report session update、run start base/workspace session update、active run session update、runner session update 和 completion session update 纯 payload；不写 ledger、不生成 attach command、不读 artifact、不推进状态 |
| `coding_orchestration/run_session_writeback_service.py` | 16 | Run session writeback host service，承接 start_run、start_run 异常清理与 active run reconcile 的 task session callback；只消费 session projection 已构造的 update dict 并调用注入 callback，空 update 跳过；不构造 payload、不直接 import `TaskLedger` / storage repository、不写 artifact、不启动 runner、不推进状态 |
| `coding_orchestration/run_prompt_projection.py` | 52 | Run prompt projection helper，承接首次 prompt 与增量 prompt 构造选择和参数合同；只调用传入的 PromptBuilder 生成字符串，不写 `input-prompt.md`、不生成 context artifact、不写 manifest、不启动 runner、不推进 ledger |
| `coding_orchestration/run_context_artifact_service.py` | 136 | Run context artifact service，承接 wiki context、confirmed plan / implementation context、assembled context、run instructions、execution policy 和 context index 写入，并读取 `execution-policy.json`；只触达 run_dir 下 context artifact，不写 ledger、manifest、report、summary，不启动 runner、不推进状态 |
| `coding_orchestration/run_start_artifact_service.py` | 41 | Run start artifact service，承接 `report.schema.json`、`input-prompt.md` 和 `run-manifest.json` 启动 artifact 写入；只写 run_dir 下启动 artifact，不准备 checkpoint、不写 ledger/report/summary、不启动 runner、不推进状态 |
| `coding_orchestration/run_manifest_artifact_service.py` | 24 | Run manifest artifact service，承接指定 `run-manifest.json` 写回；不写 report/summary/ledger，不启动 runner、不推进状态 |
| `coding_orchestration/run_stderr_artifact_service.py` | 11 | Run stderr artifact service，承接指定 `stderr.log` 写回；不写 report/summary/manifest/ledger，不启动 runner、不推进状态 |
| `coding_orchestration/run_report_artifact_service.py` | 35 | Run report artifact service，承接指定 `report.json` 读写和 `summary_markdown` excerpt；缺失或无效读取返回空 dict / 空摘要，不写 manifest/summary/ledger，不启动 runner、不推进状态 |
| `coding_orchestration/run_summary_artifact_service.py` | 17 | Run summary artifact service，承接指定 `summary.md` 读写；不生成 summary，不写 report/manifest/ledger，不启动 runner、不推进状态 |
| `coding_orchestration/run_ledger_projection.py` | 103 | Run ledger writeback projection，承接 start_run 与 active run reconcile 的 artifact / agent_run / fresh merge-test record 写回 payload 聚合；只返回纯数据，不调用 ledger、不写 artifact、不启动 runner、不推进状态 |
| `coding_orchestration/run_ledger_writeback_service.py` | 32 | Run ledger writeback host service，承接 completed run 与 active run reconcile 的 ledger callback；只消费 ledger projection records 并调用注入 callback，不构造 payload、不直接 import `TaskLedger` / storage repository、不写 artifact、不启动 runner、不推进状态 |
| `coding_orchestration/run_summary_projection.py` | 65 | Run summary writeback projection，承接 completed run 与 active run reconcile 的 LLM Wiki run summary writer payload 聚合；只返回纯数据，不读取 summary artifact、不调用 summary writer、不写 LLM Wiki、不写 ledger、不推进状态 |
| `coding_orchestration/run_summary_writeback_service.py` | 57 | Run summary writeback host service，承接 completed run 与 active run reconcile 的 summary writer callback；复用 summary projection，只调用注入 writer，不读取 artifact、不写 ledger、不启动 runner、不推进状态 |
| `coding_orchestration/run_artifact_paths.py` | 52 | Run artifact path projection，承接 fresh run_dir 和 existing run record 的 `ArtifactSet` 路径合同；只返回路径，不读写 artifact 文件、不创建目录、不写 ledger、不启动 runner、不推进状态 |
| `coding_orchestration/run_project_writeback_service.py` | 34 | Run project writeback host service，承接 completed run 的 Project/WorkItem writeback stale gate、payload 构造委托和注入 callback 调用；不直接 import WorkItemService/MCP adapter、不写 ledger/artifact、不启动 runner、不推进状态 |
| `coding_orchestration/run_orchestration_service.py` | 419 | Run orchestration 迁移期 application helper，承接 observed run report 构造、stale completion 观测、execution policy decision 读取、run-level diff guard violations 组合、verification limitations fallback projection、completion report payload 构造、agent run record 构造、reconciled agent run record 构造、merge-test run record 构造、project writeback payload 构造、start_run result payload 构造和 run completion 状态/phase/report 投影；兼容 re-export run failure report、run report refinement、run start selection、run session 与 run prompt projection helper；不承载 runner subprocess、Gateway 发送、workspace/git 副作用或后台 host orchestration |
| `coding_orchestration/task_list_presenter.py` | 63 | `/coding list` 任务项目和描述摘要 presenter，orchestrator 只保留兼容委托 |
| `coding_orchestration/task_status_presenter.py` | 132 | `/coding status` 任务状态详情 presenter，集中处理 Kanban 同步、完成回传、QA report、QA health score 和 known gaps 展示 |
| `coding_orchestration/run_completion_presenter.py` | 231 | plan/implementation/QA/merge-test/stale run 完成消息 presenter，集中处理 report 摘要、next actions、risk note 和 artifact fallback |
| `coding_orchestration/runners/codex_cli.py` | 375 | command build、process runner、report policy、report loader、report writer 和 artifact contract 已拆出，主类保留 runner façade 和 Hermes runtime 启动入口 |
| `coding_orchestration/project_knowledge_initializer.py` | 30 | 项目知识初始化兼容 façade，只保留 bootstrap 和旧导入路径 |
| `coding_orchestration/project_knowledge_inventory.py` | 413 | 仓库扫描、文件分类、敏感路径识别、技术栈/包管理器/验证命令推断 |
| `coding_orchestration/project_knowledge_documents.py` | 378 | LLM Wiki project profile、guidance、architecture、tooling、risk 等文档生成 |
| `coding_orchestration/ledger.py` | 222 | 兼容 façade，保留既有公开方法并委托 storage repositories |
| `coding_orchestration/storage/repositories.py` | 25 | 兼容 re-export，具体 SQL mutation 已拆到 task/run/artifact/binding repository |
| `coding_orchestration/knowledge_adapter.py` | 76 | KnowledgePort 本地实现，封装 LLM Wiki 读写和 run summary persistence |
| `coding_orchestration/llm_wiki_adapter.py` | 557 | 本地 LLM Wiki Markdown layout 实现，已不再承载 run summary 业务格式 |
| `coding_orchestration/source_links.py` | 77 | Feishu Project、Feishu Docx/Wiki 和 Meegle URL/identity 纯解析模块 |
| `coding_orchestration/source_recovery.py` | 121 | Feishu Docx/Wiki 和 Meegle deferred recovery payload、CLI command shape 纯映射模块 |
| `coding_orchestration/feishu_project_reader.py` | 188 | 来源路由兼容 façade；URL parsing 已迁到 `source_links.py`，错误恢复 payload 已迁到 `source_recovery.py`，Docx/Wiki reader 已迁到 `feishu_document_reader.py`，Project work item reader 已迁到 `feishu_work_item_reader.py` |
| `coding_orchestration/source_work_item_context.py` | 180 | Feishu/Meegle work item payload、raw_fields 和 summary shape 纯归一化合同 |
| `coding_orchestration/feishu_work_item_reader.py` | 150 | Feishu Project work item gateway/OpenAPI env 读取 adapter |
| `coding_orchestration/meegle_reader.py` | 151 | Meegle gateway/CLI reader adapter，work item payload 归一化委托给 `source_work_item_context.py` |

hard code 类型包括：

- 运行路径：`~/.hermes/coding-orchestration`、`~/.hermes/.env`。
- 外部命令：`rtk lark-cli`、`npx -y @lark-project/mcp`、Codex CLI command。
- Host 语义：`/coding`、Hermes Gateway、Hermes skill path。
- 状态字符串：`ready_for_merge_test_with_known_gaps`、`implementation_not_landed`、`permission_missing`。
- 飞书域名和 token key：`https://project.feishu.cn`、`MCP_USER_TOKEN`。
- Prompt 文案中的 Hermes/Codex 绑定说明。

## 目标架构

```text
coding_core
  domain
    Task / Run / Source / WorkItem / Report / State / Policy
  services
    TaskService / RunService / DeliveryService / WorkItemService
  contracts
    ToolSpec / IntentSpec / ReportSchema / EventEnvelope
  ports
    HostPort / RunnerPort / SourcePort / WorkItemPort
    LedgerPort / KnowledgePort / NotifierPort / RuntimePort

coding_integrations
  hermes
    plugin registration / command adapter / tool adapter / skill binding
  runners
    Codex CLI / Hermes terminal Codex / Generic CLI
  sources
    lark-cli / Feishu Docx-Wiki / Meegle
  workitems
    Feishu Project MCP adapter
  storage
    SQLite Task Ledger / Local LLM Wiki

coding_orchestration
  compatibility facade
  existing import path preservation
```

第一阶段可以不立刻创建顶层 `coding_core/` 包，但代码边界必须按上述层次组织。迁移期 `CodingOrchestrator` 作为兼容 façade 保留，逐步把实现委托到应用服务。

## 职责边界

### Core Domain

负责稳定业务概念和确定性规则：

- task/run/source/workitem/report 数据模型。
- run mode、task status、phase、状态转换。
- report contract 和 admission gate。
- diff guard 输入输出 contract。
- ToolSpec / IntentSpec。

Core Domain 不允许：

- import Hermes、MCP client、subprocess runner。
- 读取 env、`Path.home()`、`.env`。
- 拼接 `/coding` 命令。
- 直接读写 SQLite 或 LLM Wiki 文件。
- 直接使用飞书域名、token key 或 lark-cli 命令。

### Application Services

负责用 core domain 编排用例：

- `TaskService`：创建任务、继续任务、变更、bugfix、状态查询。
- `RunService`：plan-only、implementation、QA、merge-test run 生命周期。
- `DeliveryService`：breakdown、approve、materialize、parent-child 进度。
- `WorkItemService`：飞书 Project Story / Issue / WBS / 状态流转的业务用例。
- `HealthService`：doctor、preflight、readiness 汇总。

应用服务只依赖 ports，不依赖具体 adapter。

### Ports

端口是长期稳定合同：

- `HostPort`：发送消息、获取会话、注册/映射 host 能力。
- `RunnerPort`：启动、续接、取消、收集 artifacts。
- `SourcePort`：索引来源、读取来源、检查 source readiness。
- `WorkItemPort`：搜索/创建/更新外部项目工作项。
- `LedgerPort`：任务、运行、artifact、binding 的持久化。
- `KnowledgePort`：项目画像和 run summary 读写。
- `NotifierPort`：将领域结果渲染成用户可见消息。
- `RuntimePort`：后台进程、终端、文件系统边界能力。

### Adapters

adapter 可以知道外部系统细节，但必须把细节压到端口后面：

- Hermes adapter 知道 `ctx.register_hook`、`ctx.register_command`、`ctx.register_tool`、`ctx.register_skill`。
- Feishu MCP adapter 知道 JSON-RPC、stdio、`MCP_USER_TOKEN`、tool allowlist、脱敏。
- Codex adapter 知道 Codex CLI command、sandbox flag、resume、report artifact。
- Lark adapter 知道 `rtk lark-cli`、scope、appId 校验。
- SQLite Ledger adapter 知道 schema 和 migration。
- Local LLM Wiki adapter 知道本地 markdown layout。

## 工具端解耦

工具能力先定义为 host-agnostic `ToolSpec`：

```text
ToolSpec
  name
  description
  input_schema
  operation_id
  safety_level
  host_visibility
```

Hermes native tools 由 Hermes adapter 从 `ToolSpec` 注册。MCP Skill 或未来 MCP server 也从同一份 `ToolSpec` 暴露能力。handler 只做：

```text
host payload -> operation_id + normalized args -> ApplicationService -> host response
```

禁止 tool registration 直接引用 `CodingOrchestrator.tool_*`。

## MCP 解耦

核心域只认 `WorkItemPort`：

```text
search_workitems(query)
create_workitem(draft, confirmation)
transition_workitem(identity, target_state, fields, confirmation)
update_wbs(identity, rows, publish, confirmation)
append_comment(identity, content, confirmation)
```

Feishu Project MCP adapter 负责：

- transport：stdio / future HTTP。
- token：只在本地配置和子进程环境出现。
- allowlist：read/write 工具白名单。
- write gate：确认写操作。
- audit：记录工具名、脱敏 payload、结果状态。

Codex、Claude、Gemini runner 不直接持有 Feishu Project MCP token，也不直接写飞书项目。

## Skill 解耦

Skill 分两层：

1. `coding-operator-core`
   - 描述意图路由、任务状态含义、风险说明、下一步策略。
   - 不出现 Hermes、`/coding`、Task Ledger、LLM Wiki 文件路径。
2. `hermes-coding-operator`
   - 把 core intent 映射到 Hermes `/coding` 命令或 Hermes native tools。
   - 只承载 host binding，不承载通用业务规则。

健康检查 Skill 同样拆分：

1. `coding-health-core`
   - 描述 readiness 解释格式和修复口径。
2. `hermes-coding-health-check`
   - 映射 Hermes CLI、Hermes 配置路径和当前插件命令。

## 零耦合集成责任矩阵

工具端、MCP / WorkItem、Skill 和 Hermes host shell 不能各自定义一套业务规则。每条能力必须先找到权威层，再由 Hermes 做 host 集成；如果某一层必须知道外部系统细节，只能知道自己 adapter 的细节。

| 切面 | 权威层 | Hermes 只做什么 | 禁止回流 | 验收信号 |
| --- | --- | --- | --- | --- |
| 工具端 | `ToolSpec` + operation dispatcher | 注册 Hermes native tool，把 host payload 归一成 `operation_id + args` | 在 `plugin_tools.py` 里写业务规则、状态推进或 ledger mutation | Hermes native tools、未来 MCP tools 和 CLI handler 可复用同一 operation spec |
| MCP / WorkItem | `WorkItemPort` + `WorkItemService` + MCP adapter | 注入本机运行配置，调用 adapter，输出脱敏结果 | core/service 持有 `MCP_USER_TOKEN`、直接拼 JSON-RPC、绕过写确认 | 写操作有确认和审计，token 只存在本机配置与 adapter 子进程环境 |
| Skill core | `coding-operator-core` / `coding-health-core` | 不由 Hermes 直接注册为业务入口，只作为 host-agnostic playbook | core skill 出现 Hermes、`/coding`、运行根、ledger、LLM Wiki 本地路径 | core skill 可被其他 host 复用，不依赖 Hermes runtime |
| Hermes binding skill | `hermes-coding-operator` / `hermes-coding-health-check` | 把 core intent 映射到 `/coding`、Hermes CLI、`lark-cli` 恢复命令 | 在 binding skill 中新增通用业务策略或状态机规则 | binding skill 删除后 core skill 仍能描述通用工作法 |
| Gateway / command | `gateway_command_controller.py` + executor host shell | 解析 host event、生成 route metadata、委托 service / façade | controller 写 ledger、启动 runner、发送 Gateway 消息或推进状态 | 解析规则可纯测试，副作用只在 host shell / application service 中发生 |
| Run orchestration | `RunService` + run projection modules | 连接 runner、ledger、manifest、workspace service 的副作用边界 | projection helper 启动 subprocess、写 ledger、读写 workspace/git、发送消息 | projection 模块只返回 payload / decision；副作用留在 orchestrator 或明确 service |
| Source / Lark | `SourcePort` + source adapters | 索引来源、传递可恢复读取命令和 source result | 业务层消费 reader-specific dict，创建 task 前强依赖 reader 正文成功 | Task / prompt / context 只消费 `SourceResult` |
| Storage / Knowledge | repositories + `KnowledgePort` | 初始化运行根并调用 adapter | application service 手写 SQL、知道 LLM Wiki layout 或复制运行根内容 | schema/query/wiki layout 变更不影响 service contract |
| Presentation | presenter modules + host binding copy | 渲染用户可见文案和状态摘要 | presenter 推进 task/run 状态、触发 runner 或写 ledger | 文案可单测，状态变化由 service / state machine 证明 |
| 大文件 / hard code | `architecture_guard.py` + 文档合同 | 输出 watchlist 和 fail gate | 把新增大文件、host command、`Path.home()`、`os.getenv()`、token key 当临时例外 | 新增 core/service/tool hard code 会失败；新增超阈值文件需拆分或登记 |

## 大文件治理

文件长度治理规则：

- 小模块目标：200-400 行。
- 超过 500 行：需要在设计或 PR 中说明职责边界。
- 超过 600 行：进入治理清单。
- 超过 1000 行：必须拆分，除非是生成文件或测试 fixture。

拆分优先级：

1. `orchestrator.py`
   - 拆 `CommandController`、`TaskService`、`RunService`、`DeliveryService`、`WorkItemService`、`HealthService`、`NotificationPresenter`。
2. 已完成拆分项
   - `tests/test_codex_cli_runner.py` 已删除并拆为 command/process/report/report-failure façade 小文件。
   - `doctor_presenter.py` 已拆出 doctor、preflight 和 source-resolve 文案。
   - `runners/codex_cli.py` 已拆出 command/process/report/artifact 模块。
   - `project_knowledge_initializer.py` 已拆出 scanner/inventory 与 document builder。
   - `ledger.py` / `storage/repositories.py` 已拆出 schema 与 task/run/artifact/binding repository。
   - `feishu_project_reader.py` 已拆出 URL parser、document reader、work item reader 和 error mapper。
   - `gateway_rewrite_presenter.py`、`run_start_presenter.py`、`feedback_presenter.py`、`merge_test_presenter.py`、`task_list_presenter.py`、`task_status_presenter.py` 和 `run_completion_presenter.py` 已拆出 rewrite/run-start/feedback/merge-test/list/status 摘要与 run completion 用户可见消息。
   - `workspace_checkpoint_service.py` 已拆出 workspace 复用/创建、source branch/base branch、QA artifact 收集、clean-tree checkpoint、git HEAD 和 diff guard QA artifact 过滤。
   - `run_manifest_service.py` 已拆出 run-manifest 基础字段、启动期 manifest update projection、artifact record、Codex attach/resume 展示命令、manifest session metadata 字段投影与文件回写、controlled bypass 权限 profile 和 source elevated plan 权限判断。
   - `gateway_command_controller.py` 已拆出显式 `/coding` / `/commands` 解析、`/coding` 命令归一化、命令 route plan、handler key、reply mode、task id 来源策略、merge-test 参数解析、rewrite canonical command、确认/取消词分类、rewrite 风险确认、plugin echo 过滤、Gateway event dedupe 和授权探测；orchestrator 现按 reply mode 统一处理 help/list/project/use/status/complete/cancel/restore/delete 和 diagnostic immediate reply。
   - `gateway_command_executor.py` 已拆出 task/run/delivery/implementation/QA/prepare/merge-test custom route host shell 分发，orchestrator 只委托 executor；runner/ledger 副作用仍通过 façade/callback 保持兼容。
   - `gateway_pending_action_executor.py` 已拆出 pending action 确认/取消、latest human_required fallback、取消任务 gate 和确认后显式命令续接，orchestrator 只保留兼容 wrapper。
   - `gateway_active_context.py` 已拆出 active project 应用到缺项目 task 的回填逻辑，orchestrator 只保留兼容 wrapper。
   - `run_session_projection.py` 已拆出 plan report session fields 白名单、plan report session update、run start base/workspace session update、active run session update、runner session update 和 completion session update 纯 payload，`run_session_writeback_service.py` 已拆出 start_run 与 active run reconcile 的 task session callback，`run_diff_guard_service.py` 已拆出 run diff guard observation host service，`run_dispatch_service.py` 已拆出 checkpoint failure gate、`runner.run()` 调度和 runner exception fallback host service，`run_status_transition_service.py` 已拆出状态机、status/phase/Kanban callback、run start/completion/reconcile transition 和 active run cleanup host service，`run_evidence_observation_service.py` 已拆出 QA artifacts、tested commit 和 implementation dirty-check observation，`run_prompt_projection.py` 已拆出首次/增量 prompt 构造选择，`run_context_artifact_service.py` 已拆出 run context artifact 文件写入和 `execution-policy.json` 读取，`run_start_artifact_service.py` 已拆出 `report.schema.json`、`input-prompt.md` 和 `run-manifest.json` 启动 artifact 写入，`run_manifest_artifact_service.py` 已拆出 `run-manifest.json` artifact 写回，`run_stderr_artifact_service.py` 已拆出 `stderr.log` artifact 写回，`run_report_artifact_service.py` 已拆出 `report.json` artifact 读写和 summary excerpt，`run_summary_artifact_service.py` 已拆出 `summary.md` artifact 读写，`run_ledger_writeback_service.py` 已拆出 run ledger host callback，`run_summary_writeback_service.py` 已拆出 summary writer host callback，`run_orchestration_service.py` 只保留兼容 re-export。

## Hard Code 治理

hard code 只能出现在以下位置：

- `config.py` / future config module：默认路径、默认命令、默认域名和 env key 名称。
- future env adapter：环境变量读取。
- `adapters/*`：host 或外部系统 binding。
- `models.py` / `status_policy.py`：状态常量和投影规则。
- 测试 fixture：明确验证默认值时允许。

核心域和应用服务中禁止：

- `Path.home()`。
- `os.getenv()`。
- `subprocess.run()`。
- `rtk lark-cli` 字符串。
- `/coding` 字符串。
- `MCP_USER_TOKEN`、`FEISHU_APP_ID` 等 token/env key。
- Hermes skill 绝对路径。

## 工作阶段

工作阶段按“先固化合同，再迁移用例，再拆 adapter，最后治理回流”的顺序推进。每一阶段都必须保持 Hermes 当前主流程可用，不能为了拆分破坏 plan-only 只读、人工确认、MCP 写入门禁和 merge-test 人工触发这些安全语义。

阶段不是一次性项目，而是长期迭代的治理轨道。每个阶段都必须有明确主责、明确沉淀物和明确验收信号；当阶段没有完成时，后续新能力只能在现有 façade 后继续增量推进，不能绕过边界新增平行实现。

### 阶段批次

| 批次 | 覆盖阶段 | 目标 | 完成后系统形态 |
| --- | --- | --- | --- |
| A. 合同与边界 | 0-4 | 先统一事实、配置、工具规格和端口，防止后续迁移继续依赖 Hermes 细节 | 新需求能先选归属，再写代码 |
| B. 应用服务迁移 | 5-9 | 将 workitem、task、run、status、delivery 的业务用例从 orchestrator 迁到 service/policy | `CodingOrchestrator` 只保留命令 façade 和副作用编排 |
| C. Adapter 与资产拆分 | 10-14 | 将 prompt、runner、storage、source、skill 的外部系统绑定收口到 adapter 或 contract asset | core/service 不感知 Codex CLI、MCP、Lark、SQLite、LLM Wiki 或 Hermes skill 细节 |
| D. 测试、文档、治理回流 | 15-17 | 清理旧实现耦合测试，更新事实文档，引入行数、hard code 和边界漂移检查 | 长期迭代时新增耦合能被测试、脚本或 review 发现 |

### 全线阶段总表

| 阶段 | 核心问题 | 职责归属 | 主要产物 | 退出验收 |
| --- | --- | --- | --- | --- |
| 0. 现状盘点 | 量化耦合、大文件、hard code、旧测试绑定 | 架构治理 | 行数清单、hard code 清单、旧测试分类、主流程风险清单 | 核心模块和风险点可被追踪 |
| 1. 架构合同 | 团队缺少统一边界判断标准 | 架构治理 + 文档合同 | 本设计文档、实施计划、`component-contract` 更新 | 新需求能判断应落在 core、service、port、adapter 还是 host shell |
| 2. 配置边界 | 路径、命令、域名、env key 散落 | Config / Adapter binding | `RuntimeConfig`、`ToolConfig`、后续 `HostConfig` | core 和 service 不直接读 env、`Path.home()` 或本机路径 |
| 3. ToolSpec / IntentSpec | 工具端直接绑定 Hermes tool 注册 | Tool contract | `ToolSpec`、operation dispatcher、future `IntentSpec` | Hermes native tools 和未来 MCP tool 共用同一规格 |
| 4. Ports 反转依赖 | 业务逻辑直接依赖外部系统实现 | Port contract | `HostPort`、`RunnerPort`、`SourcePort`、`WorkItemPort`、`LedgerPort` 等 | service 只依赖端口，不 import 具体 adapter |
| 5. MCP / WorkItem 解耦 | 飞书 Project MCP 读写和业务状态混在 orchestrator | WorkItem service + MCP adapter | `WorkItemService`、MCP adapter 写门禁、脱敏审计 | 读写都经 `WorkItemPort`，写操作必须确认，token 不出 adapter |
| 6. Task 用例解耦 | 任务创建、source indexing、状态 payload 堆在 orchestrator | Task application service | `TaskService`、task utils、source payload contract | 创建任务、查询状态、source 索引行为保持兼容 |
| 7. Run 生命周期解耦 | plan/implementation/QA/merge-test 状态和 runner 编排耦合 | Run application service | `RunService`、run blocker、timeout、phase 映射、run result 映射 | plan-only、implementation、QA、merge-test 主流程回归通过 |
| 8. StatusPolicy | 状态字符串、known gaps、runner failure 投影分散 | Domain policy | `status_policy.py`、状态详情 contract tests | 新状态只能经状态策略进入用户可见状态 |
| 9. DeliveryService | 父子任务、拆解、materialize 和根任务进度缺少独立边界 | Delivery application service | `DeliveryService`、breakdown/materialize/status contract | 交付拆解和主 task/run 生命周期互不污染 |
| 10. Prompt 模板治理 | PromptBuilder 承载 mode 文案、source 文案和 host 绑定 | Prompt contract | `prompts/` 模板模块、prompt contract tests | prompt 只组合模板，模式约束和 report schema 不退化 |
| 11. Runner adapter 拆分 | Codex CLI command、process、report、artifact 混合 | Runner adapter | command builder、report policy、process runner、report loader、report writer、artifact collector | runner 内部每个组件职责单一，runner tests 通过 |
| 12. Storage / Knowledge 拆分 | Ledger schema、query、mutation、LLM Wiki 写入混合 | Storage adapter + Knowledge adapter | ledger repositories、migration 模块、knowledge adapter | 持久化细节不进入 application service |
| 13. Source adapter 拆分 | URL 解析、lark-cli、Feishu/Meegle 读取和错误映射混合 | Source adapter | URL parser、document reader、work item reader、error mapper | source 读取失败可恢复，业务层只见 `SourcePort` 结果 |
| 14. Skill 解耦 | Skill 直接描述 Hermes、`/coding` 和运行根细节 | Core skill + host binding skill | `coding-operator-core`、`hermes-coding-operator`、health core/binding | core skill 不含 Hermes 细节，Hermes skill 只做映射 |
| 15. 旧测试清理 | 测试绑定旧 helper 和旧文件形态 | Test contract | 旧测试保留/改写/删除清单、contract/main-flow tests | 删除前已有等价覆盖，完整单测通过 |
| 16. 文档同步 | 文档与实际边界不一致会反向制造耦合 | 文档合同 | README、Usage、Project Map、Component Contract 更新 | 用户文档只描述可见行为，架构文档描述内部边界 |
| 17. 长期治理 | 新需求可能重新堆回 orchestrator 或 adapter | Architecture guard | 行数检查、hard code 检查、边界检查、PR checklist | 新增耦合能在测试、review 或治理脚本中被发现 |

### 阶段责任矩阵

| 阶段 | 主责角色 | 协作角色 | 长期沉淀 |
| --- | --- | --- | --- |
| 0. 现状盘点 | 架构治理 | 测试治理、模块维护者 | 大文件、hard code、旧测试和主流程风险清单 |
| 1. 架构合同 | 架构治理 | 文档合同、模块维护者 | 设计文档、实施计划、组件合同 |
| 2. 配置边界 | Adapter binding | 架构治理、测试治理 | `RuntimeConfig`、`ToolConfig` 和配置 contract tests |
| 3. ToolSpec / IntentSpec | Tool contract | Hermes host adapter、MCP adapter | `ToolSpec`、operation id、统一 schema |
| 4. Ports 反转依赖 | Port contract | Application service、Adapter owner | `ports.py` 和 runtime-checkable protocol tests |
| 5. MCP / WorkItem 解耦 | WorkItem service | Feishu MCP adapter、测试治理 | `WorkItemService`、写门禁、脱敏审计 |
| 6. Task 用例解耦 | Task service | Source adapter、Ledger adapter | task 创建、状态 payload、source indexing contract |
| 7. Run 生命周期解耦 | Run service | Runner adapter、Diff guard、状态策略 | run blocker、mode gate、timeout、result mapping |
| 8. StatusPolicy | Domain policy | Run service、Report contract | 状态详情、known gaps、runner failure 投影策略 |
| 9. DeliveryService | Delivery service | Task service、Ledger adapter、Presenter | breakdown、approve、materialize、rollup contract |
| 10. Prompt 模板治理 | Prompt contract | Source adapter、Runner adapter | mode/source 模板和 prompt contract tests |
| 11. Runner adapter 拆分 | Runner adapter | Report policy、Process runtime | command/process/report/artifact 组件 |
| 12. Storage / Knowledge 拆分 | Storage adapter | Knowledge adapter、Application service | repository、migration、knowledge port |
| 13. Source adapter 拆分 | Source adapter | WorkItem adapter、Prompt contract | URL parser、reader、error mapper |
| 14. Skill 解耦 | Skill contract | Hermes binding、Tool contract | host-agnostic core skill 和 host binding skill |
| 15. 旧测试清理 | 测试治理 | 各阶段主责 | cleanup log、contract/main-flow replacement tests |
| 16. 文档同步 | 文档合同 | 架构治理、模块维护者 | project map、component contract、conventions |
| 17. 长期治理 | Architecture guard | 测试治理、文档合同 | 行数、hard code、边界漂移检查和 PR checklist |

### 阶段执行合同

每个阶段都按同一套执行合同推进：

1. 准入：完整单测或该阶段上一轮基线通过；明确本阶段只迁移一个职责域。
2. 先测：先补 contract 或主流程测试，再迁移实现。
3. 兼容：`CodingOrchestrator` 迁移期只做 façade，用户可见命令和 tool schema 不变。
4. 验证：阶段内跑聚焦测试；阶段结束跑完整单测或记录为什么只能跑聚焦测试。
5. 记录：更新实施计划中的状态、剩余职责和删除旧测试的等价覆盖依据。

### 长期职责模型

后续所有新增能力先写入以下归属之一，再动代码：

| 归属 | 可以做 | 不可以做 |
| --- | --- | --- |
| Core Domain | 数据模型、状态枚举、确定性策略、report contract | 读 env、调 subprocess、拼 host 命令 |
| Application Service | 编排 task/run/delivery/workitem 用例，调用端口 | import Hermes、MCP transport、Codex CLI 细节 |
| Port | 定义稳定能力合同 | 包含外部系统命令、token、URL 细节 |
| Adapter | 绑定 Hermes、MCP、Codex、Lark、SQLite、LLM Wiki | 承载业务状态决策 |
| Host Shell | 注册 hook、command、tool、skill，转换 host event | 实现核心业务规则 |
| Presentation | 用户可见消息、状态摘要、rewrite handoff copy、help copy | 推进 task/run 状态 |
| Tests | contract、主流程、安全边界、adapter 行为 | 只断言旧私有 helper 或旧文件位置 |

### 持续迭代闭环

每一轮迭代固定使用同一个闭环，避免阶段做完后边界再次漂移：

1. 选择一个职责域：只能选 task、run、delivery、workitem、source、runner、storage、skill、prompt、presentation 或 governance 之一。
2. 更新基线：记录当前行数、hard code 命中、主流程测试和旧测试依赖点。
3. 写 contract：先补 service/port/policy/adapter contract tests，主流程风险补 orchestrator flow tests。
4. façade 迁移：外部入口保持不变，业务规则只迁到一个权威模块。
5. 清理旧耦合：仅删除已有等价覆盖的私有 helper 或旧文件形态测试。
6. 同步事实：更新 `docs/project-map.md`、`docs/component-contract.md`、`docs/conventions.md` 或本计划的进度表。
7. 治理回流：把新发现的大文件、hard code、边界漂移加入治理清单或检查脚本。

## 旧测试清理策略

旧测试分三类处理：

1. 保留
   - 用户可见行为测试。
   - 状态机、report contract、diff guard、安全边界测试。
   - install/preflight 的安全检查测试。
2. 改写
   - 直接断言 orchestrator 私有方法的测试，改为 application service 或 contract tests。
   - 直接依赖 Hermes tool registration 细节的测试，改为 ToolSpec + Hermes adapter tests。
   - 直接断言 MCP JSON-RPC payload 位置的测试，改为 WorkItemPort adapter tests。
3. 删除
   - 只验证旧方法名、旧 helper 存在、旧文件内部分支的测试。
   - 与新边界相冲突、但不保护用户行为和安全语义的测试。
   - 重复覆盖同一行为且依赖旧实现形态的测试。

删除旧测试必须满足两个条件：

- 有对应的新 contract 或主流程测试覆盖同一用户价值。
- 删除理由写入实施计划或提交说明。

## 主流程验收

改造完成前必须证明以下流程继续跑通：

1. `/coding task <需求> --project <项目>` 创建任务并自动进入 plan-only。
2. plan-only 输出完整 report，Task 进入 plan ready。
3. `/coding implement <task_id>` 进入实现 run，产出 commit/report/artifacts。
4. `/coding qa <task_id>` 可续接实现 workspace，并可记录 known gaps。
5. `/coding merge-test <task_id>` 执行 merge-test gate，不自动发布。
6. `/coding complete <task_id>` 人工标记完成。
7. 飞书 Project MCP 读写仍需显式确认，token 不进入 prompt、日志、文档和测试 fixture。
8. plan-only 无论是否提权，都不能修改项目文件。

最小验证命令：

```bash
rtk proxy python3 -m unittest discover -s tests -v
```

分阶段可使用更窄测试，但最终验收必须跑完整单测，并补充主流程 contract tests。

## 长期迭代规则

- 新能力先写归属：core domain、application service、port、adapter、presentation。
- 新外部系统必须先定义 port，再写 adapter。
- 新 host 只能接入 adapter，不改 core domain。
- 新工具必须先进入 ToolSpec。
- 新状态必须进入 `models.py` / `state_machine.py` / `status_policy.py`，不能散落字符串。
- 新 prompt 必须有模板归属和 contract test。
- 新测试优先覆盖 contract 和用户行为，不依赖私有 helper。

## 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 一次性大迁移破坏主流程 | 每阶段保持 façade 兼容，按服务逐步替换 |
| 删除旧测试导致覆盖下降 | 先补 contract tests，再删除旧实现耦合测试 |
| 新增抽象变成空壳 | 每个 port 必须至少有一个现有 adapter 和测试 |
| 配置迁移影响本机安装 | 保留旧默认值，先通过 config facade 注入 |
| Skill 拆分影响 Hermes 主 agent | 先新增 core skill，再让 Hermes skill 引用/映射，不直接删除旧 skill |

## 完成定义

改造完成必须同时满足：

- `orchestrator.py` 不再承载核心业务逻辑，主流程通过服务完成。
- 核心域和应用服务不依赖 Hermes、MCP transport、CLI subprocess 和本机路径。
- ToolSpec、ports、config、status policy 有测试覆盖。
- 旧测试清理完成，剩余测试保护用户行为、contract 和安全边界。
- 完整单测通过。
- README、PLUGIN_USAGE、component contract 与实际架构一致。
