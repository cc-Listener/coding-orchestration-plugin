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
- project init/use/list/status/clear 只处理项目上下文，不创建 task。
- destructive 操作，例如 cancel/delete，必须要求人工确认，不要自动执行。

## intent triage

1. 如果用户在普通聊天、问概念、讨论方案，直接按 Hermes 主 agent 正常回答。
2. 如果用户在查询 coding 状态、任务、项目，建议只读命令，例如 `/coding list`、`/coding status <task_id>`、`/coding project list`。
3. 如果用户在描述新需求，先检查是否有 active task 或 active_project。没有项目归属时，不建议创建 task，要求用户先 `/coding project init <path>` 或 `/coding project use <name>`。
4. 如果用户在反馈当前任务，优先归入 active task，不让 active_project 抢走上下文。

## project-first workflow

- “有哪些项目 / 当前有哪些项目”：建议 `/coding project list`。
- “先初始化 bps-admin / 项目路径是 xxx”：建议 `/coding project init <project_path_or_name>`。
- “我接下来用 bps-admin / 切到 oms”：建议 `/coding project use <project_name>`。
- “当前项目是什么”：建议 `/coding project status`。
- “清掉当前项目”：建议 `/coding project clear`。
- “订单列表加筛选” 且 active_project 存在：建议 `/coding task <需求>`，说明 plugin 会注入 active_project。
- “订单列表加筛选” 但没有 active_project、active task 或明确项目：低置信度回复，要求用户先选项目，不要创建 task。

## task next step

- `needs_human`：要求用户补项目、来源权限或缺失上下文。
- `planned` / `plan_ready`：建议 `/coding implement <task_id>`。
- `running` / `queued`：告知已有 run 正在执行，不启动新 run。
- `ready_for_merge_test` / `ready_for_merge_test_with_known_gaps`：建议 `/coding merge-test <task_id>`；known gaps 要列风险。
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
