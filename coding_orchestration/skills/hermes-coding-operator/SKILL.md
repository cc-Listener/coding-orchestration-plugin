---
name: hermes-coding-operator
description: Use when Hermes Coding Mode handoff is low-confidence and the main agent must triage project-first coding operations.
---

# Hermes Coding Operator

用于 Hermes 主 agent 接管 coding plugin 的低置信度 handoff。你的目标是判断用户原话是否应该转成 `/coding <action>`，还是按普通对话处理，或者要求用户补信息。

## Hard Rules

- 低置信度不创建 task、不启动 runner、不写 LLM Wiki。
- 不默认使用插件仓库、Hermes 当前工作目录、当前 shell cwd 或 active project 之外的目录。
- 只有用户明确指定项目、已有 active task、已有 active_project，或明确说明 Wiki 目标时，才能建议对应 `/coding` 命令。
- 如果用户明确指定项目/文件夹并提出新的开发需求，飞书 Wiki/Docx/Meegle 来源读不到也不应阻止 task 创建；把来源作为 Codex plan 阶段读取项，建议 `/coding task <原需求> --project <项目名或文件夹>`。
- 只有用户明确在问 `lark-cli` 授权、scope、source 读取失败、token 刷新等诊断时，才调用或建议 `coding_lark_preflight` / `coding_source_resolve`；不要把“带飞书链接的新需求”误判为授权诊断。
- project init/use/list/status/clear 只处理项目上下文，不创建 task。
- destructive 操作，例如 cancel/delete，必须要求人工确认，不要自动执行。

## intent triage

1. 如果用户在普通聊天、问概念、讨论方案，直接按 Hermes 主 agent 正常回答。
2. 如果用户在查询 coding 状态、任务、项目，建议只读命令，例如 `/coding list`、`/coding status <task_id>`、`/coding project list`。
3. 如果用户在描述新需求，先检查是否有 active task 或 active_project。没有项目归属时，不建议创建 task，要求用户先 `/coding project init <path>` 或 `/coding project use <name>`。
4. 如果用户在反馈当前任务，优先归入 active task，不让 active_project 抢走上下文。
5. 如果用户在同一条消息里给了项目名称/文件夹和需求，即使需求来源是飞书 Wiki/Docx，仍按新 task 处理；不要先要求授权或粘贴正文。

## project-first workflow

- “有哪些项目 / 当前有哪些项目”：建议 `/coding project list`。
- “先初始化 bps-admin / 项目路径是 xxx”：建议 `/coding project init <project_path_or_name>`。
- “我接下来用 bps-admin / 切到 oms”：建议 `/coding project use <project_name>`。
- “当前项目是什么”：建议 `/coding project status`。
- “清掉当前项目”：建议 `/coding project clear`。
- “订单列表加筛选” 且 active_project 存在：建议 `/coding task <需求>`，说明 plugin 会注入 active_project。
- “订单列表加筛选” 但没有 active_project、active task 或明确项目：低置信度回复，要求用户先选项目，不要创建 task。
- “项目名称：商户后台，文件夹名称为 bestvoy-admin。实现 Marketplace APP 后台模块，需求来源：飞书 Wiki 链接”：建议 `/coding task <原需求> --project bestvoy-admin`。飞书正文由 Codex plan session 调用 `rtk lark-cli docs +fetch ...` 读取。

## task next step

- `needs_human`：要求用户补项目、来源权限或缺失上下文；具体来源问题看 `source_status` / `source_recovery_action`，如果用户已经给出项目或路径，建议 `/coding continue <项目或来源补充>`。
- task 缺少项目但会话有 active_project：建议 `/coding run <task_id>` 或 `/coding continue <项目或来源补充>`；plugin 会把 active_project 回填到 task。
- `planned` 且 phase 为 `plan_ready`：建议 `/coding implement <task_id>`。
- `planned` 且 phase 为 `planning` / `plan_revision`：建议 `/coding run <task_id>` 重新生成或刷新计划，不要直接 implement。
- `running`：告知已有 run 正在执行，不启动新 run；如果 `status_detail=queued` 或 `raw_status=queued`，仍按 running 处理。
- `failed`：如果项目已确定，建议 `/coding run <task_id>` 重跑 plan-only；如果 `failure_type=runner_failed`、`raw_status=runner_failed` 或 `last_run_raw_status=runner_failed`，先提示这是 runner/tooling 失败；如果项目未确定，先建议 `/coding continue <项目或来源补充>`。
- `blocked`：先说明 `reason`、`impact`、`recovery_action`、`fallback_evidence`；如果已有 source branch/worktree 且用户接受风险，建议 `/coding merge-test <task_id> --accept-risk`，否则建议按 recovery_action 补验证或 `/coding run <task_id>`。
- `ready_for_merge_test`：测试是可选项；用户要补测试时建议 `/coding qa <task_id>`，用户确认现有验证足够时建议 `/coding merge-test <task_id>`；如果 `known_gaps=true` 或存在 `verification_limitations`，要列风险。
- `merged_test`：建议人工验证 test 后 `/coding complete <task_id>`。
- `cancelled`：只能建议 `/coding restore <task_id>`，不要继续 run。

## feedback router

- 计划补充、验收补充：`/coding continue <反馈>`。
- 需求范围变化、新增功能、验收口径变更：`/coding change <反馈>`。
- 实现结果不对、QA 问题、截图修复、回归缺陷：`/coding bugfix <反馈>`。

## LLM Wiki helper

- 只有明确项目、active_project 或 active task 时，才建议沉淀 LLM Wiki。
- API、Swagger、Figma、飞书文档等动态来源只建议作为 source index，使用前必须重新读取。
- 不要把 `.env*`、token、私钥或敏感配置写入 Wiki。

## merge-test risk helper

任何 blocked、partial 或 known gaps 都要给：

- `reason`：为什么不能完全验证或为什么存在风险。
- `impact`：对 merge-test 或用户验收的影响。
- `recovery_action`：可执行恢复方案。
- `fallback_evidence`：当前能支持继续的证据，例如 source branch、worktree、diff、已通过测试、人工确认。
