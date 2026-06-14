# Hermes Coding Orchestration 部署指南

本文用于在 Hermes 本机部署和验收 `coding_orchestration` 插件。完整前置准备清单见 [PLUGIN_PREREQUISITES.md](../PLUGIN_PREREQUISITES.md)；本文只保留部署执行、验收和排障口径。

GitHub 仓库：[cc-Listener/coding-orchestration-plugin](https://github.com/cc-Listener/coding-orchestration-plugin)

## 0. 当前硬规范

| 项目 | 当前口径 |
|-|-|
| 插件入口 | `~/.hermes/plugins/coding_orchestration -> 当前仓库/coding_orchestration` |
| 运行根 | `~/.hermes/coding-orchestration` |
| 安装方式 | 只使用本地软链接，不使用 Git 安装副本 |
| 环境切换 | 不使用多运行根，不使用运行根环境变量切换 |
| 代码更新 | 拉取当前仓库后必须重启 Hermes Gateway |
| Shell 命令 | 全部使用 `rtk` 前缀 |

旧的 Git clone 安装副本、双运行根和运行根环境变量切换都不是当前部署方案。若本机残留这些入口，必须清理或停用，避免同一条飞书消息触发两次。

## 1. 部署前门禁

### 1.1 Hermes 和插件系统

```bash
rtk which hermes
rtk hermes --version
rtk hermes plugins list
rtk hermes gateway status
rtk hermes tools list
```

符合标准：

- Hermes CLI 可执行。
- Gateway 已加载。
- `rtk hermes tools list` 可查看 Hermes native tools。
- `~/.hermes/plugins` 对当前用户可写。

### 1.2 Hermes `.env`

`~/.hermes/.env` 至少包含：

```text
CODEX_CLI_COMMAND=/absolute/path/to/codex
FEISHU_APP_ID=<Hermes Gateway 飞书应用 App ID>
FEISHU_APP_SECRET=<Hermes Gateway 飞书应用 App Secret>
```

建议同时打开 health endpoint：

```text
API_SERVER_ENABLED=true
API_SERVER_HOST=127.0.0.1
API_SERVER_PORT=8642
```

不要在 `.env` 中配置旧的 Feishu Project token 或 Doc reader 环境变量。飞书来源读取统一由当前 `lark-cli` 和 Hermes 飞书应用身份负责。

### 1.3 Codex CLI

```bash
rtk which codex
rtk codex --version
rtk codex exec --help
```

把 `rtk which codex` 输出的绝对路径写入：

```text
CODEX_CLI_COMMAND=<absolute codex path>
```

Codex CLI 至少需要支持：

- `codex exec`
- `codex exec resume`
- `--json`
- `--output-last-message`
- `-C`

Gateway 可能由后台服务启动，不要只依赖交互终端的 `PATH`。

### 1.4 lark-cli 与飞书应用

硬门禁：终端默认 `lark-cli` 的 appId 必须等于 Hermes `.env` 中的 `FEISHU_APP_ID`。OAuth user token 按 appId 隔离；两边不是同一个 app 时，会出现“终端能读，Hermes/Codex task 读不到”的权限漂移。

检查当前 app：

```bash
rtk lark-cli config show
```

如果 `appId` 不等于 Hermes `FEISHU_APP_ID`，先绑定到 Hermes app：

```bash
rtk lark-cli config bind --source hermes --identity user-default
```

无法 bind 时，再显式初始化：

```bash
rtk lark-cli config init --app-id <FEISHU_APP_ID> --app-secret-stdin --brand feishu
```

验证 user 授权：

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

若需求文档内嵌飞书 Sheet，还需要：

```text
sheets:spreadsheet:read
```

建议一次性授权：

```bash
rtk lark-cli auth login --scope "docx:document:readonly wiki:node:read wiki:node:retrieve sheets:spreadsheet:read" --no-wait --json
```

注意：`--as bot` 成功只说明飞书后台 app/bot 权限已生效；`--as user` 失败通常说明当前用户 token 缺 scope，或目标文档没有给当前用户权限。bot 权限和 user OAuth scope 必须分开判断。

## 2. 安装插件

如果本机之前安装过 `coding_orchestration`，推荐先运行卸载脚本。卸载脚本默认只预览，不会删除文件：

```bash
rtk python3 scripts/uninstall_legacy.py --hermes-home ~/.hermes
```

确认预览结果无误后，再执行卸载：

```bash
rtk python3 scripts/uninstall_legacy.py --hermes-home ~/.hermes --execute
```

执行模式会删除历史 Hermes 插件入口、旧运行根，以及当前正式组件；如果检测到当前正式组件，脚本会要求输入 `确认卸载` 才继续。卸载完成后脚本会重启 Hermes Gateway。

然后在当前仓库根目录执行安装：

```bash
rtk python3 scripts/install_symlink.py --hermes-home ~/.hermes
rtk hermes plugins enable coding_orchestration
rtk hermes gateway restart
```

`scripts/install_symlink.py` 会执行完整前置检查：Hermes `.env`、Codex CLI 绝对路径和能力、Hermes CLI/Gateway、旧组件冲突、终端默认 `lark-cli` appId、Docx/Wiki/Sheet user scope 都必须通过。检查失败时会逐项输出错误和恢复动作。`--skip-preflight` 只允许用于隔离测试，不作为团队安装流程。

确认插件入口只有一个：

```bash
rtk ls -la ~/.hermes/plugins
```

预期只保留：

```text
coding_orchestration -> /Users/xiaojing/Desktop/tools/hermes-codex-tools/coding_orchestration
```

如果存在历史 Git 安装副本、另一个 `coding_orchestration` 目录或无效插件入口，先停用或移除，再重启 Gateway。

```bash
rtk hermes plugins disable <legacy_plugin_name>
rtk hermes gateway restart
```

## 3. 更新插件

本地软链接插件直接读取当前 checkout。更新代码只需要更新仓库并重启 Gateway：

```bash
rtk git pull --ff-only
rtk hermes gateway restart
```

验证：

```bash
rtk hermes plugins list
rtk proxy curl -sS http://127.0.0.1:8642/health
```

关键点：

- Hermes Gateway 不会自动热加载 Python 插件代码。
- 已经启动中的 Codex run 不会被中途换代码影响。
- 更新只影响后续新的 Gateway 消息、命令和新 run。

## 4. 当前运行面

插件当前已经接入 Hermes 原生运行面：

| 能力 | 用途 |
|-|-|
| `pre_gateway_dispatch` | 拦截 `/coding` 命令、进入/退出 Coding Mode，并触发自然语言 rewrite |
| `pre_llm_call` | 给 Hermes 主 agent 注入 active task、source health 和 next actions |
| `coding_task_create` | 结构化创建 coding task，并做项目/source preflight |
| `coding_task_status` | 读取 task 状态、source health、runner 状态和下一步 |
| `coding_task_run` | 通过 Hermes runtime 启动或续接 plan / implementation / merge-test |
| `coding_source_resolve` | 解析飞书 Wiki/Docx、Meegle/飞书 Project 等来源链接 |
| `coding_lark_preflight` | 检查 `lark-cli` appId、授权和文档读取 readiness |
| `coding_project_mcp_preflight` | 检查插件私有飞书项目 MCP 配置、transport 和 token 引用 |
| `coding_project_workitem_search` | 通过飞书项目 MCP 只读查询 Story / Issue / WBS 信息 |
| `coding_project_intake_sync` | 将飞书项目需求幂等同步为 Hermes root task |
| `coding_project_wbs_update` | 通过 WBS draft 更新拆解任务和工时承载 |
| `coding_project_state_transition` | 先检查必填项和可流转状态，再执行工作项状态流转 |
| `coding_project_bugfix_intake` | 将飞书项目 Issue / Bug 同步为 Hermes bugfix task |

飞书项目 Story / Issue / WBS / 状态流转读写通过插件内私有 `FeishuProjectMcpAdapter` 完成。Hermes 管理 MCP transport、`FEISHU_PROJECT_MCP_TOKEN_REF`、工具白名单、写操作确认、审计和脱敏；Codex / Claude / Gemini runner 不直接配置飞书项目 MCP，不持有 `MCP_USER_TOKEN`，也不直接写飞书项目。

飞书 Wiki/Docx 来源和普通 Lark 权限诊断仍走插件内 `SourceResolver`、`MeegleReader` 和文档 reader；`blocked` 只表示 hard human-blocked。飞书项目工作项与 Hermes task 的对应关系写入 `project_workitem_bindings`：Story 绑定 root task，WBS 行绑定 child task，Issue / Bug 绑定 bugfix task。已关联需求的 bugfix 默认继承需求 root task 的 `source_branch`，使用 `branch_policy=inherit_root_branch`，merge-test / PR 由需求 root task 统一推进。

飞书项目 MCP 是可选能力，不是 `install_symlink.py` 的安装硬门禁。需要启用自动 intake、WBS 更新、状态流转或 bugfix intake 时，先配置 token 引用并运行：

```bash
rtk node --version
rtk npx --version
rtk hermes coding project-mcp-preflight
```

## 5. 飞书来源读取口径

创建 task 时，Hermes 只负责识别项目并索引外部来源，不把飞书读取作为创建 gate。

当输入包含 `project.feishu.cn/<project_key>/<type>/detail/<id>`、`/wiki/<token>` 或 `/docx/<token>` 链接时：

- Task Ledger 记录 URL、token、Project key、工作项类型、`lark_cli_command` 和恢复动作。
- 普通 plan-only 使用 `plan_read_only`，只做计划，不修改项目文件。
- 带外部来源的 plan-only 使用 `plan_source_read_elevated`，让 Codex 在自己的 session 中执行 `rtk lark-cli` 读取飞书、Swagger/OpenAPI 和 API 元数据。
- 如果 Codex 也读不到，必须在结构化 report 中写清授权、scope、网络或工具问题，并给出恢复动作。

plan-only 即使为了读取外部来源提权，也不能修改项目文件。Hermes diff guard 会拦截任何 plan 阶段写入。

## 6. 项目与 LLM Wiki

推荐先把业务项目初始化到 LLM Wiki：

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

项目初始化只沉淀项目知识并绑定 active project，不创建 task、不启动 Codex。后续自然语言新需求如果没有显式项目，会优先使用 active project；active task 优先级高于 active project，两者冲突时必须追问。

LLM Wiki 默认路径：

```text
~/.hermes/coding-orchestration/llm-wiki
```

知识写入原则：

- 稳定项目知识写 verified profile。
- API、Swagger、Figma、飞书、Sheet 等动态来源只写 source index，使用前重新读取。
- `.env*`、token、密钥不写入 Wiki。
- 初始化时不需要带入 `project-registry.json`；它只作为可选 bootstrap/fallback。

## 7. Kanban 与 Dashboard

Kanban 是协作视图，不是 Task Ledger 的替代品。

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

## 8. 最小验收

### 8.1 本机命令验收

```bash
rtk hermes coding doctor
rtk hermes plugins list
rtk hermes gateway status
rtk proxy curl -sS http://127.0.0.1:8642/health
rtk lark-cli auth status --verify
rtk codex --version
```

预期：

- `coding_orchestration` 处于 enabled。
- health endpoint 返回 ok。
- `lark-cli` user identity 可用，且 appId 与 Hermes `FEISHU_APP_ID` 一致。
- `rtk hermes coding doctor` 不报告重复插件入口、Codex 路径缺失或 lark app mismatch。

### 8.2 飞书或 Hermes Gateway 对话验收

```text
/coding help
/coding project list
进入coding
现在有多少个 task
退出coding
```

预期：

- `/coding help` 能输出完整命令说明。
- `/coding project list` 能列出 LLM Wiki 项目或提示未初始化。
- 进入 Coding Mode 后，自然语言查询不会误创建 task。
- 退出 Coding Mode 后，普通自然语言不再进入插件 rewrite。

### 8.3 只读 plan 任务验收

```text
/coding task 项目 <project_name>：只读取项目结构并输出计划，不修改文件。 --project <project_name>
```

预期：

- task 创建成功。
- plan-only 生成 run artifact。
- 有飞书来源时，`source_context` 包含 URL、token、`lark_cli_command`。
- plan-only 不修改项目文件。
- 外部来源读取失败时，report 必须写 `reason`、`impact`、`recovery_action`、`fallback_evidence`。

## 9. 快速上手

### CLI 场景

```text
/coding project init /Users/xiaojing/Desktop/project/<project-folder>
/coding project use <project_name>
/coding task <需求正文或飞书链接>
/coding status
/coding implement <task_id>
/coding prepare-merge-test <task_id>
/coding merge-test <task_id>
/coding complete <task_id>
```

### 自然语言场景

```text
进入coding
接下来用 <project_name> 这个项目
帮我基于这个飞书需求创建一个任务：<飞书 Wiki/Docx/Project 链接>
计划确认，开始实现
这个截图里的样式不对，继续修一下
准备合 test
退出coding
```

自然语言只在 Coding Mode 中进入 rewrite。低置信度、缺项、授权诊断或高风险动作会交给 Hermes 主 agent 或要求人工确认。

## 10. 常见问题

### 插件回复两次

通常是 Hermes 同时加载了两个插件入口。

```bash
rtk ls -la ~/.hermes/plugins
rtk hermes plugins list
```

只保留本地软链接 `coding_orchestration`，停用历史副本后重启 Gateway。

### Codex 找不到

```bash
rtk which codex
rtk codex exec --help
rtk hermes coding doctor
```

确保 `CODEX_CLI_COMMAND` 是绝对路径，并重启 Gateway。

### 终端能读飞书，task 读不到

先确认 appId 一致：

```bash
rtk lark-cli config show
```

再分别验证 bot 和 user：

```bash
rtk lark-cli docs +fetch --as bot --api-version v2 --doc <url> --doc-format markdown --format json
rtk lark-cli docs +fetch --as user --api-version v2 --doc <url> --doc-format markdown --format json
```

Sheet 同理分别测试 `sheets +read --as bot` 和 `sheets +read --as user`。不要把 bot 权限和 user OAuth scope 混为一谈。

### task 卡在 queued

如果使用 Hermes terminal background runtime，`queued` 可能只是后台 Codex 进程已启动的占位状态。

```bash
rtk pgrep -fal "<task_id>|<run_id>|codex exec"
```

如果进程仍在，等待完成或补 collector 同步；如果进程已结束但 ledger 仍是 queued，需要用 artifact 的 `report.json` 回填状态。

### plan 阶段改了文件

这是违规情况。保留 artifact，检查 `diff.patch` 和 `run-manifest.json`。plan-only 即使为了读取外部来源提权，也不能修改项目文件。

## 11. Agent 一键部署 Prompt

把下面整段复制给具备终端权限的 Agent：

```text
请帮我在这台机器上部署 Hermes plugin `coding_orchestration`。

约束：
- 全程使用简体中文汇报。
- 所有 shell 命令必须加 `rtk` 前缀。
- 当前只允许本地软链接安装：`~/.hermes/plugins/coding_orchestration -> 当前仓库/coding_orchestration`。
- GitHub 仓库地址是：https://github.com/cc-Listener/coding-orchestration-plugin
- 运行根固定为 `~/.hermes/coding-orchestration`。
- 不使用 Git 安装副本，不创建双运行根，不配置运行根环境变量切换。
- 不写入旧的 Feishu Project token 或 Doc reader 环境变量。
- 任一硬门禁失败时停止，不继续安装。

前置检查：
1. 执行 `rtk which hermes`、`rtk hermes gateway status`、`rtk hermes tools list`。
2. 执行 `rtk which codex`、`rtk codex --version`、`rtk codex exec --help`，记录 Codex 绝对路径。
3. 检查 `~/.hermes/.env` 至少包含 `CODEX_CLI_COMMAND`、`FEISHU_APP_ID`、`FEISHU_APP_SECRET`；如果 `CODEX_CLI_COMMAND` 缺失或不是绝对路径，更新为第 2 步的 Codex 绝对路径。
4. 执行 `rtk lark-cli config show`，确认 appId 等于 Hermes `FEISHU_APP_ID`；不一致时执行 `rtk lark-cli config bind --source hermes --identity user-default`，再复查。
5. 执行 `rtk lark-cli auth status --verify`，确认 user identity 可用并具备 Docx/Wiki 读取 scope。
6. 执行 `rtk ls -la ~/.hermes/plugins`，确认没有历史 Git 安装副本或重复 `coding_orchestration` 入口。

历史安装清理：
1. 如果本机之前安装过 `coding_orchestration`，先执行 dry-run：
   `rtk python3 scripts/uninstall_legacy.py --hermes-home ~/.hermes`
2. 如果 dry-run 显示存在历史插件入口、旧运行根或当前正式组件，向我汇报将删除的路径。
3. 我确认后，再执行：
   `rtk python3 scripts/uninstall_legacy.py --hermes-home ~/.hermes --execute`
4. 如果脚本提示输入确认文本，输入 `确认卸载`。

安装步骤：
1. 执行 `rtk python3 scripts/install_symlink.py --hermes-home ~/.hermes`。
2. 执行 `rtk hermes plugins enable coding_orchestration`。
3. 执行 `rtk hermes gateway restart`。

验收：
1. 执行 `rtk hermes coding doctor`。
2. 执行 `rtk hermes plugins list`，确认 `coding_orchestration` enabled。
3. 执行 `rtk proxy curl -sS http://127.0.0.1:8642/health`。
4. 执行 `rtk lark-cli auth status --verify`。
5. 输出最终摘要：插件入口、运行根、Codex CLI 路径、lark-cli appId、Gateway 状态、是否发现重复插件入口。
```
