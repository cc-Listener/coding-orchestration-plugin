# Hermes Coding Orchestration Plugin

Hermes Coding Orchestration Plugin 是一个 Hermes 用户插件，用 Hermes Gateway 统一接收飞书编码需求，查询 LLM Wiki 补充上下文，并受控调用 Codex CLI 等编码工具完成 plan-only 或 implementation run。

这个项目的目标不是自动发布代码，而是把“手动切项目目录、手动开 Codex session、手动补上下文、手动整理结果”的流程，收敛成一个可审计、可回放、可沉淀知识的最小闭环。

## 版本定位

当前仓库实现的是 **MVP 版本**。

MVP 的目标是先跑通最小闭环：飞书 `/coding` 标准命令、Coding Mode 自然语言改写、Hermes 主控、Task Ledger 追踪状态、LLM Wiki 沉淀知识、Codex CLI 受控执行 plan-only / implementation / QA、人工确认 plan、人工触发 merge-test 和人工发布。

MVP 不追求大平台化，也不让普通自然语言绕过主控直接进入 plugin。标准入口是 `/coding <action>`；发送“进入coding”后，同会话自然语言会先由 LLM rewrite 成标准命令，高置信度直接执行，低置信度交给 Hermes 主 agent 基于插件上下文和内置 operator skill 继续判断，高风险候选等待确认。

当前仓库已经是 Hermes plugin，本轮能力重点是接入 Hermes native tools 和运行时能力：`pre_llm_call` 注入 active task/source health/next actions，`coding_task_create`、`coding_task_status`、`coding_task_run`、`coding_source_resolve`、`coding_lark_preflight` 供 Hermes 主 agent 结构化调用，Kanban 记录协作任务，terminal/process runtime 运行 Codex CLI。`/coding` 仍保留为人工命令面。

当前方案不引入 MCP，也不新增独立 Lark/Meegle server。来源和权限诊断走插件内 `SourceResolver`、`MeegleReader` 和文档 reader；blocked 只表示 hard human-blocked。Hermes `openai-codex` provider/OAuth 使用 `~/.hermes/auth.json`，standalone Codex CLI 可使用 `~/.codex/auth.json`，插件不会在两者之间复制或共享 auth。

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

使用前必须先完成 Hermes、Codex CLI、`lark-cli`、飞书应用权限和项目初始化检查；完整前置准备清单见 [PLUGIN_PREREQUISITES.md](PLUGIN_PREREQUISITES.md)。

### 本地软链接安装

当前硬约束：Hermes 必须直接加载本仓库的软链接目录，不使用 Git 安装副本，也不使用其他运行根。

插件入口固定为：

```text
~/.hermes/plugins/coding_orchestration -> 当前仓库/coding_orchestration
```

运行根固定为：

```text
~/.hermes/coding-orchestration
```

插件默认不读取 `CODING_ORCHESTRATION_ROOT` 作为运行根覆盖；即使 Hermes `.env` 残留该变量，也会使用上面的固定运行根。

Hermes `.env` 至少包含：

```text
CODEX_CLI_COMMAND=/absolute/path/to/codex
FEISHU_APP_ID=<Hermes Gateway 飞书应用 App ID>
FEISHU_APP_SECRET=<Hermes Gateway 飞书应用 App Secret>
```

飞书来源读取是安装硬门禁：终端默认 `lark-cli` 的 appId 必须等于 Hermes 的 `FEISHU_APP_ID`。OAuth token 按 appId 隔离，终端和 Hermes 使用不同飞书应用时，容易出现“终端能读文档、Hermes/Codex task 读不到”的错觉。

安装前先检查：

```bash
rtk lark-cli config show
```

如果输出里的 `appId` 不等于 `~/.hermes/.env` 里的 `FEISHU_APP_ID`，先绑定到 Hermes app：

```bash
rtk lark-cli config bind --source hermes --identity user-default
```

如果当前环境无法 bind，再用 Hermes app 显式初始化默认 `lark-cli`：

```bash
rtk lark-cli config init --app-id <FEISHU_APP_ID> --app-secret-stdin --brand feishu
```

然后为同一个 app 授权文档读取 scope：

```bash
rtk lark-cli auth login --scope "docx:document:readonly wiki:node:read wiki:node:retrieve" --no-wait --json
rtk lark-cli auth status --verify
```

`scripts/install_symlink.py` 默认会执行这个前置检查：如果终端默认 `lark-cli` appId 与 Hermes `FEISHU_APP_ID` 不一致，安装会失败并输出恢复动作。

安装命令：

```bash
rtk python3 scripts/install_symlink.py
rtk hermes plugins enable coding_orchestration
```

插件启用后需要重启 Gateway 或开启新的 Hermes session 才会生效：

```bash
rtk hermes gateway restart
```

安装后验证：

```bash
rtk hermes plugins list
rtk hermes gateway status
```

在飞书或 Hermes Gateway 对话里验证：

```text
/commands
/coding help
```

预期结果是 `/commands` 第一页能看到 `/coding help`、`/coding task`、`/coding project list`、`/coding status`、`/coding delete`，并且 `/coding help` 能输出完整命令说明。

### 本地软链接要求

本项目当前只允许使用本地软链接方式接入 Hermes。这样 Hermes 读取的就是当前 checkout 里的 `coding_orchestration/`，插件更新后只需要重启 Gateway，不需要同步到另一个安装副本：

```bash
rtk proxy python3 scripts/install_symlink.py --hermes-home ~/.hermes
```

软链接结果：

```text
~/.hermes/plugins/coding_orchestration -> 当前仓库/coding_orchestration
```

启用插件：

```bash
rtk hermes plugins enable coding_orchestration
```

如果 `~/.hermes/plugins/` 下存在历史安装副本，需要先移除或停用，避免 Hermes discovery 同时加载两个插件入口。

### 更新插件

软链接插件使用当前仓库更新流程：

```bash
rtk git pull --ff-only
rtk hermes gateway restart
```

更新后验证：

```bash
rtk hermes plugins list
rtk proxy curl -sS http://127.0.0.1:8642/health
```

Hermes Gateway 不会自动热加载 Python 插件代码；更新后必须重启。已经启动中的 Codex run 不会被中途换代码影响，更新只影响后续新的 Gateway 消息、命令和新 run。

## 1.0 TODO

MVP 跑通后，1.0 版本重点补齐团队化能力：

- Hermes plugin 本地软链接安装治理：安装自检、重复安装副本诊断、升级和回滚说明。
- Ledger migration：Task Ledger schema 可升级，已有任务不被破坏。
- LLM Wiki 团队化：从本地 adapter 扩展到团队共享知识层，并支持 verified / draft / run_summary 的审核晋升。
- Runner 扩展：补齐 Claude Code、Gemini runner，统一 capability 和 `report.json` schema。
- 飞书交互增强：确认卡、权限诊断、bug 单关联原 task、操作审计。
- 可观测性：`/coding doctor`、`/coding metrics`、stale workspace 清理和 blocked 原因统计。
- 新项目接入模板：`project_profile`、`WORKFLOW.md`、allowed / forbidden paths、测试命令和 merge-to-test 约束。

## Hermes 配置示例

```yaml
plugins:
  enabled:
    - coding_orchestration

coding_orchestration:
  enabled: true
  default_runner: codex_cli
  runners:
    # 可选：使用 Hermes autonomous-ai-agents/codex 对齐的 Codex 后端。
    hermes_autonomous_codex:
      command: codex
      skill_path: ~/.hermes/hermes-agent/skills/autonomous-ai-agents/codex/SKILL.md
  ledger_db: ~/.hermes/coding-orchestration/ledger.db
  run_root: ~/.hermes/coding-orchestration/runs
  workspace_root: ~/.hermes/coding-orchestration/workspaces
  llm_wiki:
    adapter: local
    root: ~/.hermes/coding-orchestration/llm-wiki
```

### 飞书来源索引

当飞书消息里包含 `project.feishu.cn/<project_key>/<type>/detail/<id>`、`/wiki/<token>` 或 `/docx/<token>` 链接时，插件只在 Hermes 层索引来源，不再提前读取正文，也不因为 Hermes 飞书权限不足阻断创建 task。Task Ledger 会记录 URL、token、Project key、工作项类型、`lark_cli_command` 和恢复动作；带外部来源的 plan-only 会以 `plan_source_read_elevated` 启动 Codex，让 Codex 在自己的 session 中执行 `rtk lark-cli` 读取正文。

Codex plan-only 若只有链接没有正文，不能假设文档内容；应优先执行来源上下文里的 `lark_cli_command`。如果 Codex 也因为授权、scope、网络或工具问题读不到，必须返回结构化 blocked，并给出授权 active lark-cli identity、补充可访问内容或直接粘贴需求正文的恢复动作。

飞书 Project 链接会保留 project key、工作项类型、工作项 id 和 URL，并继续推进 task 到 plan；读取失败时的恢复动作由 Codex report 给出，不再要求 Hermes 先读成功。

## Coding 命令入口规则

插件默认只处理显式 `/coding` 前缀消息。普通自然语言不会进入 `coding_orchestration`，也不会被 active task binding 自动吞掉；发送“进入coding”后，本会话自然语言才会进入 LLM rewrite 链路。

所有动作都必须写成 `/coding <action>`：

- 创建任务：`/coding task <需求>`
- 补充计划反馈：`/coding continue <反馈>`
- 提交需求变更：`/coding change <反馈>`
- 提交 QA/bugfix 反馈：`/coding bugfix <反馈>`
- 人工确认后进入实现：`/coding implement <task_id>`
- 查看、切换、退出：`/coding status|list|use|exit ...`

active task binding 用于 `/coding continue`、`/coding change`、`/coding bugfix`、`/coding implement` 这类命令在缺省 `task_id` 时找到当前任务；在 Coding Mode 中也会作为 rewrite 上下文。slash 命令只保留 `/coding <action>` 入口，不再兼容旧的 `/coding-*` 或 `/codex-*` 形式。

implementation 有硬门禁：必须先由 Codex 完成 plan-only，Hermes 将 phase 标为 `plan_ready` 后，再通过 `/coding implement <task_id>` 或 Coding Mode 高置信度 rewrite 进入 GitOps implementation。未进入 Coding Mode 时，`新建分支去干活`、`确认` 这类自然语言仍交给 Hermes 主 agent。

Coding Mode 低置信度不会由插件直接创建 task、启动 runner 或回复二次确认。插件会把原话、LLM 候选、拒绝原因、active task、最近 task 和 allowed commands 作为 handoff 文本交回 Hermes 主 agent；如果 Hermes 仍无法判断，就由主 agent 回复低置信度原因并要求用户确认标准 `/coding <action>` 或补充信息。

## Plugin 任务处理流程

插件处理一个 task 时，主链路如下：

```text
/coding <action>
  -> pre_gateway_dispatch 拦截
  -> Command Router 归一化 action
  -> Hermes 只索引飞书来源链接和可恢复读取命令
  -> Project Resolver 读取 LLM Wiki project_profile 识别项目
  -> Task Ledger 创建或更新 task 运行事实
  -> LLM Wiki 写入 draft_knowledge 或读取历史知识
  -> Prompt Builder 生成 input-prompt.md 和 run-manifest.json
  -> Runner Router 选择 Codex runner
  -> Codex 执行 plan-only / implementation / merge-test
  -> 收集 stdout、stderr、report.json、summary.md、diff.patch
  -> 校验 report schema、diff guard、测试结果
  -> 更新 Task Ledger
  -> 回写飞书状态
  -> 写入 LLM Wiki run_summary / QA 经验
```

状态推进规则：

- `/coding task`：创建 task，自动进入 plan-only，成功后进入 `plan_ready`。
- `/coding continue`：追加人工反馈，重新进入 plan-only。
- `/coding change`：记录需求变更，重新进入 plan-only 做变更影响分析和短计划。
- `/coding implement`：仅在 `plan_ready` 后允许，进入隔离 workspace 开发。
- `/coding bugfix`：复用原 implementation workspace、source branch 和上下文继续修复。
- `/coding merge-test`：续接 Codex session 执行 merge-to-test，发布测试环境仍人工。
- `/coding complete`：merge-test 已合入 test 后，由人工标记 task 完成。
- `/coding cancel`：取消任务或 run，保留排查材料。
- `/coding delete`：删除 task、active binding，并按参数清理 artifacts / LLM Wiki。

同一个 task 只维护一个 Codex session。首个 Codex run 创建 session 后，Hermes 会把 `resume_session_id`、`attach_command` 写入 `task_session` 和后续 `run-manifest.json`；之后的 plan retry、implementation、bugfix、merge-test 都优先 `codex exec resume <session_id> -`。visible session prompt 保持极简，只包含目标、来源、上下文 artifact 引用和本轮动作；Wiki 正文、已确认计划、实现上下文、详细执行契约和报告要求写入 run 目录中的 `context-index.json`、`wiki-context.md`、`confirmed-plan.md`、`implementation-context.md` 或 `run-instructions.md`。

普通 plan-only 使用 `plan_read_only` 权限 profile：Codex CLI 以只读沙箱运行，只产出计划，不允许修改项目文件。Hermes 创建 task 时只识别项目和索引飞书 Project/Wiki/Docx 来源，不再把飞书读取作为创建 gate；来源正文未注入时，会记录 URL、token、`lark_cli_command` 和恢复动作。带外部来源的 plan-only 使用 `plan_source_read_elevated`，Codex CLI 会以受控高权限运行，让 Codex 在自己的 session 中执行 `rtk lark-cli` 读取飞书、Swagger/OpenAPI 和 API 元数据；如果 Codex 也读不到，必须在结构化 report 中写清授权/scope/网络问题和恢复方案。plan-only 即使提权也只能读取上下文，不能修改项目文件，Hermes diff guard 会拦截任何 plan 阶段写入。implementation 和 QA run 使用受控高权限 Codex CLI session，以便自动安装依赖、访问私有源、启动测试/dev server、执行浏览器 QA、写入 `.gstack` QA 产物，并提交 QA 修复。边界不是放给 runner 自由发挥：子进程 cwd 仍是 task worktree，源码修改只允许落在当前 workspace；项目外写入只限依赖缓存、git metadata、dev server/browser 临时文件和 QA artifact；Hermes 继续用 diff guard 审计 workspace 内改动。

运行期事实只写 Task Ledger；长期知识只写 LLM Wiki；可审计材料写 run artifacts。

## 项目知识接入

项目识别和模块归属优先走 LLM Wiki 的 `project_profile`。初始化时不需要带入 `project-registry.json`；它只作为可选 bootstrap/fallback，不再作为长期项目知识事实源。

接入优先级：

1. LLM Wiki `project_profile`：项目名、别名、本地路径、模块关键词、允许/禁止修改范围、默认测试命令。
2. 项目内 `WORKFLOW.md`：执行规范，优先约束当前仓库。
3. 可选 `project-registry.json`：只有需要批量 bootstrap 时才创建，启动时会导入 LLM Wiki；文件不存在时使用空 registry。
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
/coding task --project 订单系统 修复发货失败
```

创建 Codex runner 任务：

```text
/coding task --runner codex_cli --project 订单系统 生成实现计划
```

飞书 Gateway 只有显式 `/coding task ...` 或 Coding Mode 中高置信度 rewrite 为 `/coding task ...` 的消息会创建任务并自动启动 plan-only run。补跑已有任务时，可以执行：

```text
/coding run task_xxx
```

执行 implementation run：

```text
/coding implement task_xxx
```

飞书里 plan-only 回写计划后，可以显式发送 `/coding implement task_xxx`。如果已进入 Coding Mode，自然语言确认会先经过 LLM rewrite，高置信度且信息完整时才会启动 implementation。

implementation run 会把最近一次 plan-only 的 `summary.md` 写入本次 run 的 `confirmed-plan.md`，把详细执行/报告契约写入 `run-instructions.md`，`input-prompt.md` 只引用这些 artifact，不再内联完整计划或插件规范。Codex visible prompt 只表达本轮动作：按已确认计划实现、缺依赖先安装并验证、不发布不部署不 merge。

任务切换：

```text
/coding list
/coding use task_xxx
/coding exit
/coding continue 这里补充计划上下文
/coding bugfix 这里有问题要在源分支修复
```

查看状态：

```text
/coding status task_xxx
```

取消任务：

```text
/coding cancel task_xxx
```

删除任务：

```text
/coding delete task_xxx
```

`/coding delete` 会删除 Task Ledger 记录、清理当前 active binding、删除该 task 生成的 LLM Wiki draft/run_summary，并清理插件 run/workspace 目录。运行中的 task 默认不能删除，需要先 `/coding cancel task_xxx`；确实要强制删除时使用：

```text
/coding delete task_xxx --force
```

保留本地 artifacts 或 Wiki 记录：

```text
/coding delete task_xxx --keep-artifacts
/coding delete task_xxx --keep-wiki
```

准备并执行 merge-to-test：

```text
/coding prepare-merge-test task_xxx
/coding merge-test task_xxx
/coding complete task_xxx
```

开发完成且验证通过后，task 状态进入 `ready_for_merge_test`，中文展示为“等待手动执行 merge test”。Hermes 会提示人工执行 `/coding merge-test <task_id>`；`/coding prepare-merge-test` 只是可选的人工准备标记，不会启动新的 implementation。

如果 task 处于 `blocked`，`/coding merge-test <task_id>` 会先做风险评估。只要能找到 implementation worktree 和 source branch，Hermes 就能进入风险确认：缺 Codex session 会开启新 session，缺 report、report 不完整、QA/依赖/浏览器受限、runner_failed/failed 或 diff guard 越权等都会先返回确认提示。人工确认后执行 `/coding merge-test <task_id> --accept-risk`，Hermes 会记录 `accepted_risk` 和 `blocked_merge_test_released`，把任务归一为 `ready_for_merge_test_with_known_gaps` 后继续 merge-test。缺 implementation run、缺 worktree、缺 source branch 或 task 已 cancelled 仍是硬阻断。

执行 `/coding merge-test <task_id>` 会让 Hermes 续接上一次 implementation 的 Codex session，要求 Codex 使用 `merge-to-test` skill：提交 source branch 上的已跟踪改动、push source branch、merge 到 `test` 并 push `origin/test`。成功后 Task Ledger 的 `TaskStatus` 会更新为 `merged_test`，并写入 `merge_records`；这代表已合入 test，但 task 还未完成。确认测试环境符合预期后，再发送 `/coding complete <task_id>` 人工标记为 `done`。测试环境发布仍然人工。

## 运行产物

每次 run 会生成独立 artifacts：

```text
input-prompt.md
run-instructions.md
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

本地 LLM Wiki 使用推荐目录结构，不再把新知识写成单个 `index.jsonl`：

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

写入规则：

- 每次 `upsert` 都写一份 `raw/sources/*.md` 原始来源快照，默认不覆盖，保证来源可追溯。
- 结构化知识写入 `wiki/*/*.md`，使用 YAML frontmatter 保存 `id`、`kind`、`project`、`status`、`source_refs`、时间戳和扩展字段。
- `project_profile` 写入 `wiki/entities/`，`draft_knowledge` 写入 `wiki/sources/`，`run_summary` / `qa_experience` 写入 `wiki/synthesis/`。
- 每次写入或删除都会自动刷新 `wiki/index.md`、`wiki/overview.md`，并追加 `wiki/log.md`。
- 旧版 `index.jsonl` 只做读取兼容，不再作为新知识写入格式。

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
