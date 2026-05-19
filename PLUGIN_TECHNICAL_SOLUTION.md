# 定义全新的 workflow

## 1. 为什么要定义全新的 workflow

这份方案的中心不是“做一个 Hermes plugin”，而是定义一条新的团队研发 workflow：需求必须显式进入 Hermes，Hermes 负责状态、知识和执行编排，Codex 等编码工具只作为受控 runner 执行具体编码动作。

当前人工流程里，需求来自飞书 Wiki、飞书文档、飞书项目、群聊口头沟通。人需要手动判断项目、切换目录、开启 Codex session、补充上下文、等待计划、确认开发、检查 diff、整理测试结果，再把 QA 反馈重新喂给 Codex。这个流程能跑，但它依赖个人记忆，不容易追踪，也很难把经验沉淀给下一次任务。

新的 workflow 要解决的是：

- 需求入口分散，缺少统一主控。
- Codex session 靠人手动开启和恢复，任务切换成本高。
- Plan、implementation、bugfix、merge-to-test 之间缺少可审计状态机。
- 历史需求、项目知识、QA 经验和 API 约定没有稳定沉淀。
- Hermes 主 agent 和编码流程容易抢同一条普通消息上下文。
- Codex 是当前选择，但后续需要平滑扩展 Claude Code、Gemini 等编码工具。

因此，这个 plugin 只是 workflow 的实现载体。真正要落地的是一套规则：编码任务必须通过 `/coding` 显式进入；Task Ledger 管运行事实；LLM Wiki 管长期知识；runner 只负责执行；人保留 plan 确认、测试验证和发布权。

## 2. 新 workflow 的一句话定义

飞书里只有显式 `/coding <action>` 命令会进入 plugin；Hermes 创建 Task Ledger 事实记录，按需读取 LLM Wiki 推荐目录知识，生成受控 prompt，调用 Codex CLI 或未来其他 runner 执行，产出 artifact，再把 run summary、需求草稿和 QA 经验按 LLM Wiki 规范自动沉淀。

## 2.1 版本定位

当前方案定位为 **MVP 版本**，目标是先把“飞书需求 -> Hermes 主控 -> LLM Wiki 增强 -> Codex plan-only -> 人工确认 -> Codex implementation -> 人工测试 -> merge-to-test 辅助 -> 人工发布”的最小闭环跑通。

MVP 的判断标准不是功能完整，而是 workflow 可用、任务可追踪、run 可审计、知识能沉淀、Hermes 主 agent 不再抢 coding 上下文。

MVP 保留的刻意限制：

- 只要求 `/coding` 显式命令进入 plugin。
- 默认 runner 是 Codex CLI，Claude Code / Gemini 只保留接口。
- LLM Wiki 采用本地 adapter 和推荐目录结构。
- Task Ledger 使用本地 SQLite。
- merge-to-test 可以由 Hermes 续接 Codex session 执行，但发布仍然人工。
- plugin 生产安装路径要清晰，但允许 debug 阶段继续软链接。

## 3. 前置环境配置

这套 workflow 要稳定运行，需要先完成 Hermes、runner、飞书权限、项目知识和本地目录的基础配置。

### 3.1 Hermes 环境安装

Hermes 的安装和基础配置直接以官方文档为准，本方案不重复维护安装步骤：

- Hermes 官方文档：https://hermes-agent.nousresearch.com/docs/
- Hermes 官方安装文档：https://hermes-agent.nousresearch.com/docs/getting-started/installation/
- Hermes 官方 Quickstart：https://hermes-agent.nousresearch.com/docs/getting-started/quickstart/

### 3.2 TODO：Hermes plugin 安装与重启

TODO：生产环境安装 plugin。生产环境不使用软链接，直接通过 Hermes plugin install 从仓库安装：

```bash
hermes plugins install cc-Listener/coding-orchestration-plugin --enable
rtk hermes gateway restart
```

如果团队内部统一使用 SSH Git URL：

```bash
hermes plugins install git@github.com:cc-Listener/coding-orchestration-plugin.git --enable
rtk hermes gateway restart
```

安装后必须验证三件事：

```bash
hermes plugins list
hermes gateway status
```

在飞书或 Hermes Gateway 对话里验证：

```text
/commands
/coding help
```

预期结果：

- `/commands` 第一页能看到 `/coding help`、`/coding task`、`/coding status`、`/coding delete`。
- `/coding help` 能输出完整 coding workflow 命令说明。
- 普通自然语言不会进入 plugin。

TODO：本地 debug 安装 plugin：

```bash
rtk proxy python3 scripts/install_symlink.py --hermes-home ~/.hermes
hermes plugins enable coding_orchestration
rtk hermes gateway restart
```

> 截图占位：`screenshots/02-plugin-install-restart.png`
>
> 截图内容建议：终端展示 plugin install 或 symlink install、`hermes plugins enable coding_orchestration`、`rtk hermes gateway restart` 成功输出，重点能看到插件已启用和 Gateway 已重启。

Hermes 配置示例：

```yaml
plugins:
  enabled:
    - coding_orchestration

coding_orchestration:
  enabled: true
  default_runner: codex_cli
  ledger_db: ~/.hermes/coding-orchestration/ledger.db
  run_root: ~/.hermes/coding-orchestration/runs
  workspace_root: ~/.hermes/coding-orchestration/workspaces
  # 可选：只用于首次 bootstrap / 兜底迁移，不是运行期项目画像事实源。
  project_registry: ~/.hermes/coding-orchestration/project-registry.json
  llm_wiki:
    adapter: local
    root: ~/.hermes/coding-orchestration/llm-wiki
```

运行目录会自动生成：

```text
~/.hermes/coding-orchestration/
  ledger.db
  runs/
  workspaces/
  llm-wiki/
  project-registry.json   # 可选 bootstrap seed；稳定项目画像写入 LLM Wiki
```

### 3.3 Codex 环境安装

MVP 默认 runner 是 Codex CLI。Codex CLI 的安装、登录和基础配置直接以 OpenAI 官方文档为准，本方案不重复维护安装步骤：

- Codex CLI 官方文档：https://developers.openai.com/codex/cli
- Codex CLI 命令参考：https://developers.openai.com/codex/cli/reference

后续扩展 Claude Code / Gemini 时，在 Hermes runner 配置里启用即可；workflow 不需要改。

### 3.4 飞书 Project 读取权限

如果需求来自飞书 Project 链接，Hermes 需要先读出 story / bug 描述，再整理给 runner。需要配置：

```bash
FEISHU_PROJECT_PLUGIN_TOKEN=...
FEISHU_PROJECT_USER_KEY=...
```

如果租户使用不同接口，可配置 URL 模板：

```bash
FEISHU_PROJECT_WORK_ITEM_DETAIL_URL_TEMPLATE=https://project.feishu.cn/open_api/{project_key}/work_item/{work_item_type_key}/{work_item_id}
```

如果没有这些权限，plugin 会停在人工补充阶段，不会把只有链接的任务直接交给 Codex 猜。

> 截图占位：`screenshots/04-feishu-project-permission.png`
>
> 截图内容建议：展示 Hermes 环境变量配置位置或启动日志，能看到 `FEISHU_PROJECT_PLUGIN_TOKEN`、`FEISHU_PROJECT_USER_KEY` 已配置；不要截出真实 token，建议打码。

### 3.5 LLM Wiki 基础目录

本地 LLM Wiki 路径默认为：

```text
~/.hermes/coding-orchestration/llm-wiki
```

首次写入时会自动生成推荐目录：

```text
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

无需手工维护 `index.md`、`overview.md`、`log.md`；它们由 adapter 自动更新。

> 截图占位：`screenshots/05-llm-wiki-directory.png`
>
> 截图内容建议：文件管理器或终端 `tree ~/.hermes/coding-orchestration/llm-wiki -L 3`，展示 `purpose.md`、`schema.md`、`raw/sources`、`wiki/index.md`、`wiki/log.md`、`wiki/overview.md` 和各分类目录。

### 3.6 项目画像

项目画像由 LLM Wiki 接管，稳定项目知识统一保存为 `project_profile`。Hermes 的 Project Resolver 运行时优先 search/read LLM Wiki，再把命中的 `project_profile` 转成可执行路由结果；Task Ledger 只记录本次任务实际采用的 `project_path`、匹配证据和 `llm_wiki_refs`。

`project-registry.json` 不是长期项目知识事实源，只保留两个用途：

- 首次接入新环境时作为 bootstrap seed，启动后自动 upsert 到 LLM Wiki。
- LLM Wiki 暂不可用或缺少画像时，作为低优先级兜底，并在人工确认后回写 LLM Wiki。

因此，日常新增项目、修正别名、补充模块关键词、调整允许修改范围，都应该更新 LLM Wiki 的 `project_profile`，而不是长期维护 registry 配置。

最小 `project_profile`：

```json
{
  "kind": "project_profile",
  "project": "bps-admin",
  "name": "bps-admin",
  "aliases": ["BPS运营后台", "bps-admin"],
  "local_paths": ["/Users/xiaojing/Desktop/project/bps-admin"],
  "keywords": ["订单列表", "策略列表"],
  "allowed_paths": ["src/", "tests/"],
  "forbidden_paths": [".env", "deploy/"],
  "test_commands": ["rtk pnpm test"],
  "default_runner": "codex_cli",
  "status": "verified"
}
```

> 截图占位：`screenshots/06-project-profile.png`
>
> 截图内容建议：展示 LLM Wiki 中某个 `project_profile` 页面，例如 `wiki/entities/project-bps-admin.md`，能看到 aliases、local_paths、keywords、allowed_paths、test_commands 等关键字段。

### 3.7 项目内 workflow 约束

项目内可以提供 `WORKFLOW.md`，用于约束 runner 的开发范围和测试命令：

```md
# WORKFLOW

## Allowed Paths
- src/
- tests/

## Forbidden Paths
- .env
- deploy/

## Test Commands
- rtk pnpm test

## Merge Policy
manual_only

## Publish Policy
manual_only
```

当 `WORKFLOW.md` 和 LLM Wiki `project_profile` 同时存在时，项目内 `WORKFLOW.md` 优先，缺失项由 LLM Wiki 补齐。

> 截图占位：`screenshots/07-project-workflow-md.png`
>
> 截图内容建议：展示项目仓库中的 `WORKFLOW.md`，重点包含 Allowed Paths、Forbidden Paths、Test Commands、Merge Policy、Publish Policy。

## 4. 总体架构

```text
Feishu
  |
  v
Hermes Gateway
  |
  v
pre_gateway_dispatch hook
  |
  v
coding_orchestration plugin
  |
  +-- Command Router：只处理 /coding <action>
  +-- Task Ledger：运行期事实源
  +-- LLM Wiki Adapter：知识库读写层
  +-- Project Resolver：项目识别与模块路由
  +-- Workflow Loader：项目工作流约束
  +-- Prompt Builder：受控 prompt 生成
  +-- Runner Router：编码工具路由
  |     |
  |     +-- Codex CLI Runner
  |     +-- Claude Code Runner，后续
  |     +-- Gemini Runner，后续
  |
  +-- Run Artifacts：审计、回放、diff guard
  +-- Run Summary Writer：知识沉淀
```

> 截图占位：`screenshots/08-workflow-architecture.png`
>
> 截图内容建议：可以是一张手绘或白板架构图，展示 Feishu -> Hermes Gateway -> plugin -> Task Ledger / LLM Wiki / Runner Router -> Codex CLI 的关系。

核心边界：

- Hermes Gateway 是唯一入口和控制面。
- plugin 只处理显式 `/coding` 命令。
- Task Ledger 是运行期事实源。
- LLM Wiki 是知识增强层，不保存任务运行状态。
- Codex CLI 是 runner，不直接操作飞书、不决定项目、不自动发布。
- 发布测试环境仍由人执行。

## 5. Hermes 集成方式

plugin 通过 Hermes 插件系统加载，不直接改 Hermes 主程序。

生产安装建议：

```bash
hermes plugins install cc-Listener/coding-orchestration-plugin --enable
```

本地 debug 可以使用软链接：

```bash
rtk proxy python3 scripts/install_symlink.py --hermes-home ~/.hermes
```

Hermes 加载后，plugin 注册：

- `pre_gateway_dispatch` hook：在 Hermes 主 agent 接手前识别 `/coding` 命令。
- `/coding` 命令组：统一入口。
- 兼容旧 `/coding-*`、`/codex-*` slash 命令，但不作为推荐入口。

最新规则非常明确：

- `/coding task ...` 会进入 plugin。
- `/coding continue ...` 会进入 plugin。
- `/coding bugfix ...` 会进入 plugin。
- `/coding implement ...` 会进入 plugin。
- 普通自然语言不会进入 plugin。
- active task binding 只给显式 `/coding` 命令补默认 task 上下文，不自动吞普通回复。

这解决了之前最影响实际使用的问题：Hermes 主 agent 和 plugin 不再抢自然语言消息。

> 截图占位：`screenshots/09-hermes-plugin-command-registration.png`
>
> 截图内容建议：展示 Hermes `/commands` 的返回结果，第一页能看到 `/coding help`、`/coding task`、`/coding status`、`/coding delete` 等插件预设命令。

## 6. 标准命令

团队只需要记住一个前缀：`/coding`。

```text
/coding help
/coding task <需求>
/coding status <task_id>
/coding list
/coding use <task_id>
/coding exit
/coding continue <反馈>
/coding bugfix <反馈>
/coding run <task_id>
/coding implement <task_id>
/coding prepare-merge-test <task_id>
/coding merge-test <task_id>
/coding cancel <task_id|run_id>
/coding delete <task_id> [--keep-artifacts] [--keep-wiki] [--force]
```

关键语义：

- `/coding task`：创建任务，识别项目，写 Task Ledger，写 LLM Wiki draft，自动进入 plan-only。
- `/coding continue`：补充计划反馈，重新进入 plan-only。
- `/coding bugfix`：补充 QA 或实现反馈，复用原 implementation workspace 修复。
- `/coding implement`：人工确认 plan 后进入 GitOps implementation。
- `/coding merge-test`：人工测试通过后，续接 Codex session 执行 `merge-to-test` skill。
- `/coding delete`：删除 task、active binding、关联 LLM Wiki draft/run_summary 和本地 run/workspace artifact。

普通确认语，例如“可以了”“新建分支去干活”，不会再触发 plugin。必须显式发送 `/coding implement <task_id>`。

> 截图占位：`screenshots/10-coding-help-command.png`
>
> 截图内容建议：飞书或 Hermes 对话里执行 `/coding help` 的返回结果，能看到完整命令列表和普通自然语言不进入 plugin 的说明。

## 7. Plugin 处理任务的完整流程

这一节描述的是 plugin 内部如何处理一个 coding task。它不是用户操作说明，而是团队理解和排查问题时要看的主链路。

### 7.1 内部处理流水线

```text
飞书消息 / Hermes Gateway message
  |
  v
pre_gateway_dispatch
  |
  +-- /commands
  |     -> plugin 输出 Coding Orchestration 命令列表
  |
  +-- 非 /coding 普通自然语言
  |     -> 放行给 Hermes 主 agent
  |
  +-- /coding <action>
        |
        v
Command Router
  |
  +-- normalize action
  |     /coding task / continue / bugfix / implement / merge-test / delete ...
  |
  v
Source Context Reader
  |
  +-- 飞书 Project / Wiki / Doc 链接
  |     -> Hermes 使用飞书权限读取正文和字段
  |     -> 读取失败则 task 进入 needs_human，不交给 runner 猜
  |
  v
Project Resolver
  |
  +-- 显式 --project 优先
  +-- LLM Wiki project_profile 匹配项目、别名、模块关键词
  +-- project-registry.json 只做 bootstrap/fallback
  +-- 低置信度则要求人工确认
  |
  v
Task Ledger
  |
  +-- 创建 task_id
  +-- 写 source / requirement_summary / project_path / status / phase
  +-- 写 llm_wiki_refs / human_decisions / active binding
  |
  v
LLM Wiki Writer
  |
  +-- 写 draft_knowledge
  +-- 写 raw source snapshot
  |
  v
Prompt Builder
  |
  +-- 读取 LLM Wiki project_profile / verified knowledge / run summary
  +-- 读取项目 WORKFLOW.md
  +-- 生成 input-prompt.md
  +-- 生成 run-manifest.json
  |
  v
Runner Router
  |
  +-- MVP 默认 Codex CLI Runner
  +-- 后续可路由 Claude Code / Gemini
  |
  v
Run Execution
  |
  +-- plan-only：只产出 plan，不改代码
  +-- implementation：隔离 workspace / source branch 中开发
  +-- merge-test：续接 Codex session 执行 merge-to-test
  |
  v
Artifact Collector
  |
  +-- stdout.log / stderr.log
  +-- report.json / summary.md
  +-- diff.patch
  |
  v
Validator
  |
  +-- report schema 校验
  +-- diff guard 越权检查
  +-- test result 汇总
  |
  v
Task Ledger Update + Feishu Reply + LLM Wiki Run Summary
```

### 7.2 状态推进规则

Task Ledger 是状态事实源，状态推进由 plugin 控制：

```text
/coding task
  -> draft / planning
  -> plan-only running
  -> plan_ready 或 blocked

/coding continue
  -> 追加人工反馈
  -> 重新进入 plan-only
  -> plan_ready 或 blocked

/coding implement
  -> 要求当前 task 已 plan_ready
  -> plan_approved
  -> implementation running
  -> human_review / ready_for_review 或 blocked

/coding bugfix
  -> 要求存在 active task 或显式 task_id
  -> 复用 implementation workspace / source branch
  -> implementation running
  -> human_review / ready_for_review 或 blocked

/coding merge-test
  -> 要求人工测试已通过且存在 source branch / Codex resume session
  -> merge_test running
  -> merged_test / done 或 blocked

/coding cancel
  -> cancelled

/coding delete
  -> 删除 Task Ledger 记录、active binding、可选清理 LLM Wiki 和 artifacts
```

普通自然语言不会推进状态。比如“确认”“可以了”“新建分支去干活”都不会触发 implementation，必须显式发送 `/coding implement <task_id>`。

### 7.3 数据写入规则

每个阶段写入位置不同：

```text
Task Ledger
  -> 运行期事实：status、phase、project_path、runs、workspace、resume session、human decisions

LLM Wiki
  -> 长期知识：draft_knowledge、project_profile、run_summary、QA 经验、verified knowledge

Run Artifacts
  -> 可审计材料：input-prompt.md、run-manifest.json、stdout/stderr、report.json、summary.md、diff.patch

Feishu Reply
  -> 人可读状态：task_id、项目、计划摘要、风险、下一步命令、artifact 路径
```

边界必须清楚：Task Ledger 管“现在任务是什么状态”，LLM Wiki 管“以后可复用的知识”，artifact 管“这次 run 到底发生了什么”。

### 7.4 新需求流程

新需求从 `/coding task` 进入：

```text
/coding task 输入需求
  -> Hermes 解析飞书来源
  -> Project Resolver 识别项目
  -> LLM Wiki search/read 获取项目知识和历史经验
  -> 写 Task Ledger
  -> 写 LLM Wiki draft_knowledge
  -> Codex plan-only
  -> 飞书回写 plan summary
  -> 人工 review plan
  -> /coding implement <task_id>
  -> Codex GitOps implementation
  -> diff guard
  -> 飞书回写 summary、测试结果、风险
  -> 人工测试
  -> /coding merge-test <task_id>
  -> 人工发布测试环境
```

> 截图占位：`screenshots/11-feishu-coding-task.png`
>
> 截图内容建议：飞书中发送 `/coding task ...` 后，Hermes 回复“已创建编码任务”，包含 task_id、需求小结、当前状态、项目、下一步。

> 截图占位：`screenshots/12-plan-only-result.png`
>
> 截图内容建议：飞书中 plan-only 完成后的回写内容，能看到计划摘要、风险、下一步，以及明确要求人工确认 plan 后再 `/coding implement <task_id>`。

### 7.5 Bugfix 流程

bugfix 从 `/coding bugfix` 进入：

```text
/coding bugfix 输入 QA 反馈
  -> 读取 active task 或指定 task
  -> 读取 Task Ledger 中的原 run、workspace、source branch
  -> 读取 LLM Wiki 中的原计划、run summary、QA 经验
  -> 复用原 implementation workspace
  -> Codex 在源分支继续修复
  -> 写新的 artifact 和 run_summary
  -> 人工验证
```

> 截图占位：`screenshots/13-bugfix-feedback.png`
>
> 截图内容建议：飞书中发送 `/coding bugfix ...` 的场景，Hermes 回复已收到 bugfix 反馈，并说明会复用原 implementation workspace 继续修复。

### 7.6 Merge-to-test 流程

```text
人工测试通过
  -> /coding prepare-merge-test <task_id>
  -> /coding merge-test <task_id>
  -> Hermes 续接上一次 Codex session
  -> Codex 使用 merge-to-test skill
  -> push source branch
  -> merge 到 test 并 push origin/test
  -> Task Ledger 标记 merged_test / done
  -> 发布测试环境仍人工
```

> 截图占位：`screenshots/14-merge-test-flow.png`
>
> 截图内容建议：飞书中执行 `/coding prepare-merge-test <task_id>` 和 `/coding merge-test <task_id>` 的回写，重点展示 Hermes 续接 Codex session、merge 到 test、发布仍人工。

### 7.7 Cancel / Delete 流程

取消和删除是两个不同动作：

```text
/coding cancel <task_id|run_id>
  -> 取消正在运行的 task 或 run
  -> Task Ledger 标记 cancelled
  -> 保留已有 artifacts 和 LLM Wiki 记录，便于排查

/coding delete <task_id>
  -> 删除 Task Ledger task
  -> 清理 active binding
  -> 默认清理 task 关联 LLM Wiki draft/run_summary
  -> 默认清理 run/workspace artifacts
  -> 可用 --keep-artifacts 或 --keep-wiki 保留材料
```

删除是清理动作，不是状态推进动作；运行中任务默认需要先 cancel，除非显式使用 `--force`。

## 8. Task Ledger 的职责

Task Ledger 是运行期事实源。

它保存：

- task_id
- source
- requirement_summary
- project_path
- status
- phase
- task_session
- llm_wiki_refs
- agent_runs
- artifacts
- human_decisions
- merge_records
- active bindings
- created_at / updated_at

它回答的是：

- 当前任务处于什么状态。
- 当前 task 绑定哪个飞书会话。
- 最近一次 run 是哪个。
- implementation workspace 在哪里。
- Codex resume session id 是什么。
- 是否已经 ready_for_review / merged_test / done。

这些事实不会写入 LLM Wiki 作为状态源。LLM Wiki 可以记录总结和经验，但不能替代 Task Ledger。

> 截图占位：`screenshots/15-task-ledger-status.png`
>
> 截图内容建议：执行 `/coding status <task_id>` 的返回结果，展示 status、phase、项目路径、source_branch、worktree 等运行期事实。

## 9. LLM Wiki 的最新落地方式

LLM Wiki 是团队知识层，不是任务状态库。

它保存：

- 项目画像：项目名、别名、本地路径、模块关键词、默认测试命令。
- 需求草稿：飞书输入、需求摘要、补充上下文。
- run summary：plan-only、implementation、merge-test 的结构化总结。
- QA 经验：bug 根因、修复方式、回归测试。
- 稳定知识：API 约定、模块归属、工作流规范。

它不保存：

- task 是否 running。
- 当前 active task。
- 当前 run 是否成功。
- 是否已经 merge test。
- 是否已经发布。

### 9.1 推荐目录结构

本地 LLM Wiki 已按 `llm_wiki` 推荐结构落盘：

```text
llm-wiki/
  purpose.md
  schema.md
  raw/
    sources/
    assets/
  wiki/
    index.md
    log.md
    overview.md
    entities/
    concepts/
    sources/
    queries/
    synthesis/
    comparisons/
  .llm-wiki/
  .obsidian/
```

目录语义：

- `purpose.md`：说明这个知识库的用途和边界。
- `schema.md`：说明 frontmatter 字段和知识类型。
- `raw/sources/`：不可变来源快照，保存飞书输入、runner summary、registry bootstrap 等原始材料。
- `raw/assets/`：图片、附件等原始素材。
- `wiki/entities/`：实体知识，例如 `project_profile`。
- `wiki/sources/`：需求草稿、飞书输入摘要等 source-derived 页面。
- `wiki/synthesis/`：`run_summary`、`qa_experience` 等综合知识。
- `wiki/concepts/`：稳定概念、规则、工作流规范。
- `wiki/queries/`：查询记录或人工检索问题，后续扩展。
- `wiki/comparisons/`：方案对比，后续扩展。
- `wiki/index.md`：自动生成的知识索引。
- `wiki/overview.md`：自动生成的项目、状态、最近更新概览。
- `wiki/log.md`：自动追加的写入/删除日志。

> 截图占位：`screenshots/16-llm-wiki-overview-index-log.png`
>
> 截图内容建议：并排展示或分别截图 `wiki/index.md`、`wiki/overview.md`、`wiki/log.md`，证明知识索引、概览和更新日志会自动生成。

### 9.2 自动录入规则

所有新知识通过 `LocalLlmWikiAdapter.upsert()` 写入：

- 先写一份 `raw/sources/*.md` 原始来源快照。
- 再写一份 `wiki/*/*.md` 可检索知识页。
- wiki 页面用 YAML frontmatter 保存结构化字段。
- 同一 `dedupe_key/id` 的 wiki 页面更新 `updated_at`，保留 `created_at`。
- raw source 已存在时不覆盖，保证来源可追溯。
- 每次 upsert 自动刷新 `wiki/index.md` 和 `wiki/overview.md`。
- 每次 upsert 自动追加 `wiki/log.md`。

当前类型映射：

```text
project_profile      -> wiki/entities/
draft_knowledge      -> wiki/sources/
run_summary          -> wiki/synthesis/
qa_experience        -> wiki/synthesis/
verified_knowledge   -> wiki/concepts/
```

> 截图占位：`screenshots/17-llm-wiki-auto-ingest.png`
>
> 截图内容建议：展示一次任务后生成的 `raw/sources/*.md` 和对应 `wiki/sources/*.md` 或 `wiki/synthesis/*.md`，重点能看到 frontmatter 中的 `id`、`kind`、`project`、`source_refs`、`created_at`、`updated_at`。

### 9.3 按需读取规则

Hermes 不会把整个知识库塞进 prompt。

读取流程是：

```text
task requirement
  -> search(query, filters)
  -> read(ref_id)
  -> 注入少量相关 wiki docs
  -> Prompt Builder 生成 input-prompt.md
```

读取原则：

- 按项目过滤，避免跨项目污染。
- 优先读取 `project_profile`、verified knowledge、相关 run summary。
- 当前 task 自己产生的 draft 不会作为外部知识反向注入。
- bugfix 任务会额外读取原 task 的 run summary。
- `source_refs` 保留来源链路，方便审计。

旧版 `index.jsonl` 只保留读取兼容，不再作为新写入格式。

> 截图占位：`screenshots/18-llm-wiki-search-read.png`
>
> 截图内容建议：展示某次 run 的 `input-prompt.md` 中注入的 LLM Wiki refs，或展示日志中 search/read 命中的 project_profile/run_summary，证明不是整库注入，而是按需读取。

### 9.4 自动更新规则

写入时机：

- `/coding task`：写 `draft_knowledge`。
- plan-only 完成：写 `run_summary`。
- implementation 完成：写 `run_summary`。
- bugfix 完成：写新的 `run_summary`，后续可提炼为 `qa_experience`。
- registry bootstrap：写 `project_profile`。
- `/coding delete`：按参数删除 task 关联 draft/run_summary 和 raw source。

更新产物：

- `raw/sources/*.md`
- `wiki/*/*.md`
- `wiki/index.md`
- `wiki/overview.md`
- `wiki/log.md`

> 截图占位：`screenshots/19-llm-wiki-after-delete-or-update.png`
>
> 截图内容建议：展示 `/coding delete <task_id>` 后，task 关联的 wiki 页面和 raw source 被清理，同时 `wiki/index.md` 和 `wiki/log.md` 更新。

## 10. Codex 受控执行方式

Codex CLI 不是主控，只是 runner。

每次 run 都由 Hermes 生成独立 artifact：

```text
input-prompt.md
run-manifest.json
report.schema.json
stdout.log
stderr.log
events.jsonl
report.json
summary.md
diff.patch
```

> 截图占位：`screenshots/20-run-artifacts-directory.png`
>
> 截图内容建议：展示某个 run 目录，例如 `~/.hermes/coding-orchestration/runs/<task_id>/<run_id>/`，能看到 `input-prompt.md`、`run-manifest.json`、`stdout.log`、`stderr.log`、`report.json`、`summary.md`、`diff.patch`。

artifact 作用：

- `input-prompt.md`：Hermes 生成的受控 prompt。
- `run-manifest.json`：run_id、task_id、mode、runner、project_path、workspace_path、timeout、allowed paths。
- `report.schema.json`：要求 runner 输出结构化结果。
- `stdout.log` / `stderr.log` / `events.jsonl`：完整过程日志。
- `report.json`：结构化执行结果。
- `summary.md`：给人看的飞书回写内容。
- `diff.patch`：diff guard 和审计依据。

Codex 模式：

- `plan-only`：只读项目，不开发，只输出计划。
- `implementation`：在隔离 workspace / source branch 中开发。
- `merge-test`：续接 Codex session 执行 `merge-to-test` skill。

implementation 的 prompt 会显式要求 GitOps 流程：

- 使用 superpowers / worktree 方式。
- 先理解 plan。
- 在隔离 workspace 中改代码。
- 运行测试。
- 输出 `report.json` 和 `summary.md`。
- 不自动发布。
- 不操作飞书。

> 截图占位：`screenshots/21-codex-implementation-summary.png`
>
> 截图内容建议：飞书中 implementation 完成后的回写，能看到实现摘要、测试结果、风险、artifact 路径，以及“不自动合并或发布”的提示。

## 11. Runner 可扩展设计

当前默认 runner 是 `codex_cli`，但架构上不把 Codex 写死。

统一抽象是：

```text
CodingAgentRunner.run(manifest, prompt, workspace) -> RunnerResult
```

Runner 共同约束：

- 接收 Hermes 生成的 prompt 和 manifest。
- 输出 stdout/stderr/events。
- 输出结构化 report。
- 不直接写 Task Ledger。
- 不直接操作飞书。
- 不决定项目。
- 不自动发布。

后续可以扩展：

- Claude Code Runner
- Gemini Runner
- 内部 coding agent runner
- 审查型 runner
- 只跑测试型 runner

Hermes 只负责调度、状态、审计和知识沉淀；具体编码工具可以替换。

> 截图占位：`screenshots/22-runner-router-config.png`
>
> 截图内容建议：展示 Hermes 配置中 default_runner 和 runners 配置，或代码中的 Runner Router 配置，说明 Codex / Claude Code / Gemini 可以被同一 workflow 路由。

## 12. 项目识别策略

项目识别优先使用 LLM Wiki 的 `project_profile`。

优先级：

1. `/coding task --project <name>` 显式指定。
2. LLM Wiki `project_profile` 的 name / aliases 精确匹配。
3. LLM Wiki `project_profile` 的 keywords / modules 匹配。
4. 本地 `project-registry.json` 只作为 bootstrap/fallback，命中后必须自动沉淀为 LLM Wiki `project_profile`。
5. 低置信度时进入人工确认，不让 runner 猜项目。

`project_profile` 典型字段：

```json
{
  "kind": "project_profile",
  "project": "bps-admin",
  "name": "bps-admin",
  "aliases": ["BPS运营后台", "bps-admin"],
  "local_paths": ["/Users/xiaojing/Desktop/project/bps-admin"],
  "keywords": ["订单列表", "策略列表"],
  "allowed_paths": ["src/", "tests/"],
  "forbidden_paths": [".env", "deploy/"],
  "test_commands": ["rtk pnpm test"],
  "default_runner": "codex_cli",
  "status": "verified"
}
```

稳定项目知识应沉淀到 LLM Wiki，而不是持续堆配置文件。Project Resolver 的目标不是读配置找项目，而是从 LLM Wiki 读取团队已经确认过的项目画像，并把本次路由结论写入 Task Ledger 供审计。

> 截图占位：`screenshots/23-project-resolution-evidence.png`
>
> 截图内容建议：展示 `/coding task ...` 创建任务后的回写或 Task Ledger 记录，能看到项目识别结果、项目路径、match evidence 或来自 LLM Wiki 的 project_profile。

## 13. 当前已经具备的能力

当前 MVP 已具备：

- `/coding` 统一命令入口。
- 普通自然语言不进入 plugin。
- 飞书需求创建 task。
- 自动进入 Codex plan-only。
- plan 回写飞书，等待人工确认。
- `/coding implement` 启动 GitOps implementation。
- implementation 使用隔离 workspace。
- `/coding bugfix` 复用源 workspace 修复。
- `/coding merge-test` 续接 Codex session 执行 merge-to-test。
- `/coding delete` 删除 task、artifacts、关联 LLM Wiki 文档。
- Task Ledger 状态追踪。
- LLM Wiki 推荐目录落盘。
- LLM Wiki 自动录入、按需读取、自动更新 index/overview/log。
- Runner Router 支持未来扩展。
- stale run 保护。
- plugin 回声保护。
- diff guard 越权修改检查。

## 14. 1.0 版本 TODO

MVP 跑通后，1.0 的目标是把这套 workflow 从“个人可用”推进到“团队稳定可安装、可升级、可观测、可扩展”。

### 14.1 Hermes plugin 安装产品化

1.0 必须把 plugin 安装从 debug 软链接升级为标准安装链路：

- 仓库发布稳定 tag，例如 `v1.0.0`。
- `plugin.yaml` 补齐版本、兼容 Hermes 版本、入口、命令和 hook 描述。
- README 和 `PLUGIN_USAGE.md` 只推荐生产安装命令：

```bash
hermes plugins install cc-Listener/coding-orchestration-plugin --enable
rtk hermes gateway restart
```

- 私有仓库或内网环境使用 SSH Git URL：

```bash
hermes plugins install git@github.com:cc-Listener/coding-orchestration-plugin.git --enable
rtk hermes gateway restart
```

- 提供安装后自检清单：
  - `hermes plugins list` 能看到 `coding_orchestration` 已启用。
  - `/commands` 能看到 `/coding` 命令组。
  - `/coding help` 能输出插件命令说明。
  - `/coding task ...` 能创建 task 并进入 plan-only。

软链接安装只保留为开发者 debug 方式，不进入生产部署流程。

### 14.2 插件升级、回滚和兼容性

- 支持按 tag 安装和升级。
- 记录当前安装版本和 Hermes 版本。
- 提供 rollback 指引：回退到上一 tag、重启 Gateway、保留 Ledger 和 LLM Wiki 数据。
- 为 Task Ledger schema 增加 migration 机制，避免升级破坏已有任务。
- 给 LLM Wiki 文档结构增加 schema version。

### 14.3 LLM Wiki 从本地 adapter 走向团队知识层

- 保留本地 adapter，新增可替换 adapter 接口。
- 支持团队共享存储，例如 Git repo、内部知识库、数据库或向量检索服务。
- 把 `project_profile` 的新增、确认、更新流程产品化。
- 增加 verified / draft / run_summary 的审核或晋升机制。
- 增加知识冲突检测：同一项目多个路径、同一模块多个 owner、API 约定不一致时要求人工确认。

### 14.4 Runner 生态扩展

- Codex CLI 仍是默认 runner。
- 增加 Claude Code runner、Gemini runner 的实现和测试。
- Runner capability 进入配置：是否支持 plan-only、implementation、resume、structured report、workspace isolation。
- 不同项目可以在 LLM Wiki `project_profile` 中配置默认 runner。
- 统一 `report.json` schema，避免不同 runner 输出不可比较。

### 14.5 飞书集成增强

- Project story / bug 读取失败时给出更明确的权限诊断。
- 支持从飞书评论继续补充 task 上下文，但仍要求 `/coding` 前缀。
- 输出确认卡：需求摘要、项目识别证据、plan 摘要、风险、下一步命令。
- 对 bug 单自动关联原 task，并从 LLM Wiki 恢复历史上下文。
- 增加操作审计：谁创建、谁确认 plan、谁触发 implementation、谁触发 merge-test。

### 14.6 可观测和治理

- 提供 `/coding metrics` 查看 task 数、成功率、blocked 原因、平均耗时。
- 提供 `/coding doctor` 检查 Hermes、Codex、Feishu、LLM Wiki、项目路径和权限。
- 增加 run 超时、取消、stale workspace 的清理策略。
- 将 stdout/stderr/report/diff 的关键摘要纳入统一日志。
- 对越权 diff、高风险文件、冲突、未通过测试做更明确的阻断。

### 14.7 团队接入模板

- 提供新项目接入模板：
  - LLM Wiki `project_profile`
  - 项目 `WORKFLOW.md`
  - allowed / forbidden paths
  - 默认测试命令
  - merge-to-test 约束
- 提供团队宣讲版 quickstart。
- 提供截图清单：安装、`/commands`、创建 task、plan 回写、implementation 完成、merge-test。

## 15. 不做什么

第一版刻意不做：

- 不自动发布测试环境或生产环境。
- 不让 Codex 直接操作飞书。
- 不让 Codex 自己决定项目。
- 不把 Task Ledger 状态写进 LLM Wiki 当事实源。
- 不自动处理高风险冲突。
- 不做复杂多 agent 平台。
- 不做庞大 RAG 平台。
- 不让普通自然语言进入 plugin。

核心边界是：Hermes 控制流程，runner 执行编码，人保留关键判断和发布权。

## 16. 团队价值

这套 plugin 的长期价值，是把个人经验型 AI 编码流程变成团队可复用的工程系统。

变化包括：

- 从“人找 Codex”变成“Hermes 调度 Runner”。
- 从“飞书口头需求”变成“可追踪 Task”。
- 从“本地 session 记忆”变成“LLM Wiki 团队知识”。
- 从“手动切项目”变成“Project Resolver 自动路由”。
- 从“结果不可回放”变成“artifact 全量留痕”。
- 从“只支持 Codex”变成“未来可插拔多编码工具”。
- 从“知识散落在对话里”变成“按 LLM Wiki 推荐目录持续沉淀”。

最终目标不是做大平台，而是先把最小闭环稳定跑通：需求显式进入 Hermes，计划由 Codex 产出，开发由 Codex 执行，状态由 Ledger 管理，知识由 LLM Wiki 沉淀，发布仍由人控制。
