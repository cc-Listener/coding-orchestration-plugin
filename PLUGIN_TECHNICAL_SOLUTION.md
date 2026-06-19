# 定义全新的 workflow

## 1. 为什么要定义全新的 workflow

这份方案的中心不是“做一个 Hermes plugin”，而是定义一条新的团队研发 workflow：需求必须进入 Hermes 的 coding 主控，Hermes 负责自然语言意图改写、状态、知识和执行编排，Codex 等编码工具只作为受控 runner 执行具体编码动作。

当前人工流程里，需求来自飞书 Wiki、飞书文档、飞书项目、群聊口头沟通。人需要手动判断项目、切换目录、开启 Codex session、补充上下文、等待计划、确认开发、检查 diff、整理测试结果，再把 QA 反馈重新喂给 Codex。这个流程能跑，但它依赖个人记忆，不容易追踪，也很难把经验沉淀给下一次任务。

新的 workflow 要解决的是：

- 需求入口分散，缺少统一主控。
- Codex session 靠人手动开启和恢复，任务切换成本高。
- Plan、implementation、bugfix、merge-to-test 之间缺少可审计状态机。
- 历史需求、项目知识、QA 经验和 API 约定没有稳定沉淀。
- Hermes 主 agent 和编码流程容易抢同一条普通消息上下文；用户希望在 Coding Mode 中用自然语言表达，但系统不能误创建 task。
- Codex 是当前选择，但后续需要平滑扩展 Claude Code、Gemini 等编码工具。

因此，这个 plugin 只是 workflow 的实现载体。真正要落地的是一套规则：标准执行入口统一为 `/coding <action>`；command catalog 是命令、rewriter prompt、handoff allowed commands 和 help 文案的单一事实源；Coding Mode 中的自然语言必须先由 LLM rewrite 成标准命令；高置信度直接执行，低置信度交给 Hermes 主 agent 基于插件上下文和 plugin 内置 operator skill 继续判断，高风险候选确认后执行；Task Ledger 管运行事实；LLM Wiki 管长期知识；runner 只负责执行；人保留 plan 确认、测试验证和发布权。

## 2. 新 workflow 的一句话定义

飞书里显式 `/coding <action>` 命令会直接进入 plugin；发送“进入coding”后，同会话自然语言会先交给 Hermes LLM rewrite，生成标准 `/coding <action>`。高置信度且信息完整时直接进入同一条命令执行链路；低置信度或缺信息时，plugin 不执行、不回复二次确认，而是用 Gateway `rewrite` action 把原话、候选结果、active task、active_project、known projects、command catalog 和推荐 skill 交给 Hermes 主 agent；high-risk 候选等待人工确认。Hermes 创建 Task Ledger 事实记录，按需读取 LLM Wiki 推荐目录知识，生成受控 prompt，调用 Codex CLI 或未来其他 runner 执行，产出 artifact，再把 run summary、需求草稿和 QA 经验按 LLM Wiki 规范自动沉淀。

## 2.1 版本定位

当前方案定位为 **MVP 版本**，目标是先把“飞书需求 -> Hermes 主控 -> LLM Wiki 增强 -> Codex plan-only -> 人工确认 -> Codex implementation -> 人工测试 -> merge-to-test 辅助 -> 人工发布”的最小闭环跑通。

MVP 的判断标准不是功能完整，而是 workflow 可用、任务可追踪、run 可审计、知识能沉淀、Hermes 主 agent 不再抢 coding 上下文。

当前仓库已经是 Hermes plugin，本轮重点不是“再做 plugin 化”，而是深度使用 Hermes 原生能力。插件注册 `pre_gateway_dispatch` 和 `pre_llm_call`，并通过 `ctx.register_tool` 暴露 Hermes native tools：`coding_task_create`、`coding_task_status`、`coding_task_run`、`coding_source_resolve`、`coding_lark_preflight`、`coding_project_mcp_preflight`、`coding_project_intake_sync`、`coding_project_wbs_update`、`coding_project_state_transition` 和 `coding_project_bugfix_intake`。Hermes 主 agent 优先调用这些结构化 tools；`/coding <action>` 是人工入口和 fallback。

飞书项目 Story / Issue / WBS / 状态流转读写通过插件内私有 `FeishuProjectMcpAdapter` 完成。插件只读取 `~/.hermes/coding-orchestration/mcp.json` 中的 `mcpServers.feishu-project` 配置，并负责 MCP transport、工具白名单、写操作确认、审计和脱敏；runner 不直接配置飞书项目 MCP，不持有 `MCP_USER_TOKEN`，也不直接写飞书项目。Lark Wiki/Docx 来源解析仍走插件内 `SourceResolver` 和 Feishu/Lark 文档 reader。Source/auth/permission 问题统一投影为 TaskStatus 主状态 `needs_human`，具体原因放在 `source_status` / `source_recovery_action`；blocked 只表示 hard human-blocked。

飞书项目工作项关系写入 `project_workitem_bindings`：Story / 需求绑定 Hermes root task，WBS 行绑定 child task，Issue / Bug 绑定 bugfix task；Issue 可通过 `source_workitem_key` 归属到原需求 root task。已关联需求的 bugfix 使用 `branch_policy=inherit_root_branch` 并继承 root task 的 `source_branch`，merge-test / PR 由需求 root task 统一推进，避免每个 bugfix 长期分支再反复合并。

Hermes Codex 能力也被复用但边界清晰：Hermes `openai-codex` provider/OAuth 是模型能力，使用 `~/.hermes/auth.json`；standalone Codex CLI workspace edit 仍通过 Hermes terminal/process runtime 运行，可使用 `~/.codex/auth.json`。插件不会复制、导入或共享这两个 auth 文件。

MVP 保留的刻意限制：

- 标准执行命令只保留 `/coding <action>`；Coding Mode 自然语言只做 LLM rewrite，不新增第二套命令。
- 默认 runner 是 Codex CLI，Claude Code / Gemini 只保留接口。
- LLM Wiki 采用本地 adapter 和推荐目录结构。
- Task Ledger 使用本地 SQLite。
- merge-to-test 可以由 Hermes 续接 Codex session 执行，但发布仍然人工。
- plugin 安装路径固定为本地软链接，Hermes 必须直接加载当前仓库的 `coding_orchestration/`。

## 3. 前置环境配置

这套 workflow 要稳定运行，需要先完成 Hermes、runner、飞书权限、项目知识和本地目录的基础配置。

可执行检查项统一维护在 [PLUGIN_PREREQUISITES.md](PLUGIN_PREREQUISITES.md)。后续如果 Hermes `.env`、Codex CLI 路径、`lark-cli` 授权、飞书 scope、项目 LLM Wiki 初始化或 Kanban/Dashboard 规则发生变化，优先更新该清单，再同步本方案中的原则说明。

### 3.1 Hermes 环境安装

Hermes 的安装和基础配置直接以官方文档为准，本方案不重复维护安装步骤：

- Hermes 官方文档：https://hermes-agent.nousresearch.com/docs/
- Hermes 官方安装文档：https://hermes-agent.nousresearch.com/docs/getting-started/installation/
- Hermes 官方 Quickstart：https://hermes-agent.nousresearch.com/docs/getting-started/quickstart/

### 3.2 Hermes plugin 本地软链接安装与重启

当前硬要求：Hermes 只加载本地软链接插件目录，不使用 Git 安装副本。插件入口固定为：

```text
~/.hermes/plugins/coding_orchestration -> 当前仓库/coding_orchestration
```

飞书/Lark 授权硬规范：终端默认 `lark-cli` 的 appId 必须与 Hermes Gateway 的 `FEISHU_APP_ID` 一致。OAuth user token 按 appId 隔离，不能把一个飞书应用的用户授权复用于另一个飞书应用；因此安装前置检查必须拒绝 appId 不一致的环境。

前置检查：

```bash
rtk lark-cli config show
```

验收条件：

- `lark-cli config show` 输出的 `appId` 等于 `~/.hermes/.env` 的 `FEISHU_APP_ID`。
- `rtk lark-cli auth status --verify` 中 user identity 为 ready/verified。
- scope 至少包含 `docx:document:readonly`，并包含 `wiki:node:read` 或 `wiki:node:retrieve`。

修复命令：

```bash
rtk lark-cli config bind --source hermes --identity user-default
rtk lark-cli auth login --scope "docx:document:readonly wiki:node:read wiki:node:retrieve" --no-wait --json
```

如果 bind 无法在当前环境完成，再使用 Hermes app 显式初始化默认 `lark-cli`：

```bash
rtk lark-cli config init --app-id <FEISHU_APP_ID> --app-secret-stdin --brand feishu
```

插件安装脚本默认执行 appId 一致性 preflight；只有隔离测试允许 `--skip-preflight`。检查通过后，脚本会创建软链接、启用 `coding_orchestration` 插件并自动重启 Hermes Gateway。

安装命令：

```bash
rtk python3 scripts/install_symlink.py --hermes-home ~/.hermes
```

如果 `~/.hermes/plugins/` 下存在历史安装副本，需要移除或停用，避免两个插件入口同时注册 Gateway hook。安装后必须验证三件事：

```bash
rtk hermes plugins list
rtk hermes gateway status
```

在飞书或 Hermes Gateway 对话里验证：

```text
/commands
/coding help
```

预期结果：

- `/commands` 第一页能看到 `/coding help`、`/coding task`、`/coding project list`、`/coding status`、`/coding delete`。
- `/coding help` 能输出完整 coding workflow 命令说明。
- 默认普通自然语言不会进入 plugin；发送“进入coding”后，自然语言会进入 LLM rewrite 链路，高置信度直接执行，低置信度交给 Hermes 主 agent，高风险候选确认后执行。

当前仓库更新后必须重启 Gateway：

```bash
rtk git pull --ff-only
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
  runners:
    hermes_autonomous_codex:
      command: codex
      skill_path: ~/.hermes/hermes-agent/skills/autonomous-ai-agents/codex/SKILL.md
  ledger_db: ~/.hermes/coding-orchestration/ledger.db
  run_root: ~/.hermes/coding-orchestration/runs
  workspace_root: ~/.hermes/coding-orchestration/workspaces
  # 可选：只用于首次 bootstrap / 兜底迁移，不是运行期项目画像事实源。
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

### 3.4 飞书来源读取职责

需求来自飞书 Project、Wiki、Doc 或 Docx 链接时，Hermes 只负责识别项目并索引来源，不再把飞书正文读取作为 task 创建 gate。来源上下文记录 URL、token、Project key、工作项类型、`lark_cli_command` 和恢复动作；Codex plan-only 负责在自己的 session 中执行 `rtk lark-cli` 读取正文。项目识别仍优先走 LLM Wiki `project_profile`，缺失时再从文本中的项目名、文件夹名或路径定位本地项目并初始化项目画像。

当 Hermes 读不到飞书正文时，source context 会保留参考读取命令用于排障：

```bash
rtk lark-cli docs +fetch --api-version v2 --doc <url> --doc-format markdown --format json
```

带外部来源的 Codex plan-only 会使用 `plan_source_read_elevated` 权限 profile，并优先执行来源上下文中的 `lark_cli_command`。如果 Codex 也读不到，应在 `report.json` 中返回结构化 blocked，说明 lark-cli 授权、scope、网络或工具问题，并给出补充可访问内容或直接粘贴来源正文的恢复动作。

> 截图占位：`screenshots/04-feishu-project-permission.png`
>
> 截图内容建议：展示 task artifact 中的 `source_context`，能看到飞书 URL、token、`deferred_source_resolution=true` 和恢复动作。

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
- plugin 直接处理显式 `/coding` 命令；Coding Mode 中的普通自然语言先进入 LLM rewrite，高置信度合法命令可直接执行。
- Task Ledger 是运行期事实源。
- LLM Wiki 是知识增强层，不保存任务运行状态。
- Codex CLI 是 runner，不直接操作飞书、不决定项目、不自动发布。
- LLM rewrite 只能产出标准命令 JSON，不能自行创建 task、启动 Codex 或修改状态；所有执行都由 Hermes 校验后复用 `/coding` handler。
- 发布测试环境仍由人执行。

### 4.1 解耦改造工作阶段全线图

解耦不是一次性重构，而是一条长期治理轨道。工作阶段按“先合同、再服务、再 adapter、再治理回流”的顺序推进；每一阶段都必须保持现有 `/coding` 主流程可运行，并且不能破坏 plan-only 只读、人工确认、MCP 写入门禁、QA/merge-test 人工触发这些安全语义。

全线工作分为四个批次：

| 批次 | 覆盖阶段 | 目标 | 完成后形态 |
| --- | --- | --- | --- |
| A. 合同与边界 | 0-4 | 统一现状、配置、工具规格和端口合同 | 新能力先判断归属，再写实现 |
| B. 应用服务迁移 | 5-9 | 把 workitem、task、run、status、delivery 业务用例从 orchestrator 迁到 service/policy | `CodingOrchestrator` 退为命令 façade 和副作用编排入口 |
| C. Adapter 与资产拆分 | 10-14 | 把 prompt、runner、storage、source、skill 的外部系统细节收口到 adapter 或合同资产 | core/service 不感知 Codex CLI、MCP、Lark、SQLite、LLM Wiki 或 Hermes skill 细节 |
| D. 测试、文档、治理回流 | 15-17 | 清理旧实现耦合测试，更新事实文档，引入行数、hard code 和边界漂移检查 | 新增耦合能被测试、脚本或 review 发现 |

完整阶段如下：

| 阶段 | 目标 | 主责域 | 验收信号 |
| --- | --- | --- | --- |
| 0. 现状盘点 | 量化耦合、大文件、hard code、旧测试绑定 | 架构治理 | 行数、hard code、旧测试和主流程风险有清单 |
| 1. 架构合同 | 固化 core / service / port / adapter / host shell 边界 | 架构治理 + 文档合同 | 设计文档、实施计划、组件合同一致 |
| 2. 配置边界 | 收口路径、命令、域名和 env key 默认值 | Config / Adapter binding | core/service 不直接读 env、`Path.home()` 或本机路径 |
| 3. ToolSpec / IntentSpec | 工具端不再直接绑定 Hermes 注册细节 | Tool contract | Hermes native tools 和未来 MCP tools 共用同一规格 |
| 4. Ports 反转依赖 | 业务逻辑只依赖稳定能力合同 | Port contract | service 只依赖端口，不 import 具体 adapter |
| 5. MCP / WorkItem 解耦 | 飞书 Project MCP 读写进入工作项服务和 adapter | WorkItem service + MCP adapter | 读写经 `WorkItemPort`，写操作确认，token 不出 adapter |
| 6. Task 用例解耦 | 任务创建、source indexing、状态 payload 服务化 | Task service | task 创建、查询、source 索引主流程兼容 |
| 7. Run 生命周期解耦 | plan/implementation/QA/merge-test 生命周期服务化 | Run service | run blocker、timeout、phase、result mapping 有 contract |
| 8. StatusPolicy | 状态、known gaps、runner failure 投影集中 | Domain policy | 新状态只能经状态策略进入用户可见状态 |
| 9. DeliveryService | 父子任务、拆解、materialize、rollup 独立 | Delivery service | 交付拆解不污染主 task/run 生命周期 |
| 10. Prompt 模板治理 | prompt 文案和 source/mode 模板从 builder 拆出 | Prompt contract | `PromptBuilder` 只组合模板，模板有 contract tests |
| 11. Runner adapter 拆分 | Codex command、process、report、artifact 各自归属 | Runner adapter | runner 内部模块职责单一，runner façade 保持兼容 |
| 12. Storage / Knowledge 拆分 | ledger schema/query/mutation 和 LLM Wiki 写入拆开 | Storage + Knowledge adapter | application service 不依赖 SQLite 或 Wiki layout |
| 13. Source adapter 拆分 | URL 解析、Lark/Feishu/Meegle 读取、错误恢复收口 | Source adapter | 业务层只消费 `SourcePort` / `SourceResult` |
| 14. Skill 解耦 | core skill host-agnostic，Hermes skill 只映射 | Skill contract | core skill 不包含 Hermes、`/coding`、运行根或 ledger 细节 |
| 15. 旧测试清理 | 删除只保护旧 helper/旧文件形态的测试 | Test governance | 删除前已有等价 contract 或主流程覆盖 |
| 16. 文档同步 | 文档与真实边界同步，避免文档反向制造耦合 | 文档合同 | README、Usage、Project Map、Component Contract 一致 |
| 17. 长期治理 | 行数、hard code、边界漂移进入自动检查 | Architecture guard | 新增大文件、core/service hard code 或真实 token 模式会失败 |

阶段责任矩阵：

| 阶段范围 | 主责 | 协作 | 长期沉淀 |
| --- | --- | --- | --- |
| 0-1 现状与合同 | 架构治理 | 文档合同、测试治理、模块维护者 | 设计文档、实施计划、组件合同、风险清单 |
| 2-4 配置 / 工具 / 端口 | Config / Tool / Port contract | Hermes host adapter、MCP adapter、application service | `RuntimeConfig`、`ToolSpec`、`ports.py` 和 contract tests |
| 5-9 用例服务 | Application service | Ledger adapter、Source adapter、Runner adapter、Presenter | `TaskService`、`RunService`、`DeliveryService`、`WorkItemService` 和 domain policy |
| 10-13 Adapter 与资产 | Prompt / Runner / Storage / Source adapter | Application service、Report policy、Knowledge adapter | prompt 模板、runner 子模块、storage repository、`SourceResult` |
| 14 Skill 分层 | Skill contract | Hermes binding、Tool contract | host-agnostic core skill 和 Hermes binding skill |
| 15-17 测试与治理 | Test governance + Architecture guard | 文档合同、模块维护者 | contract/main-flow tests、行数检查、hard code 检查、边界漂移检查 |

阶段执行合同：

1. 每轮只迁移一个职责域，其他模块只做必要 façade 适配。
2. 先补 contract 或主流程测试，再迁移实现；旧私有 helper 测试只能在等价覆盖存在后删除。
3. `CodingOrchestrator` 迁移期只做 host façade、兼容 wrapper 和副作用接线，不再新增核心业务规则。
4. core/service/tool 层不得新增 Hermes 命令、`lark-cli`、`Path.home()`、`os.getenv()`、`subprocess`、token key 或真实 secret 模式。
5. 阶段结束必须更新项目事实文档或实施计划，并跑对应聚焦测试；发布前跑完整单测、architecture guard、diff check 和敏感扫描。

长期迭代操作模型：

| 步骤 | 要做什么 | 责任人/主责域 | 输出物 |
| --- | --- | --- | --- |
| 1. 定域 | 只选择一个职责域作为本轮主线，例如 run orchestration、source adapter、tool dispatcher 或 skill contract | 本轮主责域 owner | `task_plan.md` 阶段条目、实施计划状态 |
| 2. 建基线 | 记录当前行数、hard code 命中、相邻主流程测试、旧 helper 测试依赖 | Architecture guard + Test governance | 行数和风险基线、可回归测试列表 |
| 3. 先写合同 | 先补 service、port、policy、adapter 或 presenter contract tests；主流程风险补 flow tests | 主责域 owner + Test governance | 失败到通过的 contract/main-flow tests |
| 4. façade 迁移 | 外部入口保持不变，业务规则只迁入本轮权威模块，orchestrator 只做 wrapper/callback | 主责域 owner | 小步代码迁移、兼容 wrapper、无用户行为漂移 |
| 5. 清理旧耦合 | 只删除已有等价覆盖的旧私有 helper 或旧文件形态测试 | Test governance | 保留/改写/删除记录 |
| 6. 同步事实 | 更新 project map、component contract、conventions、实施计划和技术方案中的边界描述 | 文档合同 | canonical docs 与代码边界一致 |
| 7. 回流治理 | 把新增大文件、hard code 或边界漂移加入 architecture guard 或 watchlist | Architecture guard | guard fail/watchlist 更新、发布 gate 可复查 |

长期职责判定规则：

- 新业务规则优先落到 application service 或 domain policy，不落到 Gateway controller、presenter 或 adapter。
- 新外部系统绑定优先落到 adapter，并通过 port 或 ToolSpec 暴露能力，不让 core/service 直接 import host 细节。
- 新用户可见文案落到 presenter 或 host binding skill，不推进 task/run 状态。
- 新 Hermes/MCP/CLI 注册只做 operation id 到 service/adapter 的分发，不直接拼业务流程。
- 新测试优先保护 contract、主流程、安全边界和治理脚本，不再只保护旧私有 helper 名称。

跨切面零耦合集成矩阵：

| 切面 | 权威层 | Hermes 集成职责 | 明确禁止 | 长期验收 |
| --- | --- | --- | --- | --- |
| 工具端 | `ToolSpec` + operation dispatcher | 注册 native tool / CLI handler / future MCP tool，把 host payload 转成 `operation_id + args` | 在 tool 注册层直接写业务规则、状态推进、ledger mutation | 同一 operation spec 能服务 Hermes native tools 和未来 MCP tools |
| MCP / WorkItem | `WorkItemPort` + `WorkItemService` + MCP adapter | 注入本机 token 环境、调用 adapter、输出脱敏结果 | core/service 持有 `MCP_USER_TOKEN`、拼 JSON-RPC、绕过写确认 | 写操作有确认和审计，token 只存在 adapter 边界 |
| Skill core | `coding-operator-core` / `coding-health-core` | 不承载 host 绑定，只描述通用意图、状态和修复口径 | core skill 出现 Hermes、`/coding`、运行根、ledger 或本机命令 | core skill 可迁移到其他 host，仍能表达完整工作法 |
| Hermes binding skill | `hermes-coding-operator` / `hermes-coding-health-check` | 把 core intent 映射到 `/coding`、Hermes CLI、`lark-cli` 恢复命令 | 在 binding skill 中沉淀通用业务规则或状态机 | binding skill 只是 host adapter，删除后不影响 core contract |
| Gateway / command | `gateway_command_controller.py` + executor host shell | 解析 host event、生成 route metadata、委托 service / façade | controller 写 ledger、启动 runner、发送 Gateway 消息或推进状态 | controller 可纯测试，副作用只在 host shell / application service |
| Run orchestration | `RunService` + projection modules | 连接 runner、ledger、manifest、workspace service 的边界 | projection helper 启动 subprocess、写 ledger、读写 workspace/git、发送消息 | projection 只返回 payload / decision，副作用有明确 owner |
| Source / Lark | `SourcePort` + source adapters | 索引来源、传递可恢复读取命令和 `SourceResult` | 业务层消费 reader-specific dict，创建 task 前强依赖正文读取成功 | Task / prompt / context 只消费稳定 source result |
| Storage / Knowledge | repository + `KnowledgePort` | 初始化运行根并调用 adapter | application service 手写 SQL、知道 LLM Wiki layout 或复制运行根内容 | schema/query/wiki layout 可独立演进 |
| Presentation | presenter modules + host binding copy | 渲染用户可见文案、状态摘要和恢复动作 | presenter 推进 task/run 状态、触发 runner 或写 ledger | 文案可单测，状态变化由 service / state machine 证明 |
| 大文件 / hard code | `architecture_guard.py` + 文档合同 | 输出 watchlist、fail gate 和 review checklist | 新增大文件、host command、`Path.home()`、`os.getenv()`、token key 当临时例外 | 新增 core/service/tool hard code 会失败；超阈值文件需拆分或登记 |

当前长期执行队列固定为：

| 任务 | 主责 | 状态 | 退出标准 |
| --- | --- | --- | --- |
| Task 28. Workspace / Git / Diff checkpoint service | Run support service + Diff guard | Done | workspace、branch、checkpoint、QA artifact、run manifest/session policy、session metadata 字段投影与启动期 manifest update projection 已迁出 |
| Task 29. Command / Gateway controller 瘦身 | Host shell | In Progress | 已迁出 route plan、handler key、reply mode、immediate reply 分发、custom route executor、pending action executor 和 active context helper；继续把执行副作用下沉 |
| Task 30. Run orchestration service 闭环 | Run application service | Complete | 已迁出后台等待完成、失败 transition、merge-test pending action、run completion projection、runner/checkpoint failure report projection、diff guard / implementation commit missing blocked report 构造、run report refinement projection、run diff guard observation、runner dispatch、run status transition、run evidence observation、observed run report 构造、stale completion 观测、session/prompt/start selection、run manifest session metadata host writeback、run artifact 文件写入、run artifact path contract、report/summary artifact 读写、run report summary excerpt、execution policy artifact 读取、completion/report/project writeback payload、Project writeback host gate/callback、summary writer host callback、start_run 与 active run reconcile 的 artifact / agent_run / merge-test record 写回 payload 聚合、run ledger host callback、run session host callback、completed run 与 active run reconcile 的 run summary writer payload 聚合、fresh completed run 写回协调和 active run reconcile 写回协调等规则；`run_completion_writeback_service.py` 和 `run_reconcile_writeback_service.py` 分别负责 fresh completed 与 active reconcile 的完成态写回协调。后续大文件治理、hard code 清理和 Hermes/Skill 深度解耦进入 Task 31+ / Task 18/20 长期治理；Task 32 第一切片后 `orchestrator.py` 当前约 4692 行。 |
| Task 31. SourcePort 消费闭环 | Source adapter + Task service | Planned | orchestrator、TaskService、prompt/context 不再消费 reader-specific dict |
| Task 32. Tool / MCP operation dispatcher | Tool contract + WorkItem adapter | In Progress | 已新增 `ToolOperationDispatcher`，Hermes native tool 注册层只包装 `ToolSpec.operation_id`，不再维护 `operation_id -> CodingOrchestrator.tool_*` 映射；后续继续让 CLI tool-equivalent 子命令和 future MCP tool 共用同一 dispatcher |
| Task 33. Skill 零耦合复查 | Skill contract | Planned | core skill 零 Hermes 细节，binding skill 只做 host 映射 |
| Task 34. Orchestrator façade 降载 | Architecture guard | Planned | `orchestrator.py` 先降到 3000 行以内，再退出 legacy large-file watchlist |
| Task 35. Legacy test final cleanup | Test governance | Planned | 旧私有 helper / 旧文件形态测试全部有保留、改写或删除记录 |
| Task 36. Release readiness and operating contract | 文档合同 + 运行治理 | Planned | 完整单测、architecture guard、diff check、敏感扫描和最小 Hermes smoke 形成发布 gate |

Task 30 最新补充：`run_checkpoint_preparation_service.py` 已承接 QA / merge-test checkpoint preparation callback 选择、调用和 manifest update payload 构造；它只调用注入 callback 并返回 `manifest_updates`，不直接 mutate manifest、不写 artifact/ledger/report/summary、不启动 runner、不推进状态。mode 到 checkpoint kind/target branch 选择仍归 `run_start_selection_projection.py`，manifest 文件写入仍归 artifact service，implementation dirty-check 后置 manifest 写回仍是后续切片。

Task 30 最新补充：`run_implementation_checkpoint_service.py` 已承接 implementation dirty 后置 checkpoint 生成和 manifest artifact writeback callback 接线；它只消费已计算好的 dirty flag，调用注入 checkpoint / manifest writer callback，不判断 dirty、不构造 blocked report、不写 ledger/report/summary、不启动 runner、不推进状态。dirty observation 仍归 `run_evidence_observation_service.py`，blocked report refinement 仍归 `run_report_refinement_projection.py`。

Task 30 最新补充：`run_manifest_session_writeback_service.py` 已承接 runner session metadata 到 run manifest 的 host callback 接线；它只消费已解析 `session_id`，复用 `run_manifest_service.build_manifest_session_fields()` 更新 manifest object/dict 并调用注入 manifest metadata writer，不解析 stdout、不写 ledger/report/summary、不启动 runner、不推进状态。session id 来源、task session ledger update 和 Codex attach/resume command 规则仍归原边界。

Task 30 最新补充：`run_completion_writeback_service.py` 已承接 fresh completed run 的 completion projection、stale observation、状态 transition、ledger/session/summary/project writeback 和 final result payload 协调；它只消费已完成 runner result 的投影数据和注入 callback，不启动 runner、不执行 diff guard、不收集 QA evidence、不判断 dirty、不准备 checkpoint、不解析 stdout、不直接持有 `TaskLedger`、`RunSummaryWriter`、`WorkItemService` 或 MCP adapter。

Task 30 最新补充：`run_reconcile_writeback_service.py` 已承接 active run reconcile 完成态的 completion projection、最终 `report.json` 写回、状态 transition、ledger upsert、runner session update、summary writer callback 和 result payload 协调；它只消费已归一化 report 与注入 callback，不读取 workspace、不启动 runner、不执行 diff guard、不收集 QA evidence、不判断 dirty、不准备 checkpoint、不解析 stdout、不直接持有 `TaskLedger`、`RunSummaryWriter` 或 MCP adapter。Task 30 closure cleanup 已完成，后续大文件治理、hard code 清理和 Hermes/Skill 深度解耦不再挂入本任务。

大文件和 hard code 是专项治理对象，不作为“顺手优化”处理：

- `orchestrator.py` 目前仍是唯一核心大文件债务，当前约 4692 行；Task 30 已关闭，短期目标是继续通过 Task 31+ / Task 34 进入 3000 行以内的 façade 降载。
- 新增业务模块超过 600 行必须说明职责边界；超过 1000 行必须拆分或登记明确例外。
- core/service/tool 层不允许新增 Hermes 命令、`lark-cli` 命令、`Path.home()`、`os.getenv()`、`subprocess`、token key 或真实 secret 模式。
- hard code 只允许落在 config、adapter binding、domain policy 或明确的测试 fixture 中。
- 每个阶段完成后都要同步 `docs/project-map.md`、`docs/component-contract.md`、`docs/conventions.md` 或实施计划，并运行对应聚焦测试；发布前必须跑完整单测和 `scripts/architecture_guard.py`。

## 5. Hermes 集成方式

plugin 通过 Hermes 插件系统加载，不直接改 Hermes 主程序。当前只允许使用本地软链接方式，让 Hermes 直接加载当前仓库的 `coding_orchestration/`：

```bash
rtk proxy python3 scripts/install_symlink.py --hermes-home ~/.hermes
```

如果历史安装副本仍在 `~/.hermes/plugins/` 下，需要先移除或停用，保证 discovery 只看到 `coding_orchestration` 这个软链接入口。安装脚本会自动启用插件并重启 Gateway；如果自动动作失败，按脚本提示手动执行 `rtk hermes plugins enable coding_orchestration` 和 `rtk hermes gateway restart`。

Hermes 加载后，plugin 注册：

- `pre_gateway_dispatch` hook：在 Hermes 主 agent 接手前识别 `/coding` 命令、`进入coding` / `退出coding`，并在 Coding Mode 下触发 LLM rewrite。
- `/coding` 命令组：统一入口。
- slash 命令只保留 `/coding <action>` 入口，不再兼容旧的 `/coding-*` 或 `/codex-*` 形式。

最新规则非常明确：

- `/coding task ...` 会进入 plugin。
- `/coding continue ...` 会进入 plugin。
- `/coding change ...` 会进入 plugin。
- `/coding bugfix ...` 会进入 plugin。
- `/coding implement ...` 会进入 plugin。
- 默认普通自然语言不会进入 plugin。
- 发送“进入coding”后，同会话普通自然语言进入 LLM rewrite；高置信度且信息完整时直接执行，低置信度交给 Hermes 主 agent 基于插件上下文继续判断。
- active task binding 给显式 `/coding` 命令和 rewrite 候选补默认 task 上下文；执行仍统一走 `/coding` handler。

这解决了之前最影响实际使用的问题：默认情况下 Hermes 主 agent 和 plugin 不抢自然语言消息；进入 Coding Mode 后，plugin 只做“自然语言 -> 标准命令候选 -> 高置信度执行 / 低置信度 handoff / 高风险确认”的受控链路。

> 截图占位：`screenshots/09-hermes-plugin-command-registration.png`
>
> 截图内容建议：展示 Hermes `/commands` 的返回结果，第一页能看到 `/coding help`、`/coding task`、`/coding project list`、`/coding status`、`/coding delete` 等插件预设命令。

## 6. 标准命令

团队只需要记住一个前缀：`/coding`。

```text
/coding help
/coding task <需求>
/coding project list
/coding project init <project_path_or_name>
/coding project use <project_name>
/coding project status
/coding project clear
/coding status <task_id>
/coding list
/coding use <task_id>
/coding exit
/coding continue <反馈>
/coding change <反馈>
/coding bugfix <反馈>
/coding run <task_id>
/coding implement <task_id>
/coding qa <task_id>
/coding prepare-merge-test <task_id>
/coding merge-test <task_id>
/coding complete <task_id>
/coding cancel <task_id|run_id>
/coding delete <task_id> [--keep-artifacts] [--keep-wiki] [--force]
```

关键语义：

- `/coding task`：创建任务，识别项目，写 Task Ledger，写 LLM Wiki draft，自动进入 plan-only。
- `/coding project list/init/use/status/clear`：管理会话级 active_project。project init 只扫描项目并写入或刷新 LLM Wiki，不创建 task、不启动 runner。
- `/coding continue`：补充计划反馈，重新进入 plan-only。
- `/coding change`：记录需求变更，重新进入 plan-only 做变更影响分析和短计划。
- `/coding bugfix`：补充 QA 或实现反馈，复用原 implementation workspace 修复。
- `/coding implement`：人工确认 plan 后进入 GitOps implementation。
- `/coding qa`：人工选择进入测试，续接 implementation workspace 执行 QA；implementation 完成后不会自动进入测试。
- `/coding merge-test`：人工测试通过后，续接 Codex session 执行 `merge-to-test` skill。
- `/coding complete`：merge-test 已合入 test 后，由人工标记 task 完成。
- `/coding delete`：删除 task、active binding、关联 LLM Wiki draft/run_summary 和本地 run/workspace artifact。

active_project 是会话级上下文，不进入 Task Ledger。先 `/coding project init <path>` 或 `/coding project use <name>` 后，用户在 Coding Mode 中说“订单列表加筛选”这类新需求时，如果没有显式项目，Hermes 会把 active_project 注入新 task；active task 优先级更高，active task 与 active_project 冲突时必须追问，不自动切换。

普通确认语，例如“可以了”“新建分支去干活”，不会绕过 rewrite 直接触发 implementation。若处于 Coding Mode，Hermes 会先用 LLM rewrite 将其改写为标准命令，例如 `/coding implement <task_id>`；高置信度且信息完整时直接执行，低置信度时交给 Hermes 主 agent 继续判断。

> 截图占位：`screenshots/10-coding-help-command.png`
>
> 截图内容建议：飞书或 Hermes 对话里执行 `/coding help` 的返回结果，能看到完整命令列表、Coding Mode 和自然语言 rewrite 的说明。

### 6.1 Coding Mode LLM rewrite

Coding Mode 的目标是降低用户输入成本，但不牺牲安全边界。用户发送“进入coding”后，本会话自然语言会进入 rewrite 链路：

```text
自然语言消息
  -> Hermes 收集上下文：active_task_id、active_task_status、known_task_ids、has_media、media_types、allowed_commands
  -> 调用 LLM rewrite prompt
  -> 校验 JSON schema 和 allowed_commands
  -> 按 confidence / risk_level 判断
  -> 高置信度：直接调用现有 `/coding <action>` handler
  -> 低置信度：通过 Gateway rewrite handoff 给 Hermes 主 agent
  -> 需要确认时：保存 pending rewrite，用户确认后再执行
```

关键约束：

- LLM 只做命令改写，不执行命令。
- 所有执行都复用现有 `/coding <action>` handler，不新增隐藏动作。
- 查询类自然语言，例如“现在有多少个 task”“task_xxx 现在怎么样”，绝不能改写成 `/coding task`。
- 当前 task 反馈类自然语言，例如“查看最近对话记录，rewrite 表现不符合预期”“这个实现不符合预期”，应在 active task 存在时改写成 `/coding bugfix <反馈>`；它们不是 `/coding list`、`/coding status` 或 `/coding task`。
- 纯元讨论类自然语言，例如“讨论一下 rewrite 方案”“整理 prompt 设计原则”，如果没有要求修复当前 task，则 intent=unknown。
- 需求变化优先改写为 `/coding change <反馈>`。
- 已有实现问题、QA 反馈、截图样式问题优先改写为 `/coding bugfix <反馈>`。
- plan 补充优先改写为 `/coding continue <反馈>`。
- `cancel`、`delete` 属于 destructive 动作，即使高置信度也必须确认；其他命令可由 LLM 通过 `needs_confirmation=true` 要求人工确认。
- 低置信度不得创建 task、不得启动 runner，也不得由插件直接回复确认；必须把原话、候选结果、active task、known tasks 和 allowed commands 交给 Hermes 主 agent。
- 如果用户输入包含 `[Image]` 但 Gateway 没有捕获 media，Hermes 必须阻止启动 Codex，并提示重发图片或图片链接。

LLM rewrite 的 system prompt：

```text
你是 Hermes Coding Plugin 的自然语言命令改写器。

你的唯一任务：把用户输入的自然语言，改写为一个合法的 `/coding <action>` 命令候选。
你不能执行命令，只能输出 JSON。
你不能创建 task、不能启动 Codex、不能修改状态。
真正执行由 Hermes 校验后完成；高置信度直接执行，高风险候选才等待确认。

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
10. 低置信度必须 needs_human_review=true，不能给出可直接执行的命令；Hermes 会把这类消息交给 Hermes 主 agent 接管。
11. 如果无法判断用户意图，intent=unknown，canonical_command=null。
12. 如果用户输入包含图片占位或 has_media=true，保留原始反馈文本，不要丢失图片语义。
13. 如果用户在 active coding task 上下文中指出当前功能、实现、文档或系统表现“不符合预期”“有问题”“需要优化”，这属于当前 task 的反馈，优先改写为 `/coding bugfix <反馈>`；不要误判为元讨论。
14. 如果用户只是抽象讨论 plugin、rewrite 规则、方案设计或文档内容，且没有要求检查/修复当前 task，则属于元讨论，intent=unknown，canonical_command=null。
15. “查看最近对话记录，自然语言 rewrite 表现不符合预期”在 active task 存在时，应理解为要求检查最近对话并修复当前 rewrite 表现，不能改写为 `/coding list`、`/coding status` 或 `/coding task`，应优先改写为 `/coding bugfix <原文>`。
16. 输出必须是严格 JSON，不要 markdown，不要解释。
```

LLM rewrite 的 user prompt 模板：

```text
请根据以下上下文，将 user_text 改写为一个 `/coding <action>` 命令候选。

上下文：
{
  "user_text": "{{用户原文}}",
  "coding_mode_enabled": {{true/false}},
  "active_task_id": "{{当前会话绑定 task_id 或空}}",
  "active_task_status": "{{active task status 或空}}",
  "has_media": {{true/false}},
  "media_types": {{媒体类型数组}},
  "known_task_ids": {{最近 task_id 数组}},
  "allowed_commands": [
    "/coding help",
    "/coding task <需求>",
    "/coding list",
    "/coding use <task_id>",
    "/coding exit",
    "/coding status <task_id>",
    "/coding continue <反馈>",
    "/coding change <反馈>",
    "/coding bugfix <反馈>",
    "/coding prepare-merge-test <task_id>",
    "/coding merge-test <task_id>",
    "/coding complete <task_id>",
    "/coding cancel <task_id|run_id>",
    "/coding restore <task_id>",
    "/coding delete <task_id> [--keep-artifacts] [--keep-wiki] [--force]"
  ]
}

请只输出 JSON。
```

输出 schema：

```json
{
  "intent": "create_task | list_tasks | select_task | exit_task | status_task | plan_feedback | requirement_change | bugfix_feedback | run_plan | implement | prepare_merge_test | merge_test | complete_task | cancel | restore_cancelled_task | delete | help | unknown",
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

Hermes 后处理规则：

- `canonical_command` 必须匹配 allowed commands，否则降级为 `unknown`。
- `confidence < 0.85` 时不执行，返回 Gateway `rewrite` action，把插件上下文交给 Hermes 主 agent。
- `missing` 非空时不执行，交给 Hermes 主 agent 判断是否能补足或向用户追问。
- `needs_human_review=true` 时不执行，交给 Hermes 主 agent 接管。
- `needs_confirmation=true` 时保存 pending rewrite，等待用户回复“确认”。
- 高置信度且 `needs_confirmation=false` 时直接调用 `_handle_explicit_gateway_command(canonical_command, event, gateway)`。
- `risk_level=destructive` 永远要求明确确认。
- 用户确认或高置信度自动执行时，Hermes 调用 `_handle_explicit_gateway_command(canonical_command, event, gateway)`。

正例必须被测试覆盖：

```json
{
  "user_text": "查看最近对话记录，自然语言的rewrite表现不符合预期",
  "coding_mode_enabled": true,
  "active_task_id": "task_xxx",
  "has_media": false
}
```

期望输出：

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
  |     -> 未进入 Coding Mode：放行给 Hermes 主 agent
  |     -> 已进入 Coding Mode：调用 LLM rewrite 生成 canonical_command，高置信度直接执行，低置信度 handoff 给 Hermes 主 agent
  |
  +-- /coding <action>
        |
        v
Command Router
  |
  +-- normalize action
  |     /coding task / continue / change / bugfix / implement / merge-test / complete / delete ...
  |
  v
Source Context Reader
  |
  +-- 飞书 Project / Wiki / Doc 链接
  |     -> Hermes/Gateway 优先读取并注入正文摘要
  |     -> 读取失败时只索引 URL、token、错误和恢复动作
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
  -> new / needs_human / planned

/coding continue
  -> 追加人工反馈
  -> 重新进入 plan-only
  -> planned 或 blocked

/coding change
  -> 追加需求变更
  -> 重新进入 plan-only 做变更影响分析和短计划
  -> planned 或 blocked

/coding implement
  -> 要求当前 task 已 planned
  -> TaskStatus: running；AgentRunStatus 主状态为 running，queued 只保存在 raw_status / status_detail
  -> 开发完成且验证通过：ready_for_merge_test
  -> 开发完成但有明确验证缺口：ready_for_merge_test + known_gaps=true / verification_limitations
  -> 无法安全完成实现：blocked / failed（runner_failed 只作为 failure_type / raw_status 保留）

/coding bugfix
  -> 要求存在 active task 或显式 task_id
  -> 复用 implementation workspace / source branch
  -> 复用 task 级 Codex session，仅注入本轮修复反馈
  -> TaskStatus: running；AgentRunStatus 主状态为 running，queued 只保存在 raw_status / status_detail
  -> ready_for_merge_test（缺口用 known_gaps=true 表达）或 blocked

/coding merge-test
  -> 要求 task 已 ready_for_merge_test
  -> blocked task 先做风险评估；缺 implementation run/worktree/source branch/cancelled 为硬阻断
  -> 其他 blocked 风险通过 --accept-risk 记录人工接受后归一为 ready_for_merge_test，并写入 known_gaps / verification_limitations
  -> 人工触发后续接同一个 task 级 Codex session，TaskStatus 进入 running；AgentRunStatus 主状态为 running，queued 只保存在 raw_status / status_detail
  -> merge-test 成功：merged_test
  -> merge-test 无法安全完成：blocked / failed（runner_failed 只作为 failure_type / raw_status 保留）

/coding complete
  -> 要求 task 已 merged_test
  -> 人工确认测试环境符合预期后标记 done

/coding cancel
  -> cancelled

/coding delete
  -> 删除 Task Ledger 记录、active binding、可选清理 LLM Wiki 和 artifacts
```

普通自然语言不会绕过 rewrite 推进状态。比如“确认”“可以了”“新建分支去干活”在 Coding Mode 中必须先被 LLM rewrite 成标准命令；高置信度且信息完整时可直接触发 implementation，低置信度时交给 Hermes 主 agent；未进入 Coding Mode 时仍会放行给 Hermes 主 agent。

### 7.3 数据写入规则

每个阶段写入位置不同：

```text
Task Ledger
  -> 运行期事实：status、phase、project_path、runs、workspace、resume session、human decisions

LLM Wiki
  -> 长期知识：draft_knowledge、project_profile、run_summary、QA 经验、verified knowledge

Run Artifacts
  -> 可审计材料：input-prompt.md、run-manifest.json、stdout/stderr、run-log.md、events.compact.jsonl、report.json、summary.md、diff.patch

Feishu Reply
  -> 人可读状态：task_id、项目、计划摘要、风险、下一步命令、artifact 路径
```

边界必须清楚：Task Ledger 管“现在任务是什么状态”，LLM Wiki 管“以后可复用的知识”，artifact 管“这次 run 到底发生了什么”。

### 7.4 自适应执行策略

Hermes 不复制 Codex/Superpowers 的 run 内执行流程。Hermes 只在 runner 启动前做粗粒度策略选择：

```text
task / feedback
  -> classify_execution_policy
  -> fast_fix | standard_change | guarded_change
  -> 选择 plan、context、verification、browser QA、人工 gate 和 timeout 预算
  -> Codex 按策略在单次 run 内执行
```

初始策略模型位于 `coding_orchestration/execution_policy.py`：

- `fast_fix`：低风险小修复、ignore/config housekeeping、文案和明确单点反馈；默认 inline plan、minimal context、targeted verification，不启用浏览器 QA。
- `standard_change`：普通功能或 UI 行为改动；默认 plan-only、project context、standard verification。
- `guarded_change`：发布、部署、权限、数据库、支付、安全等风险关键词；默认 reviewed plan、deep context、full QA 和人工确认。

该策略层只决定“走哪条路”，不决定 Codex 在 run 内具体使用哪个 Superpowers skill。Orchestrator 启动 run 时已把策略写入 `execution-policy.json`、`run-manifest.json` 和 `context-index.json`，作为后续重复 run 去重、QA 降级和 merge-test gate 的依据；当前批次不直接绕过既有状态机门禁。

### 7.5 新需求流程

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
  -> 飞书回写 summary、验证摘要、风险和可选 QA 提示
  -> 可选：/coding qa <task_id>
  -> /coding merge-test <task_id>
  -> 人工发布测试环境
```

> 截图占位：`screenshots/11-feishu-coding-task.png`
>
> 截图内容建议：飞书中发送 `/coding task ...` 后，Hermes 回复“已创建编码任务”，包含 task_id、需求小结、当前状态、项目、下一步。

> 截图占位：`screenshots/12-plan-only-result.png`
>
> 截图内容建议：飞书中 plan-only 完成后的回写内容，能看到计划摘要、风险、下一步，以及明确要求人工确认 plan 后再 `/coding implement <task_id>`。

### 7.6 Bugfix 流程

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

### 7.7 Merge-to-test 流程

```text
人工测试通过
  -> /coding prepare-merge-test <task_id>
  -> /coding merge-test <task_id>
  -> Hermes 续接上一次 Codex session
  -> Codex 使用 merge-to-test skill
  -> push source branch
  -> merge 到 test 并 push origin/test
  -> Task Ledger 标记 merged_test
  -> 人工确认后 /coding complete 标记 done
  -> 发布测试环境仍人工
```

> 截图占位：`screenshots/14-merge-test-flow.png`
>
> 截图内容建议：飞书中执行 `/coding prepare-merge-test <task_id>` 和 `/coding merge-test <task_id>` 的回写，重点展示 Hermes 续接 Codex session、merge 到 test、发布仍人工。

### 7.8 Cancel / Delete 流程

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
- 是否已经 ready_for_merge_test / merged_test / done。

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
  -> 写入 run 级 wiki-context.md
  -> Prompt Builder 生成 input-prompt.md
```

读取原则：

- 按项目过滤，避免跨项目污染。
- 优先读取 `project_profile`、verified knowledge、相关 run summary。
- 当前 task 自己产生的 draft 不会作为外部知识反向注入。
- bugfix 任务会额外读取原 task 的 run summary。
- `source_refs` 保留来源链路，方便审计。

旧版 `index.jsonl` 只保留读取兼容，不再作为新写入格式。

### 9.4 项目 Bootstrap 合同消费

LLM Wiki 初始化不负责直接治理业务仓库。稳定项目事实应先由 `project-bootstrap-contract` 或等价人工维护层整理到业务仓库：

```text
AGENTS.md
docs/project-map.md
docs/conventions.md
docs/component-contract.md
contracts/project-context.yaml
```

Hermes 的 `/coding project init <path>` 默认只读扫描这些产物并写入 LLM Wiki，不创建、不覆盖业务仓库文件。需要生成或刷新这些业务仓库合同文件时，应走显式 bootstrap/refresh 入口。这样可以避免把 LLM Wiki 初始化和业务仓库文档生成混成一个不可审计动作。

`/coding project status` 会基于 LLM Wiki `project_profile` 和只读项目路径评估初始化质量：

- 项目指导：`AGENTS.md`、`CLAUDE.md` 等 agent 指导文件。
- 项目上下文：`docs/project-map.md`、`docs/conventions.md`、架构/约定类文档或已识别技术栈。
- 组件/模块合同：`docs/component-contract.md` 或 `contracts/project-context.yaml`。
- 验证命令：`project_profile.test_commands`。
- 动态来源索引：OpenAPI、Figma、Feishu/Lark 等 read-before-use 来源数量。

质量门只暴露缺口，不自动补写业务仓库；补写应由 `project-bootstrap-contract` 或显式人工维护流程完成。

动态外部来源仍维持 `read_before_use`：

- OpenAPI / Swagger / Apifox。
- Figma 设计稿。
- Feishu / Lark 文档或 Project 来源。

这些来源只进入 `external_source_index`，不作为长期 verified 知识。

> 截图占位：`screenshots/18-llm-wiki-search-read.png`
>
> 截图内容建议：展示某次 run 的 `input-prompt.md` 只引用 `wiki-context.md` / `context-index.json`，或展示日志中 search/read 命中的 project_profile/run_summary，证明不是整库注入，而是按需读取。

### 9.5 自动更新规则

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
run-instructions.md
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
> 截图内容建议：展示某个 run 目录，例如 `~/.hermes/coding-orchestration/runs/<task_id>/<run_id>/`，能看到 `input-prompt.md`、`run-instructions.md`、`run-manifest.json`、`stdout.log`、`stderr.log`、`report.json`、`summary.md`、`diff.patch`。

artifact 作用：

- `input-prompt.md`：给 Codex visible session 的最小 prompt，只包含本轮动作和必要上下文引用。
- `run-instructions.md`：详细执行契约、状态返回规则和结构化报告要求；避免把插件规范塞进 visible session。
- `run-manifest.json`：run_id、task_id、mode、runner、project_path、workspace_path、timeout、allowed paths。
- `report.schema.json`：要求 runner 输出结构化结果。
- `stdout.log` / `stderr.log` / `events.jsonl`：完整过程日志。
- `report.json`：结构化执行结果。
- `summary.md`：给人看的飞书回写内容。
- `diff.patch`：diff guard 和审计依据。

Codex 模式：

- `plan-only`：只读项目，不开发，只输出计划。
- `implementation`：在隔离 workspace / source branch 中开发，并在缺依赖时自动安装后继续验证。
- `qa`：仅由 `/coding qa <task_id>` 人工触发，续接同一个 task Codex session，使用 `$qa` skill 做 diff-aware QA、修复、复验和 artifact 回收。
- `merge-test`：续接 Codex session 执行 `merge-to-test` skill。

权限模型：

- 普通 `plan-only` 使用 `plan_read_only` 权限 profile，Codex CLI 以只读沙箱运行，只做规划不改项目文件。
- 带外部来源的 `plan-only` 使用 `plan_source_read_elevated` 权限 profile，Codex CLI 以 `--dangerously-bypass-approvals-and-sandbox` 启动，使 Codex 在自己的 session 中执行 `rtk lark-cli` 读取飞书 Project/Wiki/Docx、Swagger/OpenAPI 和 API 元数据；如果读取失败，runner 必须结构化说明授权/scope/网络问题和恢复方案。
- `implementation` 和 `qa` 使用 `--dangerously-bypass-approvals-and-sandbox`，因为依赖安装、私有源访问、dev server、浏览器 QA、`.git/worktrees` 元数据写入和 `.gstack` QA 产物都可能超出 `workspace-write`。
- 高权限不是无限制开发：Codex 子进程 cwd 固定为 task worktree；源码修改只允许落在当前 workspace；项目外写入只允许依赖缓存、git metadata、dev server/browser 临时文件和 QA artifact。
- `run-manifest.json` 对高权限 run 记录 `dangerous_bypass`、权限原因、允许的项目外写入类型和源码修改边界；Hermes diff guard 继续审计 workspace 内 diff。

implementation 的 prompt 保持极简：

- 目标、来源、上下文 artifact 引用。
- `confirmed-plan.md` 引用，而不是内联完整计划。
- `run-instructions.md` 引用，而不是内联插件规范、状态机和 JSON 字段细节。
- 本轮动作：按已确认计划实现，缺依赖时先安装并继续验证，不发布、不部署、不 merge。

> 截图占位：`screenshots/21-codex-implementation-summary.png`
>
> 截图内容建议：飞书中 implementation 完成后的回写，能看到实现摘要、验证摘要、风险、artifact 路径，以及“QA/merge-test 都需人工触发”的提示。

## 11. Runner 可扩展设计

当前默认 runner 是 `codex_cli`，但架构上不把 Codex 写死。需要对齐 Hermes 内置 `autonomous-ai-agents/codex` 使用方式时，可以把 `default_runner` 切到 `hermes_autonomous_codex`。该后端目前仍复用 direct Codex CLI 子进程执行，但已经把 skill 路径、后端策略和 session 元数据写入 run artifact，后续可在不改状态机的前提下替换为 Hermes terminal/process 执行。

统一抽象是：

```text
CodingAgentRunner.run(manifest, prompt, workspace) -> RunnerResult
```

Runner 共同约束：

- 接收 Hermes 生成的 prompt 和 manifest。
- 输出 stdout/stderr/events。
- 输出结构化 report。
- `report.status` 只允许 `running`、`succeeded`、`blocked`、`failed`、`cancelled` 五个主状态。
- 旧 runner 语义不再作为主状态存储：`queued` 写入 `raw_status/status_detail`，`ready_for_merge_test_with_known_gaps` 写入 `status_detail` 且 `known_gaps=true`，`completed_unstructured` 写入 `status_detail` 且 `structured=false`，`runner_failed/timeout/orphaned` 写入 `failure_type/raw_status` 且主状态为 `failed`。
- 不直接写 Task Ledger。
- 不直接操作飞书。
- 不决定项目。
- 不自动发布。

后续可以扩展：

- Hermes autonomous Codex Runner
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
- 默认普通自然语言不进入 plugin；Coding Mode 中自然语言通过 LLM rewrite 转成 `/coding <action>` 候选。
- 飞书需求创建 task。
- 自然语言 rewrite 高置信度直接执行，低置信度交给 Hermes 主 agent 基于插件上下文继续判断。
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

### 14.1 Hermes plugin 本地软链接安装治理

1.0 必须把本地软链接安装做成稳定、可诊断、可恢复的标准链路：

- `plugin.yaml` 补齐版本、兼容 Hermes 版本、入口、命令和 hook 描述。
- README 和 `PLUGIN_USAGE.md` 只推荐本地软链接安装命令：

```bash
rtk python3 scripts/install_symlink.py --hermes-home ~/.hermes
```

- 提供安装后自检清单：
  - `~/.hermes/plugins/coding_orchestration` 是指向当前仓库 `coding_orchestration/` 的软链接。
  - `~/.hermes/plugins/` 下不存在会被 Hermes discovery 加载的重复安装副本。
  - `rtk hermes plugins list` 能看到 `coding_orchestration` 已启用。
  - `/commands` 能看到 `/coding` 命令组。
  - `/coding help` 能输出插件命令说明。
  - `/coding task ...` 能创建 task 并进入 plan-only。

插件更新通过当前仓库拉取代码并重启 Gateway 生效；已经启动的 Codex run 不受中途代码更新影响。

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
- 支持从飞书评论继续补充 task 上下文：显式 `/coding` 直接处理，Coding Mode 中先走 LLM rewrite。
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
- 不让普通自然语言绕过 rewrite 直接进入执行链路。

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
