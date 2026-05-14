# coding_orchestration 插件使用说明

这个仓库保存 Hermes Coding Orchestration 插件源码。生产环境应该直接通过 Hermes 插件安装命令安装，软链接只用于本地 debug。

## 生产安装

```bash
hermes plugins install cc-Listener/coding-orchestration-plugin --enable
```

如果需要使用 SSH Git URL：

```bash
hermes plugins install git@github.com:cc-Listener/coding-orchestration-plugin.git --enable
```

插件启用后需要重启或开启新的 Hermes session 才会生效。

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

Hermes 配置启用示例：

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

## Hermes 集成原则

- Hermes Gateway 是唯一主控。
- 插件只注册 Hermes hook 和命令，不直接改 Hermes 主程序。
- Codex CLI、Claude Code、Gemini 都只是 Runner，不能直接操作飞书，不能自己决定项目，不能自动发布。
- Task Ledger 是运行期事实源。
- LLM Wiki 只保存 verified knowledge、draft knowledge、run summary、QA 经验，不保存任务状态事实。
- 同一飞书来源存在未结束 coding task 时，普通回复会被 plugin 会话级接管并返回 `skip`，不会再落到 Hermes 主 agent。

## 会话级接管

进入 coding 模式后，插件会用 Task Ledger 中的 `gateway_source` 建立 active task lock：

- plan 阶段补充：记录为 `plan_feedback`，自动重新进入 plan-only。
- implementation 后 bugfix：记录为 `implementation_feedback`，复用最近一次 implementation workspace 继续修复。
- run 正在 `queued` / `running`：记录为 `runtime_feedback`，不并发启动新的 runner。
- 项目或来源不明确：记录为 `human_clarification`，不让 runner 猜项目。

需要新开独立任务时，显式发送 `/coding-task ...`。需要释放当前接管时，使用 `/coding-cancel <task_id>` 关闭无关任务。

## 常用命令

```text
/coding-task --project 订单系统 修复发货失败
/codex-task --project 订单系统 生成实现计划
/coding-run task_xxx
/coding-implement task_xxx
/coding-prepare-merge-test task_xxx
/coding-status task_xxx
/coding-cancel task_xxx
```

低置信度项目识别会进入人工确认；implementation 模式会使用隔离 workspace，并在 run 完成后做 diff guard。发布和合并 test 仍然人工执行。

## LLM Wiki 自动写入

插件会在以下时机写入 LLM Wiki：

- 创建任务时，把飞书输入写为 `draft_knowledge`。
- Codex 或其他 runner 完成后，把 `summary.md` 与 `report.json` 汇总写为 `run_summary`。
- bug 任务通过 `--bug-of task_id` 关联原任务时，会读取原任务 run summary 注入新 prompt。

## 项目接入

项目识别优先走 LLM Wiki 的 `project_profile`，`project-registry.json` 只作为首次 bootstrap 和兜底。Hermes 启动时会把 registry 中的项目导入 LLM Wiki；后续新增项目、别名、模块关键词、允许修改范围和默认测试命令，推荐直接写入 `project_profile`。

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
