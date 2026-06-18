---
name: hermes-coding-operator
description: Use when Hermes Coding Mode handoff is low-confidence and the main agent must triage project-first coding operations.
---

# Hermes Coding Operator

用于 Hermes 主 agent 接管开发任务流程的低置信度 handoff。你的目标是判断用户原话是否应该转成 `/coding <action>`，还是按普通对话处理，或者要求用户补信息。

English anchors for host tests: project-first workflow, intent triage.

Required core skill: `../coding-operator-core/SKILL.md`

本 skill 是 Hermes host binding。使用时先遵守 core skill 的通用 project-first workflow 和 intent triage，再将 core intent 映射到 Hermes `/coding` 命令、Hermes native tools 或普通回复。host binding 只处理 Hermes 命令语法、可用工具和用户可见措辞，不承载新的通用业务规则。

## 硬规则

- 低置信度不创建开发任务、不启动执行、不写长期记忆。
- 不默认使用插件仓库、Hermes 当前工作目录、当前 shell cwd 或当前项目之外的目录。
- 只有用户明确指定项目、已有当前任务、已有当前项目，或明确说明 Wiki 目标时，才能建议对应 `/coding` 命令。
- 普通 execution task 必须能落到单项目、单 repo、可验收；明确跨项目或需要拆解的需求可以先作为父级需求进入拆解链路。
- 父级需求只走 breakdown、approve-breakdown、materialize、run --next、status --delivery/status --tree；不要建议对父级需求直接 `/coding implement`。
- Codex 负责语义判断、拆解、风险和验收建议；Hermes 负责校验、调度、记录、展示。不要让 Python/Hermes 代替 Codex 做语义兜底。
- Report Admission Gate 拒绝的拆解 report 不能创建子任务、不能推进状态、不能进入 merge-test；应要求补信息或重跑 breakdown。
- 上下文是证据包：只建议带入需求摘要、来源索引、直接依赖、父级验收口径和必要项目画像，不要把多项目源码或飞书全文都塞给 Codex。
- 如果用户明确指定项目/文件夹并提出新的开发需求，飞书 Wiki/Docx/Meegle 来源读不到也不应阻止任务创建；把来源作为计划阶段读取项，建议 `/coding task <原需求> --project <项目名或文件夹>`。
- 只有用户明确在问 `lark-cli` 授权、scope、source 读取失败、token 刷新等诊断时，才调用或建议 `coding_lark_preflight` / `coding_source_resolve`；不要把“带飞书链接的新需求”误判为授权诊断。
- project init/use/list/status/clear 只处理项目上下文，不创建任务。
- destructive 操作，例如 cancel/delete，必须要求人工确认，不要自动执行。
- 对用户回复时用“开发任务、当前任务、当前项目、整理计划、实现、执行”，不要直接说 active_project、active task、run、plan-only、implementation、Task Ledger 或 LLM Wiki。

## 意图分流

1. 如果用户在普通聊天、问概念、讨论方案，直接按 Hermes 主 agent 正常回答。
2. 如果用户在查询 coding 状态、任务、项目，建议只读命令，例如 `/coding list`、`/coding status <task_id>`、`/coding project list`。
3. 如果用户在描述普通单项目新需求，先检查是否有当前任务或当前项目。没有项目归属时，不建议创建 execution task，要求用户先 `/coding project init <path>` 或 `/coding project use <name>`。
4. 如果用户明确说这是复杂需求、多任务、多项目、需要拆解或 PMO/交付视角审查，可以建议先创建父级需求，再用 `/coding breakdown <task_id>` 生成交付拆解。
5. 如果用户在反馈当前任务，优先归入当前任务，不让当前项目抢走上下文。
6. 如果用户在同一条消息里给了项目名称/文件夹和需求，即使需求来源是飞书 Wiki/Docx，仍按新任务处理；不要先要求授权或粘贴正文。

## 项目优先流程

- “有哪些项目 / 当前有哪些项目”：建议 `/coding project list`。
- “先初始化 bps-admin / 项目路径是 xxx”：建议 `/coding project init <project_path_or_name>`。
- “我接下来用 bps-admin / 切到 oms”：建议 `/coding project use <project_name>`。
- “当前项目是什么”：建议 `/coding project status`。
- “清掉当前项目”：建议 `/coding project clear`。
- “订单列表加筛选” 且当前项目存在：建议 `/coding task <需求>`，说明系统会带入当前项目。
- “订单列表加筛选” 但没有当前项目、当前任务或明确项目：低置信度回复，要求用户先选项目，不要创建 execution task。
- “这个需求涉及多个项目 / 需要拆成多个任务 / 先从交付角度审查”：建议先创建父级需求，再 `/coding breakdown <task_id>`；不要要求用户先选一个单项目。
- “项目名称：商户后台，文件夹名称为 bestvoy-admin。实现 Marketplace APP 后台模块，需求来源：飞书 Wiki 链接”：建议 `/coding task <原需求> --project bestvoy-admin`。飞书正文由计划执行会话调用 `rtk lark-cli docs +fetch ...` 读取。

## 需求交付拆解流程

父级需求是 requirement，执行任务是 execution。父级需求承载拆解报告和整体进度；真正写代码的只能是 execution 子任务。

建议顺序：

1. 已有明确复杂需求：`/coding task <需求>`。
2. 需要交付拆解：`/coding breakdown <task_id>` 或 `/coding analyze <task_id>`。
3. 拆解方案可接受：`/coding approve-breakdown <task_id>`。
4. 生成执行任务：`/coding materialize <task_id>`。
5. 执行下一个可运行子任务：`/coding run <task_id> --next`。
6. 看整体进度：`/coding status <task_id> --delivery`。
7. 看父子任务和依赖：`/coding status <task_id> --tree`。

判断口径：

- 用户要“拆需求、拆任务、跨项目、全局审查、PMO 视角、交付计划”：优先建议 breakdown，而不是直接 implement。
- breakdown 只生成方案，不创建执行任务；approve-breakdown 是人工确认；materialize 才生成子任务。
- `run --next` 只用于父级需求，Hermes 会选择依赖满足的 execution 子任务。
- 如果没有可运行子任务，建议先看 `/coding status <task_id> --tree`，不要强行启动父级需求实现。
- 多项目需求先按交付责任拆，再收敛到单项目 execution task；不要按 repo 名称机械拆分。

## 任务下一步

- 父级需求 requirement：
  - 没有拆解方案：建议 `/coding breakdown <task_id>`。
  - 拆解方案有开放问题或 `materialization_allowed=false`：要求补信息后重跑 `/coding breakdown <task_id>`。
  - 已有拆解方案但未确认：建议 `/coding approve-breakdown <task_id>`。
  - 已确认但还没有子任务：建议 `/coding materialize <task_id>`。
  - 已有子任务：建议 `/coding status <task_id> --delivery` 或 `/coding run <task_id> --next`。
  - 依赖阻塞或无可运行子任务：建议 `/coding status <task_id> --tree` 查看依赖，不建议直接实现父级需求。
- `needs_human`：要求用户补项目、来源权限或缺失上下文；具体来源问题看 `source_status` / `source_recovery_action`，如果用户已经给出项目或路径，建议 `/coding continue <项目或来源补充>`。
- 任务缺少项目但会话有当前项目：建议 `/coding run <task_id>` 或 `/coding continue <项目或来源补充>`；系统会把当前项目回填到任务。
- `planned` 且 phase 为 `plan_ready`：建议 `/coding implement <task_id>`。
- `planned` 且 phase 为 `planning` / `plan_revision`：建议 `/coding run <task_id>` 重新生成或刷新计划，不要直接实现。
- `running`：告知已有执行正在进行，不启动新执行；如果 `status_detail=queued` 或 `raw_status=queued`，仍按 running 处理。
- `failed`：如果项目已确定，建议 `/coding run <task_id>` 重新整理计划；如果 `failure_type=runner_failed`、`raw_status=runner_failed` 或 `last_run_raw_status=runner_failed`，先提示这是执行器或工具失败；如果项目未确定，先建议 `/coding continue <项目或来源补充>`。
- `blocked`：先说明 `reason`、`impact`、`recovery_action`、`fallback_evidence`；如果已有源分支/工作区且用户接受风险，建议 `/coding merge-test <task_id> --accept-risk`，否则建议按 recovery_action 补验证或 `/coding run <task_id>`。
- `ready_for_merge_test`：测试是可选项；用户要补测试时建议 `/coding qa <task_id>`，用户确认现有验证足够时建议 `/coding merge-test <task_id>`；如果 `known_gaps=true` 或存在 `verification_limitations`，要列风险。
- `merged_test`：建议人工验证 test 后 `/coding complete <task_id>`。
- `cancelled`：只能建议 `/coding restore <task_id>`，不要继续执行。

## 反馈路由

- 计划补充、验收补充：`/coding continue <反馈>`。
- 需求范围变化、新增功能、验收口径变更：`/coding change <反馈>`。
- 实现结果不对、QA 问题、截图修复、回归缺陷：`/coding bugfix <反馈>`。
- 父级需求拆解不准确：先建议 `/coding change <反馈>` 记录范围变化，再重新 `/coding breakdown <task_id>`。

## 长期记忆辅助

- 只有明确项目、当前项目或当前任务时，才建议沉淀长期记忆。
- API、Swagger、Figma、飞书文档等动态来源只建议作为来源索引，使用前必须重新读取。
- 不要把 `.env*`、token、私钥或敏感配置写入 Wiki。

## merge-test 风险辅助

任何 blocked、partial 或 known gaps 都要给：

- `reason`：为什么不能完全验证或为什么存在风险。
- `impact`：对 merge-test 或用户验收的影响。
- `recovery_action`：可执行恢复方案。
- `fallback_evidence`：当前能支持继续的证据，例如源分支、工作区、diff、已通过测试、人工确认。
