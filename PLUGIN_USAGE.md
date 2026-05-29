# coding_orchestration 插件使用说明

这个仓库保存 Hermes Coding Orchestration 插件源码。当前版本定位为 **MVP**：先跑通飞书 `/coding` 标准命令、Coding Mode 自然语言改写、Hermes 主控、LLM Wiki 知识增强、Codex 受控执行、Task Ledger 留痕和人工发布的最小闭环。

生产环境应该直接通过 Hermes 插件安装命令安装，软链接只用于本地 debug。

## 生产安装

生产环境统一使用 SSH Git URL 安装。安装前先判断 SSH 仓库访问是否符合：

```bash
rtk git ls-remote git@github.com:cc-Listener/coding-orchestration-plugin.git HEAD
```

符合判定：返回 commit hash 和 `HEAD` 才继续安装；如果出现 `Permission denied (publickey)` 或 `Repository not found`，先修复 SSH key 或仓库权限。

测试部署和生产部署必须使用不同运行根目录。测试 Gateway 设置 `CODING_ORCHESTRATION_ROOT=~/.hermes/coding-orchestration-test`，生产 Gateway 设置 `CODING_ORCHESTRATION_ROOT=~/.hermes/coding-orchestration-prod`；修改后必须重启对应 Gateway。

安装命令：

```bash
rtk hermes plugins install git@github.com:cc-Listener/coding-orchestration-plugin.git --enable
```

插件启用后需要重启 Gateway 或开启新的 Hermes session 才会生效：

```bash
rtk hermes gateway restart
```

安装后检查：

```bash
rtk hermes plugins list
rtk hermes gateway status
```

在飞书或 Hermes Gateway 对话里检查：

```text
/commands
/coding help
```

预期结果：

- `/commands` 第一页能看到 `/coding help`、`/coding task`、`/coding status`、`/coding delete`。
- `/coding help` 能输出完整命令说明。
- 默认普通自然语言不会进入 plugin；发送“进入coding”后，本会话自然语言会先交给 LLM rewrite。高置信度会直接执行为 `/coding <action>`，低置信度或高风险候选会要求确认。

## Debug 安装

开发期可以先把源码落到当前目录，再通过软链接接入 Hermes：

```bash
rtk proxy python3 scripts/install_symlink.py --hermes-home ~/.hermes
```

软链接目标：

```text
~/.hermes/plugins/coding_orchestration -> 当前仓库/coding_orchestration
```

生产环境不要依赖软链接安装；软链接会把 Hermes 绑定到本地 checkout，适合快速调试，不适合稳定部署。

## 1.0 TODO

MVP 之后，1.0 版本重点补齐以下事项：

- 插件安装产品化：按 tag 发布、标准 Hermes plugin install、安装自检、升级和回滚说明。
- Hermes 兼容性声明：记录支持的 Hermes 版本、Codex CLI 版本和必要环境变量。
- Ledger migration：Task Ledger schema 可升级。
- LLM Wiki 团队化：支持共享知识层和 verified / draft / run_summary 晋升流程。
- Runner 扩展：接入 Claude Code、Gemini，并统一 runner capability 和 `report.json`。
- 飞书交互增强：确认卡、权限诊断、bug 单关联、操作审计。
- 可观测性：增加 `/coding doctor`、`/coding metrics`、blocked 原因统计。
- 新项目接入模板：提供 `project_profile`、`WORKFLOW.md`、allowed paths、测试命令和 merge-to-test 约束模板。

Hermes 配置启用示例：

```yaml
plugins:
  enabled:
    - coding_orchestration

coding_orchestration:
  enabled: true
  default_runner: codex_cli
  runners:
    # 可选：切到 Hermes autonomous Codex 后端。
    hermes_autonomous_codex:
      command: codex
      skill_path: ~/.hermes/hermes-agent/skills/autonomous-ai-agents/codex/SKILL.md
  ledger_db: ~/.hermes/coding-orchestration-prod/ledger.db
  run_root: ~/.hermes/coding-orchestration-prod/runs
  workspace_root: ~/.hermes/coding-orchestration-prod/workspaces
  llm_wiki:
    adapter: local
    root: ~/.hermes/coding-orchestration-prod/llm-wiki
```

## Hermes 集成原则

- Hermes Gateway 是唯一主控。
- 插件只注册 Hermes hook 和命令，不直接改 Hermes 主程序。
- Codex CLI、Claude Code、Gemini 都只是 Runner，不能直接操作飞书，不能自己决定项目，不能自动发布。
- Task Ledger 是运行期事实源。
- LLM Wiki 只保存 verified knowledge、draft knowledge、run summary、QA 经验，不保存任务状态事实。
- plugin 默认只处理显式 `/coding` 前缀消息；发送“进入coding”后，本会话自然语言进入 Coding Mode，通过 LLM rewrite 生成标准 `/coding <action>`。高置信度且信息完整时直接执行，低置信度、缺信息或高风险候选才等待人工确认。

## Runner 权限与自动测试

plan-only run 使用 `plan_read_only` 权限 profile：Codex CLI 以只读沙箱运行，只做规划不改项目文件。飞书/Lark 文档、Swagger/OpenAPI、私有 API 元数据、依赖元信息和必要网络上下文优先由 Hermes source reader 在创建 task 前读取，并作为 source context 或 artifact 注入给 Codex。

implementation 和 QA run 使用受控高权限 Codex CLI session。这样 Codex 可以在任务 worktree 内实现代码，并在需要时自动安装依赖、访问私有源、启动测试或 dev server、执行浏览器 QA、写入 `.gstack` QA 报告/截图，以及提交 QA 修复。

安全边界由 Hermes 继续收口：plan-only 不使用 bypass；implementation/QA/merge-test 的 Codex 子进程 cwd 固定为当前 task worktree；源码修改只允许落在当前 workspace；项目外写入只允许依赖缓存、git metadata、dev server/browser 临时文件和 QA artifact；run-manifest 会记录高权限 run 的 `dangerous_bypass`、权限原因和修改边界；Hermes diff guard 仍会审计 workspace 内 diff，越权项目改动不能直接进入可合并状态。

## Coding 命令入口

标准入口仍然是 `/coding <action>`。Coding Mode 只是把自然语言先改写成这些标准命令，不新增第二套动作：

- `/coding task <需求>`：创建任务并自动进入 plan-only。
- `/coding continue <反馈>`：给当前 active task 补充计划反馈，并重新进入 plan-only。
- `/coding change <反馈>`：记录需求变更，重新进入 plan-only 做变更影响分析和短计划。
- `/coding bugfix <反馈>`：给当前 active task 补充实现或 QA 修复反馈，并复用原 workspace 继续 implementation。
- `/coding implement <task_id>`：人工确认 plan 后进入 GitOps implementation。
- `/coding prepare-merge-test <task_id>`：人工标记任务等待执行 merge test。
- `/coding merge-test <task_id>`：续接 Codex session 执行 merge-to-test。
- `/coding complete <task_id>`：merge-test 已合入 test 后，人工标记 task 完成。
- `/coding list|use|exit|status|cancel|delete`：查看、切换、退出、取消或删除任务。

active task binding 用于 `/coding continue`、`/coding change`、`/coding bugfix`、`/coding implement`、`/coding merge-test` 等命令在缺省 `task_id` 时找到当前任务。同一个飞书会话里有多个任务时，用 `/coding list` 查看，用 `/coding use <task_id>` 切换当前任务。需要释放当前绑定或关闭 Coding Mode 时，使用 `/coding exit` 或“退出coding”；需要新开独立任务时，显式发送 `/coding task ...`，或在 Coding Mode 中描述新需求并让高置信度 rewrite 自动执行。

implementation 有硬门禁：Codex 必须先完成 plan-only，Hermes 把 task phase 标为 `plan_ready` 后，人工通过 `/coding implement <task_id>` 才会启动 GitOps implementation。Coding Mode 中的“确认”“新建分支去干活”等自然语言必须先被 LLM rewrite 成标准命令；高置信度且信息完整时直接执行，低置信度或缺信息时要求人工确认。

## Coding Mode 自然语言 rewrite

发送“进入coding”后，本会话开启 Coding Mode。用户可以用自然语言描述意图，Hermes 会调用 LLM rewrite，把自然语言改写为一个标准 `/coding <action>` 候选。

执行原则：

- LLM 只负责改写，不负责执行。
- Hermes 必须校验 LLM 输出的命令是否属于允许列表。
- 高置信度且信息完整时直接执行合法 `/coding <action>`。
- 低置信度不创建 task、不启动 Codex，只提示人工二次确认。
- `/coding cancel`、`/coding delete` 这类 destructive 动作，或 LLM 明确 `needs_confirmation=true` 的候选，即使高置信度也必须确认。
- 如果文本包含 `[Image]` 但 Gateway 没有拿到可访问图片，Hermes 不启动 Codex，提示用户重发图片或图片链接。

高置信度示例：

```text
用户：截图里的 grouped_items 样式不对，按图修一下

Hermes：
[task_xxx] 已收到 bugfix 反馈，进入 implementation 修复。
```

低置信度示例：

```text
用户：帮我看一下

Hermes：
我不确定你要执行哪个 coding 指令，需要人工二次确认。

可能是：
1. /coding continue <反馈>：补充计划信息
2. /coding change <反馈>：需求发生变化
3. /coding bugfix <反馈>：修复已有实现问题

请回复 1/2/3，或直接发送标准命令。
```

LLM rewrite 使用的核心 prompt：

```text
你是 Hermes Coding Plugin 的自然语言命令改写器。

你的唯一任务：把用户输入的自然语言，改写为一个合法的 `/coding <action>` 命令候选。
你不能执行命令，只能输出 JSON。
你不能创建 task、不能启动 Codex、不能修改状态。
真正执行由 Hermes 在用户确认后完成。

必须遵守：
1. 只允许使用 allowed_commands 中列出的命令。
2. 不允许发明命令，不允许输出 `/coding-*` 或 `/codex-*` 旧命令。
3. 用户只是查询任务数量、任务列表、任务状态时，绝不能改写成 `/coding task`。
4. 用户表达“需求改了、需求变更、新增要求、改成...”时，优先改写为 `/coding change <反馈>`。
5. 用户表达“实现不对、截图不对、样式不对、QA反馈、修一下、这里有问题”时，优先改写为 `/coding bugfix <反馈>`。
6. 用户表达“补充一下、计划里加一下、还需要考虑...”时，优先改写为 `/coding continue <反馈>`。
7. 用户表达“可以合 test、merge test、准备合到测试分支”时，改写为 `/coding merge-test <task_id>` 或 `/coding prepare-merge-test <task_id>`，但如果缺少 task_id 且没有 active_task_id，必须标记 missing。
8. cancel/delete 属于 destructive 命令，即使高置信度也必须 needs_confirmation=true。
9. 高置信度且信息完整时设置 needs_confirmation=false，Hermes 会直接执行。
10. 低置信度必须 needs_human_review=true，不能给出可直接执行的命令。
11. 如果无法判断用户意图，intent=unknown，canonical_command=null。
12. 如果用户输入包含图片占位或 has_media=true，保留原始反馈文本，不要丢失图片语义。
13. 如果用户在 active coding task 上下文中指出当前功能、实现、文档或系统表现“不符合预期”“有问题”“需要优化”，这属于当前 task 的反馈，优先改写为 `/coding bugfix <反馈>`；不要误判为元讨论。
14. 如果用户只是抽象讨论 plugin、rewrite 规则、方案设计或文档内容，且没有要求检查/修复当前 task，则属于元讨论，intent=unknown，canonical_command=null。
15. “查看最近对话记录，自然语言 rewrite 表现不符合预期”在 active task 存在时，应理解为要求检查最近对话并修复当前 rewrite 表现，不能改写为 `/coding list`、`/coding status` 或 `/coding task`，应优先改写为 `/coding bugfix <原文>`。
16. 输出必须是严格 JSON，不要 markdown，不要解释。
```

LLM 必须输出的 JSON schema：

```json
{
  "intent": "list_tasks | task_status | switch_task | create_task | plan_feedback | requirement_change | bugfix_feedback | prepare_merge_test | merge_test | complete_task | cancel_task | delete_task | help | exit | unknown",
  "canonical_command": "/coding list",
  "confidence": 0.95,
  "risk_level": "read | write | state_transition | destructive | unknown",
  "needs_confirmation": false,
  "needs_human_review": false,
  "task_id": null,
  "uses_active_task": false,
  "missing": [],
  "reason": "用户询问当前 task 数量，语义明确是任务列表查询"
}
```

正例：

```json
{
  "user_text": "查看最近对话记录，自然语言的rewrite表现不符合预期",
  "coding_mode_enabled": true,
  "active_task_id": "task_xxx",
  "has_media": false
}
```

应输出：

```json
{
  "intent": "bugfix_feedback",
  "canonical_command": "/coding bugfix 查看最近对话记录，自然语言的rewrite表现不符合预期",
  "confidence": 0.9,
  "risk_level": "write",
  "needs_confirmation": false,
  "needs_human_review": false,
  "task_id": "task_xxx",
  "uses_active_task": true,
  "missing": [],
  "reason": "用户要求检查最近对话并指出当前自然语言 rewrite 表现不符合预期，这是 active coding task 的实现反馈，应进入 bugfix"
}
```

## Plugin 任务处理流程

```text
/coding task <需求>
  -> Hermes 拦截显式 /coding 命令
  -> 读取飞书 Project / Wiki / Doc 来源
  -> 从 LLM Wiki 读取 project_profile 识别项目
  -> 创建 Task Ledger 记录和 active binding
  -> 写 LLM Wiki draft_knowledge
  -> 生成 input-prompt.md / run-instructions.md / run-manifest.json
  -> Codex plan-only
  -> 回写计划、风险和下一步命令
  -> 人工确认 plan
  -> /coding implement <task_id>
  -> Codex 在隔离 workspace / source branch 开发
  -> 收集 report、summary、stdout/stderr、diff
  -> diff guard 和测试结果检查
  -> 回写飞书，写 LLM Wiki run_summary
  -> 人工测试
  -> /coding merge-test <task_id>
  -> 续接 Codex session 执行 merge-to-test
  -> 发布测试环境仍人工
```

补充反馈和修复流程：

- `/coding continue <反馈>`：补充 plan 反馈，重新进入 plan-only。
- `/coding bugfix <反馈>`：复用原 implementation workspace、source branch 和历史上下文继续修复。
- `/coding cancel <task_id|run_id>`：取消运行，但保留已有 artifacts 和 LLM Wiki 记录。
- `/coding delete <task_id>`：清理 task、active binding、关联 LLM Wiki 记录和本地 run/workspace；可用 `--keep-artifacts`、`--keep-wiki` 保留材料。

边界：Task Ledger 是运行期事实源；LLM Wiki 是长期知识层；run artifacts 是审计和回放材料。

## 常用命令

```text
/coding task --project 订单系统 修复发货失败
/coding task --runner codex_cli --project 订单系统 生成实现计划
/coding list
/coding use task_xxx
/coding exit
/coding continue 这里补充计划上下文
/coding change 需求改了，需要同时支持订单标签和商品标签
/coding bugfix 这里有问题要在源分支修复
/coding run task_xxx
/coding implement task_xxx
/coding prepare-merge-test task_xxx
/coding merge-test task_xxx
/coding complete task_xxx
/coding status task_xxx
/coding cancel task_xxx
/coding delete task_xxx
```

低置信度项目识别会进入人工确认；自然语言低置信度 rewrite 会进入人工二次确认；implementation 模式会使用隔离 workspace/source branch，并在 run 完成后做 diff guard。人工测试通过后，`/coding merge-test <task_id>` 会续接上一次 Codex session 执行 `merge-to-test` skill，把 source branch push 到 origin、merge 到 `test` 并 push `origin/test`，然后把 Task Ledger 更新为 `merged_test`。这代表已合入 test，但 task 还没有完成；确认测试环境符合预期后，再发送 `/coding complete <task_id>` 标记 `done`。测试环境发布仍然人工执行。

`blocked` task 可以人工尝试 merge-test，但不是无条件放行。Hermes 的硬阻断只保留缺 implementation run、缺 worktree、缺 source branch 或 cancelled。其他风险会先返回确认提示；确认后发送 `/coding merge-test <task_id> --accept-risk`，Hermes 会记录 `accepted_risk` 和 `blocked_merge_test_released`，再转成 `ready_for_merge_test_with_known_gaps` 继续 merge-test。缺 Codex session 时会开新 session；缺 report、report 不完整、diff guard 越权、runner_failed/failed 或报告显示未落地代码，都需要人工接受风险。

`/coding delete` 会删除 Task Ledger 记录、active binding、该 task 生成的 LLM Wiki draft/run_summary，以及插件 run/workspace 目录。运行中任务默认需要先 cancel；可用 `--force` 强制删除，用 `--keep-artifacts` 或 `--keep-wiki` 保留对应记录。

## LLM Wiki 自动写入

插件会在以下时机写入 LLM Wiki：

- 创建任务时，把飞书输入写为 `draft_knowledge`。
- Codex 或其他 runner 完成后，把 `summary.md` 与 `report.json` 汇总写为 `run_summary`。
- bug 任务通过 `--bug-of task_id` 关联原任务时，会读取原任务 run summary 注入新 prompt。

本地 LLM Wiki 按推荐结构落盘：

```text
llm-wiki/
  purpose.md
  schema.md
  raw/sources/
  raw/assets/
  wiki/index.md
  wiki/log.md
  wiki/overview.md
  wiki/entities/
  wiki/concepts/
  wiki/sources/
  wiki/queries/
  wiki/synthesis/
  wiki/comparisons/
```

`upsert` 会同时写入不可变 raw source 快照和可更新的 wiki 页面；`search/read` 按需读取 wiki 页面并保留 `source_refs`；每次写入或删除都会自动刷新 `wiki/index.md`、`wiki/overview.md` 并追加 `wiki/log.md`。旧 `index.jsonl` 只保留读取兼容，不再作为新写入格式。

## 项目接入

项目识别优先走 LLM Wiki 的 `project_profile`。初始化时不需要带入 `project-registry.json`；它只作为可选 bootstrap 和兜底。Hermes 启动时会把存在的 registry 导入 LLM Wiki；文件不存在时使用空 registry。后续新增项目、别名、模块关键词、允许修改范围和默认测试命令，推荐直接写入 `project_profile`。

最小 `project_profile`：

```json
{
  "kind": "project_profile",
  "project": "order-system",
  "name": "order-system",
  "aliases": ["订单系统", "OMS"],
  "local_paths": ["/Users/xiaojing/Desktop/projects/order-system"],
  "keywords": ["订单", "发货", "库存"],
  "allowed_paths": ["src/", "tests/"],
  "forbidden_paths": [".env", "deploy/"],
  "test_commands": ["rtk pnpm test"],
  "default_runner": "codex_cli",
  "status": "verified"
}
```

`WORKFLOW.md` 仍用于项目内执行规范；当 Wiki profile 和 `WORKFLOW.md` 同时存在时，`WORKFLOW.md` 优先，缺失项由 Wiki profile 补齐。见：

- `examples/WORKFLOW.md`
- `examples/project-registry.json`
