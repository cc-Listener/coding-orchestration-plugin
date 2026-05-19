# coding_orchestration 插件使用说明

这个仓库保存 Hermes Coding Orchestration 插件源码。当前版本定位为 **MVP**：先跑通飞书显式 `/coding` 输入、Hermes 主控、LLM Wiki 知识增强、Codex 受控执行、Task Ledger 留痕和人工发布的最小闭环。

生产环境应该直接通过 Hermes 插件安装命令安装，软链接只用于本地 debug。

## 生产安装

```bash
hermes plugins install cc-Listener/coding-orchestration-plugin --enable
```

如果需要使用 SSH Git URL：

```bash
hermes plugins install git@github.com:cc-Listener/coding-orchestration-plugin.git --enable
```

插件启用后需要重启 Gateway 或开启新的 Hermes session 才会生效：

```bash
rtk hermes gateway restart
```

安装后检查：

```bash
hermes plugins list
hermes gateway status
```

在飞书或 Hermes Gateway 对话里检查：

```text
/commands
/coding help
```

预期结果：

- `/commands` 第一页能看到 `/coding help`、`/coding task`、`/coding status`、`/coding delete`。
- `/coding help` 能输出完整命令说明。
- 普通自然语言不会进入 plugin。

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
- plugin 只处理显式 `/coding` 前缀消息；普通自然语言不会进入 plugin，也不会被 active task binding 自动接管。

## Coding 命令入口

进入 coding 流程必须使用 `/coding <action>`：

- `/coding task <需求>`：创建任务并自动进入 plan-only。
- `/coding continue <反馈>`：给当前 active task 补充计划反馈，并重新进入 plan-only。
- `/coding bugfix <反馈>`：给当前 active task 补充实现或 QA 修复反馈，并复用原 workspace 继续 implementation。
- `/coding implement <task_id>`：人工确认 plan 后进入 GitOps implementation。
- `/coding list|use|exit|status|cancel|delete`：查看、切换、退出、取消或删除任务。

active task binding 只用于显式 `/coding continue`、`/coding bugfix`、`/coding implement` 在缺省 `task_id` 时找到当前任务。同一个飞书会话里有多个任务时，用 `/coding list` 查看，用 `/coding use <task_id>` 切换当前任务。需要释放当前绑定时，使用 `/coding exit`；需要新开独立任务时，显式发送 `/coding task ...`。

implementation 有硬门禁：Codex 必须先完成 plan-only，Hermes 把 task phase 标为 `plan_ready` 后，人工通过 `/coding implement <task_id>` 才会启动 GitOps implementation。`确认`、`新建分支去干活` 等普通自然语言不会触发 plugin。

## Plugin 任务处理流程

```text
/coding task <需求>
  -> Hermes 拦截显式 /coding 命令
  -> 读取飞书 Project / Wiki / Doc 来源
  -> 从 LLM Wiki 读取 project_profile 识别项目
  -> 创建 Task Ledger 记录和 active binding
  -> 写 LLM Wiki draft_knowledge
  -> 生成 input-prompt.md / run-manifest.json
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
/coding bugfix 这里有问题要在源分支修复
/coding run task_xxx
/coding implement task_xxx
/coding prepare-merge-test task_xxx
/coding merge-test task_xxx
/coding status task_xxx
/coding cancel task_xxx
/coding delete task_xxx
```

低置信度项目识别会进入人工确认；implementation 模式会使用隔离 workspace/source branch，并在 run 完成后做 diff guard。人工测试通过后，`/coding merge-test <task_id>` 会续接上一次 Codex session 执行 `merge-to-test` skill，把 source branch push 到 origin、merge 到 `test` 并 push `origin/test`，然后自动把 Task Ledger 更新为 `done / merged_test`。测试环境发布仍然人工执行。

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
