# Hermes Coding Orchestration 使用前置准备清单

这份清单用于在使用 `coding_orchestration` plugin 前统一检查环境。目标是避免常见问题：Hermes 加载了旧插件副本、Codex 路径不一致、`lark-cli` appId 不一致、飞书 Wiki/Sheet 权限没有生效、项目没有初始化到 LLM Wiki。

## 0. 当前硬规范

- Hermes 必须加载本地软链接插件：`~/.hermes/plugins/coding_orchestration -> 当前仓库/coding_orchestration`。
- 运行根固定为：`~/.hermes/coding-orchestration`。
- 不使用 `coding-orchestration-prod`、`coding-orchestration-test` 或 `CODING_ORCHESTRATION_ROOT` 做运行根切换。
- 插件更新后必须重启 Hermes Gateway；Gateway 不会热加载 Python 插件代码。
- 所有 shell 命令必须使用 `rtk` 前缀。

## 1. Hermes 基础配置

确认 Hermes CLI、Gateway 和插件工具面可用：

```bash
rtk which hermes
rtk hermes --version
rtk hermes plugins list
rtk hermes gateway status
rtk hermes tools list
```

`~/.hermes/.env` 至少需要：

```text
CODEX_CLI_COMMAND=/absolute/path/to/codex
FEISHU_APP_ID=<Hermes Gateway 飞书应用 App ID>
FEISHU_APP_SECRET=<Hermes Gateway 飞书应用 App Secret>
```

建议打开 health endpoint，方便运行态验收：

```text
API_SERVER_ENABLED=true
API_SERVER_HOST=127.0.0.1
API_SERVER_PORT=8642
```

验收命令：

```bash
rtk hermes coding doctor
rtk proxy curl -sS http://127.0.0.1:8642/health
```

预期：

- `Hermes runtime: available`
- `Kanban: available` 或明确知道当前不需要 Kanban
- health 返回 `{"status":"ok","platform":"hermes-agent"}` 或等价 ok payload

## 2. 插件安装与加载

安装只使用本地软链接：

```bash
rtk python3 scripts/install_symlink.py --hermes-home ~/.hermes
rtk hermes plugins enable coding_orchestration
rtk hermes gateway restart
```

确认插件入口只有一个：

```bash
rtk ls -la ~/.hermes/plugins
```

预期只保留：

```text
coding_orchestration -> /Users/xiaojing/Desktop/tools/hermes-codex-tools/coding_orchestration
```

如果存在历史副本，例如 `coding-orchestration-plugin` 或另一个 `coding_orchestration` 目录，需要移除或停用，避免两个 `pre_gateway_dispatch` hook 同时处理同一条飞书消息。

验证插件命令：

```bash
rtk hermes plugins list
rtk hermes coding doctor
```

在飞书或 Hermes Gateway 对话里验证：

```text
/commands
/coding help
```

## 3. Codex CLI 配置

插件默认 runner 是 `codex_cli`。必须确认 Gateway 运行用户能找到同一个 Codex CLI。

```bash
rtk which codex
rtk codex --version
rtk codex exec --help
```

把绝对路径写入 `~/.hermes/.env`：

```text
CODEX_CLI_COMMAND=<rtk which codex 的输出>
```

关键点：

- 不要只依赖交互终端的 `PATH`，因为 Gateway 可能由 launchd/systemd 启动。
- Codex CLI 要支持 `codex exec`、`codex exec resume`、`--json`、`--output-last-message`、`-C`。
- 带外部来源的 plan-only、implementation、QA、merge-test 会使用受控高权限；安全边界由 task worktree、manifest 和 diff guard 收口。
- Hermes `openai-codex` provider/OAuth 使用 `~/.hermes/auth.json`；standalone Codex CLI 可使用 `~/.codex/auth.json`。两者不要互相复制。

## 4. lark-cli 配置

飞书 Wiki、Docx、Sheet 的读取都走当前 `lark-cli`。硬性要求：终端默认 `lark-cli` appId 必须等于 Hermes 的 `FEISHU_APP_ID`。

检查当前 app：

```bash
rtk lark-cli config show
```

如果 `appId` 不等于 `~/.hermes/.env` 里的 `FEISHU_APP_ID`，先绑定到 Hermes app：

```bash
rtk lark-cli config bind --source hermes --identity user-default
```

无法 bind 时，再用 Hermes app 显式初始化：

```bash
rtk lark-cli config init --app-id <FEISHU_APP_ID> --app-secret-stdin --brand feishu
```

验证授权：

```bash
rtk lark-cli auth status --verify
```

最低 user scope：

```text
docx:document:readonly
wiki:node:read
wiki:node:retrieve
offline_access
```

如果需求文档内嵌飞书 Sheet，还需要：

```text
sheets:spreadsheet:read
```

建议一次性 user 授权：

```bash
rtk lark-cli auth login --scope "docx:document:readonly wiki:node:read wiki:node:retrieve sheets:spreadsheet:read" --no-wait --json
```

bot 权限由飞书开放平台后台配置和发布控制。确认 bot 能读 Wiki/Sheet：

```bash
rtk lark-cli docs +fetch --as bot --api-version v2 --doc <wiki_or_docx_url> --doc-format markdown --format json
rtk lark-cli sheets +read --as bot --spreadsheet-token <spreadsheet_token> --sheet-id <sheet_id> --range <sheet_id>
```

如果 `--as bot` 能读、`--as user` 不能读，说明后台 app/bot 权限已生效，但当前 user OAuth scope 还没补齐。此时重新执行 user `auth login --scope ...`。

## 5. 飞书应用后台配置

飞书开放平台应用需要和 `FEISHU_APP_ID` 是同一个 app。至少确认：

- App ID 等于 `rtk lark-cli config show` 输出的 `appId`。
- App Secret 写入 `~/.hermes/.env` 的 `FEISHU_APP_SECRET`。
- 已发布或已让权限变更生效。
- 文档读取权限包含 Docx/Wiki。
- 如果需求使用嵌入 Sheet，应用权限包含 `sheets:spreadsheet:read`。
- 目标 Wiki/Docx/Sheet 对当前 bot 或当前 user 可见。

注意：后台权限存在不等于 user OAuth token 已包含 scope。后台开通后，user 仍需要重新授权；bot 则需要确认应用发布/权限生效。

## 6. 项目准备

每个业务项目建议先初始化到 LLM Wiki：

```text
/coding project init /Users/xiaojing/Desktop/project/<project-folder>
```

查看已有项目：

```text
/coding project list
```

切换当前会话项目：

```text
/coding project use <project_name>
```

项目目录建议具备：

- Git 仓库。
- 默认 base branch 为 `main`，或在项目画像/需求中显式声明 `source_base_branch`。
- Git identity 可用：

```bash
rtk git config --global user.name
rtk git config --global user.email
```

- 项目内有 `WORKFLOW.md`、`AGENTS.md` 或 `.codex/` 约束，写清 allowed paths、forbidden paths、测试命令、发布边界。
- 项目测试命令本身可运行，依赖安装路径和私有源可访问。

## 7. LLM Wiki 准备

默认路径：

```text
~/.hermes/coding-orchestration/llm-wiki
```

项目初始化后，至少应该能看到：

```text
project_profile
project_guidance_contract
project_architecture_map
project_conventions
verification_profile
tooling_profile
agent_tooling_profile
risk_profile
external_source_index
historical_plan_index
```

原则：

- 稳定项目知识写 `verified` profile。
- API、Swagger、Figma、飞书、Sheet 这类动态来源只写 source index，使用前重新读取。
- `.env*`、token、密钥不写入 Wiki。

## 8. Kanban 与 Dashboard

Kanban 是协作视图，不是 task ledger 的替代品。确认可用：

```bash
rtk hermes coding doctor
rtk hermes kanban boards list
rtk hermes kanban list --json
```

Dashboard：

```bash
rtk hermes dashboard
```

默认地址：

```text
http://127.0.0.1:9119
```

当前插件创建 task 时会尝试同步 Kanban；如果没有 `kanban_task_id`，以 Task Ledger 为准，并检查 Kanban bridge 或后续手动补同步能力。

## 9. 最小验收流程

完成上面配置后，按这个顺序验收：

```bash
rtk hermes coding doctor
rtk hermes plugins list
rtk proxy curl -sS http://127.0.0.1:8642/health
rtk lark-cli auth status --verify
rtk codex --version
```

飞书/Gateway 对话验收：

```text
/coding help
/coding project list
进入coding
现在有多少个 task
退出coding
```

创建一个只读 plan 任务：

```text
/coding task 项目 <project_name>：只读取项目结构并输出计划，不修改文件。--project <project_name>
```

预期：

- task 创建成功。
- plan-only 生成 run artifact。
- 有飞书来源时，`source_context` 包含 URL、token、`lark_cli_command`。
- plan-only 不修改项目文件。
- 如果外部来源读取失败，report 必须写 `reason`、`impact`、`recovery_action`、`fallback_evidence`。

## 10. 常见问题定位

### 插件回复两次

通常是 Hermes 同时加载了两个插件入口。检查：

```bash
rtk ls -la ~/.hermes/plugins
```

只保留本地软链接 `coding_orchestration`。

### 终端能读飞书，Codex task 读不到

先确认 appId：

```bash
rtk lark-cli config show
```

`appId` 必须等于 Hermes `FEISHU_APP_ID`。如果一致，再分别测试：

```bash
rtk lark-cli docs +fetch --as bot --api-version v2 --doc <url> --doc-format markdown --format json
rtk lark-cli docs +fetch --as user --api-version v2 --doc <url> --doc-format markdown --format json
```

Sheet 同理测试 `sheets +read --as bot` 和 `--as user`。不要把 bot 权限和 user OAuth scope 混为一谈。

### task 卡在 queued

如果使用 Hermes terminal background runtime，`queued` 可能只是“后台 Codex 进程已启动”的占位状态。检查：

```bash
rtk pgrep -fal "<task_id>|<run_id>|codex exec"
```

如果进程仍在，等待完成或补 collector 同步；如果进程已结束但 ledger 仍是 queued，需要用 artifact 的 `report.json` 回填状态。

### Codex 找不到或权限不对

检查：

```bash
rtk which codex
rtk codex exec --help
rtk hermes coding doctor
```

确保 `CODEX_CLI_COMMAND` 是绝对路径，并重启 Gateway。

### plan 阶段改了文件

这是违规情况。保留 artifact，检查 `diff.patch` 和 `run-manifest.json`。plan-only 即使为了读取外部来源提权，也不能修改项目文件。
