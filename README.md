# Hermes Coding Orchestration Plugin

Hermes Coding Orchestration Plugin 是一个 Hermes 用户插件，用 Hermes Gateway 统一接收飞书编码需求，查询 LLM Wiki 补充上下文，并受控调用 Codex CLI 等编码工具完成 plan-only 或 implementation run。

这个项目的目标不是自动发布代码，而是把“手动切项目目录、手动开 Codex session、手动补上下文、手动整理结果”的流程，收敛成一个可审计、可回放、可沉淀知识的最小闭环。

## 解决的问题

- 飞书 Wiki、飞书文档、飞书 Project bug、群聊口头需求入口分散。
- 手动切换项目目录和开启 Codex session 容易漏上下文。
- 历史需求、模块归属、QA 经验和 Codex run 总结难以复用。
- 编码工具运行过程缺少统一 artifacts、stdout/stderr、manifest、report 和 diff 记录。
- Codex 是当前首个编码工具，但后续需要扩展 Claude Code、Gemini CLI 等 runner。
- 合并 test 和发布测试环境仍需人工控制，避免自动发布风险。

## 架构概览

```text
Feishu input
  -> Hermes Gateway
  -> coding_orchestration plugin
     -> Task Ledger
     -> Project Resolver
     -> LLM Wiki Adapter
     -> Workflow / Workspace runtime
     -> Coding Agent Router
        -> Codex CLI Runner
        -> Claude Code Runner (future)
        -> Gemini Runner (future)
     -> Run artifacts
     -> Run Summary Writer
```

核心边界：

- Hermes 是唯一主控。
- Task Ledger 是运行期事实源。
- LLM Wiki 只保存知识、草稿、run summary 和 QA 经验。
- Codex CLI 只是首个受控 runner。
- Runner 不直接操作飞书、不决定项目、不自动发布。

## 安装到 Hermes

### 生产安装

生产环境或团队成员集成时，推荐直接通过 Hermes 插件安装命令安装仓库：

```bash
hermes plugins install cc-Listener/coding-orchestration-plugin --enable
```

如果需要使用 SSH Git URL：

```bash
hermes plugins install git@github.com:cc-Listener/coding-orchestration-plugin.git --enable
```

插件启用后需要重启或开启新的 Hermes session 才会生效。

### 本地调试安装

软链接只用于本地 debug 阶段，适合在当前 checkout 里快速修改插件源码，并让 Hermes 直接加载最新代码：

```bash
rtk proxy python3 scripts/install_symlink.py --hermes-home ~/.hermes
```

软链接结果：

```text
~/.hermes/plugins/coding_orchestration -> 当前仓库/coding_orchestration
```

启用插件：

```bash
hermes plugins enable coding_orchestration
```

生产环境不要依赖软链接安装；软链接会把运行中的 Hermes 绑定到本地工作区，适合开发调试，不适合作为稳定部署方式。

## Hermes 配置示例

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
  project_registry: ~/.hermes/coding-orchestration/project-registry.json
  llm_wiki:
    adapter: local
    root: ~/.hermes/coding-orchestration/llm-wiki
```

### 飞书 Project 需求读取

当飞书消息里包含 `project.feishu.cn/<project_key>/<type>/detail/<id>` 链接时，插件会先由 Hermes 读取工作项详情，把标题、描述和字段摘要整理进 Task Ledger、LLM Wiki draft 和 Codex prompt。Codex runner 只接收整理后的需求上下文，不直接访问飞书。

飞书 Project/Meegle 工作项详情通常需要 Project 插件身份权限。请在 Hermes 环境里配置：

```bash
FEISHU_PROJECT_PLUGIN_TOKEN=...
FEISHU_PROJECT_USER_KEY=...
```

如果你的租户使用了不同的工作项详情接口，可以覆盖 URL 模板：

```bash
FEISHU_PROJECT_WORK_ITEM_DETAIL_URL_TEMPLATE=https://project.feishu.cn/open_api/{project_key}/work_item/{work_item_type_key}/{work_item_id}
```

如果 Hermes 无法读取 Project 描述，插件会创建任务但停在 `needs_human`，并提示补充权限或直接粘贴需求描述；不会把只有链接的任务交给 Codex 自动 plan。

## 会话级接管规则

一旦某个飞书来源创建了未结束 coding task，后续普通回复会优先被 `coding_orchestration` 接管，不再进入 Hermes 主 agent。插件会按当前 task 状态处理：

- `planned` / plan-only `blocked` / plan-only `failed`：把回复写入 Task Ledger 和 LLM Wiki draft，并重新进入 plan-only。
- `ready_for_review` / implementation `blocked` / implementation `failed`：把回复作为 bugfix 或实现反馈写入，并复用最近一次 implementation workspace 继续修复。
- `queued` / `running`：只记录运行中反馈，不并发重启 Codex；后续重新 plan 或修复时注入上下文。
- `needs_human`：记录人工补充，不交给 runner 猜项目或猜需求来源。

如果需要在同一个飞书会话里创建独立新任务，请显式使用 `/coding-task ...`。如果需要释放当前接管，可使用 `/coding-cancel <task_id>` 关闭无关任务。

## 项目知识接入

项目识别和模块归属优先走 LLM Wiki 的 `project_profile`。`project-registry.json` 只用于首次 bootstrap 和兜底，不再作为长期项目知识事实源。

接入优先级：

1. LLM Wiki `project_profile`：项目名、别名、本地路径、模块关键词、允许/禁止修改范围、默认测试命令。
2. 项目内 `WORKFLOW.md`：执行规范，优先约束当前仓库。
3. `project-registry.json`：启动时自动导入 LLM Wiki，或在 Wiki 缺失时兜底。
4. 低置信度时回写飞书让人确认，不交给 runner 猜项目。

`project_profile` 示例：

```json
{
  "kind": "project_profile",
  "title": "BPS Admin 项目画像",
  "body": "BPS运营后台 bps-admin 订单列表 策略列表",
  "project": "bps-admin",
  "project_id": "bps-admin",
  "name": "bps-admin",
  "aliases": ["BPS运营后台", "bps-admin"],
  "local_paths": ["/Users/xiaojing/Desktop/project/bps-admin"],
  "keywords": ["订单列表", "策略列表"],
  "modules": [
    {
      "name": "订单列表",
      "keywords": ["订单列表", "订单筛选"],
      "paths": ["src/pages/order"]
    }
  ],
  "allowed_paths": ["src/", "tests/"],
  "forbidden_paths": [".env", "deploy/", "scripts/release"],
  "test_commands": ["rtk pnpm test", "rtk pnpm build"],
  "default_runner": "codex_cli",
  "confidence": "high",
  "status": "verified"
}
```

`project-registry.json` 示例：

```json
{
  "projects": [
    {
      "name": "order-system",
      "aliases": ["订单系统", "OMS"],
      "path": "/Users/xiaojing/Desktop/projects/order-system",
      "keywords": ["订单", "发货", "库存"],
      "allowed_paths": ["src/", "tests/"],
      "forbidden_paths": [".env", "deploy/", "scripts/release"],
      "default_test_commands": ["rtk pnpm test", "rtk pnpm build"],
      "default_runner": "codex_cli"
    }
  ]
}
```

启动时，插件会把 registry 中的项目自动 upsert 为 `project_profile`。后续稳定的项目知识应直接沉淀到 LLM Wiki，而不是继续扩展配置文件。

`WORKFLOW.md` 示例见 [examples/WORKFLOW.md](examples/WORKFLOW.md)。

## 常用命令

创建任务：

```text
/coding-task --project 订单系统 修复发货失败
```

创建 Codex runner 任务：

```text
/codex-task --project 订单系统 生成实现计划
```

飞书 Gateway 中项目识别成功的自然语言需求会自动启动 plan-only run，并在完成后回写结果。手动创建任务或补跑已有任务时，可以执行 plan-only run：

```text
/coding-run task_xxx
```

执行 implementation run：

```text
/coding-implement task_xxx
```

飞书里 plan-only 回写计划后，也可以直接回复 `确认`、`开始做`、`新建分支去干活` 等确认语句。插件会根据同一飞书会话最近的 `planned` task 接管消息，不让普通 Hermes agent 直接编码，并启动 implementation run。

implementation run 会把最近一次 plan-only 的 `summary.md` 作为已确认计划注入 `input-prompt.md`，再交给 Codex。Codex prompt 会明确要求使用 superpowers 流程，包括 `using-git-worktrees`、`test-driven-development` 和 `verification-before-completion`；Hermes 会先提供 task-scoped 隔离 worktree/workspace，Codex 在其中执行，不直接修改原项目目录。

查看状态：

```text
/coding-status task_xxx
```

取消任务：

```text
/coding-cancel task_xxx
```

准备人工合并 test：

```text
/coding-prepare-merge-test task_xxx
```

## 运行产物

每次 run 会生成独立 artifacts：

```text
input-prompt.md
run-manifest.json
report.schema.json
stdout.log
stderr.log
summary.md
report.json
diff.patch
```

这些产物会被写入 Task Ledger。run 完成后，插件会把 `summary.md` 和 `report.json` 汇总为 `run_summary` 写入 LLM Wiki。Codex CLI 的最终结构化输出会落到 `report.json`，其中 `summary_markdown` 会由 Hermes 转存为 `summary.md` 并直接回写飞书。

## LLM Wiki 写入规则

插件会自动写入：

- `draft_knowledge`：飞书输入和需求草稿。
- `run_summary`：runner 输出总结、测试结果、风险和下一步。
- `project_profile`：registry bootstrap；后续人工确认后的稳定项目画像也应以同一结构写入。
- QA 经验：bug 修复任务可以通过 `--bug-of task_id` 关联原任务，并恢复原 run summary 上下文。

飞书 Project 链接、消息来源和图片等输入会进入 `draft_knowledge.source_refs`；Task Ledger 只保存对应 Wiki ref 和当前任务状态，不把 Wiki 当运行期状态库。

插件不会把 Task Ledger 的运行状态当成 LLM Wiki 事实源。任务状态、run 状态、artifacts 和人工决策仍以 Task Ledger 为准。

## Diff Guard

implementation 模式会在隔离 worktree/workspace 中执行，并根据 `WORKFLOW.md` 或 `project-registry.json` 里的路径策略检查变更：

- `allowed_paths` 之外的修改会被阻断。
- `forbidden_paths` 命中的修改会被阻断。
- `.env`、`deploy/`、发布脚本等高风险路径默认应放进 forbidden paths。

命中越权 diff 后，任务进入 `blocked`，等待人工处理。

## 开发与测试

运行完整测试：

```bash
rtk proxy python3 -m unittest discover -s tests -v
```

当前测试覆盖：

- Task Ledger 持久化和状态机。
- Project Resolver 匹配和低置信度处理。
- LLM Wiki 本地 adapter。
- Codex CLI runner 命令生成和 fallback report。
- Orchestrator plan-only / implementation 闭环。
- workspace 隔离和 diff guard。
- bug 任务关联原任务上下文。
- Hermes 插件注册、命令注册和 gateway trigger。
- 软链接安装脚本。

## 更多文档

- [PLAN.md](PLAN.md)：完整设计方案。
- [PLUGIN_USAGE.md](PLUGIN_USAGE.md)：本地 Hermes 接入说明。
- [plan_review.md](plan_review.md)：设计评审和高优先级问题记录。
