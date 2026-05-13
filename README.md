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

## 项目配置

项目可以通过 `project-registry.json` 或项目内 `WORKFLOW.md` 接入。

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
- QA 经验：bug 修复任务可以通过 `--bug-of task_id` 关联原任务，并恢复原 run summary 上下文。

插件不会把 Task Ledger 的运行状态当成 LLM Wiki 事实源。任务状态、run 状态、artifacts 和人工决策仍以 Task Ledger 为准。

## Diff Guard

implementation 模式会在隔离 workspace 中执行，并根据 `WORKFLOW.md` 或 `project-registry.json` 里的路径策略检查变更：

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
