---
name: hermes-coding-operator
description: Use when Hermes Coding Mode handoff is low-confidence and the main agent must triage project-first coding operations.
---

# Hermes Coding Operator

用于 Hermes 主 agent 接管开发任务流程的低置信度 handoff。你的目标是判断用户原话是否应该转成 `/coding <action>`，还是按普通对话处理，或者要求用户补信息。

English anchors for host tests: project-first workflow, intent triage.

Required core skill: `../coding-operator-core/SKILL.md`

本 skill 是 Hermes host binding。使用时先遵守 core skill 的通用 project-first workflow 和 intent triage，再将 core intent 映射到 Hermes `/coding` 命令、Hermes native tools 或普通回复。host binding 只处理 Hermes 命令语法、可用工具和用户可见措辞，不承载新的通用业务规则。

## Host 映射边界

- 先读取并遵守 `../coding-operator-core/SKILL.md`；本文件不重新定义 project-first workflow、intent triage 或任务状态策略。
- 只在 core intent 已经清晰时，把 intent 映射到 Hermes `/coding` 命令、Hermes native tools 或普通回复。
- 不把本机路径、内部存储、运行产物或凭据写进回复；需要诊断时只给可见的 Hermes 命令或 native tool 名称。
- 用户缺少项目信息、来源权限或上下文时，按 core 结论要求补信息，不在 binding 中自行放宽创建、执行或合并验证条件。

## Core Intent 到 Hermes 动作

| core intent | Hermes 动作 |
| --- | --- |
| 普通对话 / 概念解释 | 普通回复，不调用 `/coding` |
| 查看任务 | `/coding list` 或 `/coding status <task_id>` |
| 查看或切换项目上下文 | `/coding project list`、`/coding project status`、`/coding project init <path>`、`/coding project use <name>`、`/coding project clear` |
| 创建单项目开发任务 | `/coding task <需求>`，有明确项目时追加 `--project <name-or-path>` |
| 带明确项目和来源的新需求 | `/coding task <原需求> --project <项目名或文件夹>` |
| 复杂需求或父级需求拆解 | `/coding breakdown <task_id>`、`/coding approve-breakdown <task_id>`、`/coding materialize <task_id>`、`/coding run <task_id> --next` |
| 查看父级需求交付进度或依赖树 | `/coding status <task_id> --delivery`、`/coding status <task_id> --tree` |
| 整理计划或刷新计划 | `/coding run <task_id>` |
| 开始实现 | `/coding implement <task_id>` |
| 补项目或来源上下文 | `/coding continue <项目或来源补充>` |
| 当前任务补充反馈 | `/coding continue <反馈>` |
| 需求范围变化 | `/coding change <反馈>` |
| 实现或 QA 缺陷修复 | `/coding bugfix <反馈>` |
| 补测试证据 | `/coding qa <task_id>` |
| 合并验证 | `/coding merge-test <task_id>`；core 认定可风险放行时才用 `/coding merge-test <task_id> --accept-risk` |
| test 环境已人工验收 | `/coding complete <task_id>` |
| 误取消恢复 | `/coding restore <task_id>` |

## Native Tool 映射

| 诊断 intent | Hermes native tool |
| --- | --- |
| 来源读取或授权预检 | `coding_lark_preflight` |
| 解析来源链接和恢复动作 | `coding_source_resolve` |
| 查询任务状态 | `coding_task_status` |
| 创建结构化任务 | `coding_task_create` |
| 启动受控执行 | `coding_task_run` |
| 飞书项目 MCP 预检 | `coding_project_mcp_preflight` |
| 飞书项目工作项检索或创建 | `coding_project_workitem_search`、`coding_project_workitem_create` |
| 飞书项目 intake / WBS / 状态同步 | `coding_project_intake_sync`、`coding_project_wbs_update`、`coding_project_state_transition` |
| 飞书项目缺陷 intake | `coding_project_bugfix_intake` |

## 用户可见措辞

- 保留 core 的中文业务词：“开发任务、当前任务、当前项目、整理计划、实现、执行”。
- 普通回复只解释为什么当前不应调用 `/coding`，并给出最短可执行下一步。
- 诊断回复只说明要运行哪个 Hermes 命令或 native tool，不展开本机配置或内部数据结构。
