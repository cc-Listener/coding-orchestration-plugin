# Hermes Coding Orchestration 使用前置准备清单

这份清单用于团队成员使用 `coding_orchestration` plugin 前的统一检查，避免出现 Hermes 加载旧插件、Codex 路径不一致、`lark-cli` appId 不一致、飞书权限没有生效、项目没有初始化到 LLM Wiki 等问题。

## 0. 当前硬规范

- Hermes 必须加载本地软链接：`~/.hermes/plugins/coding_orchestration -> 当前仓库/coding_orchestration`。
- 运行根固定为：`~/.hermes/coding-orchestration`。
- 不使用 Git 安装副本，不使用 prod/test 双运行根，不使用运行根环境变量切换。
- 插件更新后必须重启 Hermes Gateway。
- 所有 shell 命令必须使用 `rtk` 前缀。

## 1. Hermes 配置

检查 Hermes CLI、Gateway 和插件工具面：

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

建议打开 health endpoint：

```text
API_SERVER_ENABLED=true
API_SERVER_HOST=127.0.0.1
API_SERVER_PORT=8642
```

验收：

```bash
rtk hermes coding doctor
rtk hermes coding project-mcp-preflight
rtk proxy curl -sS http://127.0.0.1:8642/health
```

飞书项目 MCP 是插件内私有能力，不是 `install_symlink.py` 的安装硬门禁。需要自动 intake Story、编辑 WBS、流转 Issue 状态或创建 bugfix task 时，只配置插件运行根下的 `mcp.json`，不修改 Hermes 全局 `.env`：

```json
{
  "mcpServers": {
    "feishu-project": {
      "enabled": true,
      "command": "npx",
      "args": ["-y", "@lark-project/mcp"],
      "domain": "https://project.feishu.cn",
      "env": {
        "MCP_USER_TOKEN": "<MCP_USER_TOKEN_VALUE>"
      }
    }
  }
}
```

文件路径固定为 `~/.hermes/coding-orchestration/mcp.json`。该文件属于本机运行配置，建议权限设为 0600；不要把真实 token 写入仓库、文档、LLM Wiki、prompt、测试 fixture 或 run artifacts。stdio 模式需要 Node.js 18+ 和 `npx` 可用：

```bash
rtk node --version
rtk npx --version
rtk chmod 600 ~/.hermes/coding-orchestration/mcp.json
rtk hermes gateway restart
rtk hermes coding project-mcp-preflight
```

## 2. 插件安装与更新

安装只使用本地软链接：

```bash
rtk python3 scripts/install_symlink.py --hermes-home ~/.hermes
```

`install_symlink.py` 默认会执行完整硬门禁检查，全部通过后才创建软链接、启用 `coding_orchestration` 插件并自动重启 Hermes Gateway。检查项包括：

- `~/.hermes/.env` 中存在 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`CODEX_CLI_COMMAND`。
- `CODEX_CLI_COMMAND` 是可执行的绝对路径。
- Codex CLI 支持 `codex exec`、`codex exec resume`、`--json`、`--output-schema`、`--output-last-message`、`--sandbox`、`--dangerously-bypass-approvals-and-sandbox`、`-C`。
- Hermes CLI、plugin list 和 Gateway status 可用。
- 不存在旧 plugin 副本或旧 `coding-orchestration-prod/test` 运行根。
- 终端默认 `lark-cli` appId 等于 Hermes `FEISHU_APP_ID`。
- user scope 包含 `docx:document:readonly`、Wiki 读取 scope；如果需求文档内嵌 Sheet，还需要 `sheets:spreadsheet:readonly` 或 `sheets:spreadsheet.meta:read`（兼容旧 `sheets:spreadsheet:read`）。

如果只想在隔离测试里跳过检查，可以使用 `--skip-preflight`；团队安装流程不要使用这个参数。

如果自动启用或重启失败，按脚本提示手动恢复：

```bash
rtk hermes plugins enable coding_orchestration
rtk hermes gateway restart
```

确认插件入口只有一个：

```bash
rtk ls -la ~/.hermes/plugins
```

预期：

```text
coding_orchestration -> /Users/xiaojing/Desktop/tools/hermes-codex-tools/coding_orchestration
```

如果存在历史副本或另一个 `coding_orchestration` 目录，需要移除或停用，避免两个 Gateway hook 同时回复同一条消息。

卸载 Hermes coding 相关组件时，先 dry-run：

```bash
rtk python3 scripts/uninstall_legacy.py --hermes-home ~/.hermes
```

确认输出后再真正删除：

```bash
rtk python3 scripts/uninstall_legacy.py --hermes-home ~/.hermes --execute
```

脚本默认会卸载旧插件副本、旧运行根、当前 `coding_orchestration` 软链接，以及当前 `~/.hermes/coding-orchestration` 里的 task ledger、runs、workspaces 和 LLM Wiki。执行删除前必须输入 `确认卸载` 做二次确认；未输入确认文本时不会删除任何文件。

脚本不会删除 `~/.hermes/.env`、Hermes auth、Codex auth 或 `lark-cli` 授权文件。卸载完成后会自动执行 `rtk hermes gateway restart`；如果重启失败，脚本会提示手动恢复动作。

更新插件：

```bash
rtk git pull --ff-only
rtk hermes gateway restart
```

## 3. Codex CLI 路径

插件默认 runner 是 `codex_cli`。Gateway 可能由后台服务启动，不要只依赖交互终端的 `PATH`。

检查 Codex：

```bash
rtk which codex
rtk codex --version
rtk codex exec --help
```

把绝对路径写入 `~/.hermes/.env`：

```text
CODEX_CLI_COMMAND=<rtk which codex 的输出>
```

Codex CLI 至少需要支持 `codex exec`、`codex exec resume`、`--json`、`--output-last-message` 和 `-C`。

## 4. lark-cli 与飞书权限

硬性要求：终端默认 `lark-cli` appId 必须等于 Hermes `FEISHU_APP_ID`。OAuth user token 按 appId 隔离；如果两边不是同一个飞书应用，就会出现“终端能读，Hermes/Codex task 读不到”的权限漂移。

检查当前 app：

```bash
rtk lark-cli config show
```

如果 `appId` 不等于 `~/.hermes/.env` 里的 `FEISHU_APP_ID`，绑定到 Hermes app：

```bash
rtk lark-cli config bind --source hermes --identity user-default
```

无法 bind 时，再显式初始化：

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
sheets:spreadsheet:readonly
# 或
sheets:spreadsheet.meta:read
```

建议一次性授权：

```bash
rtk lark-cli auth login --scope "docx:document:readonly wiki:node:read wiki:node:retrieve sheets:spreadsheet:readonly" --no-wait --json
```

注意：

- `--as bot` 成功，只说明飞书后台 app/bot 权限已生效。
- `--as user` 失败，通常说明当前 user token 缺 scope，或目标文档没有给当前用户权限。
- bot 权限和 user OAuth scope 必须分开判断。

## 5. 飞书开放平台应用

飞书开放平台应用需要和 `FEISHU_APP_ID` 是同一个 app。至少确认：

- App ID 等于 `rtk lark-cli config show` 输出的 `appId`。
- App Secret 写入 `~/.hermes/.env` 的 `FEISHU_APP_SECRET`。
- 权限变更已发布或已生效。
- 文档读取权限包含 Docx/Wiki。
- 如果需求使用嵌入 Sheet，应用权限包含 `sheets:spreadsheet:readonly` 或 `sheets:spreadsheet.meta:read`；旧 `sheets:spreadsheet:read` 仍作为兼容项识别。
- 目标 Wiki/Docx/Sheet 对当前 bot 或当前 user 可见。

后台权限存在不等于 user OAuth token 已包含 scope。后台开通后，user 仍需要重新授权。

## 6. 项目与 LLM Wiki

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

项目初始化只沉淀项目知识并绑定 active project，不创建 task、不启动 Codex。后续自然语言新需求如果没有显式项目，会优先使用 active project；active task 优先级高于 active project。

LLM Wiki 默认路径：

```text
~/.hermes/coding-orchestration/llm-wiki
```

原则：

- 稳定项目知识写 verified profile。
- API、Swagger、Figma、飞书、Sheet 等动态来源只写 source index，使用前重新读取。
- `.env*`、token、密钥不写入 Wiki。

## 7. Kanban 与 Dashboard

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

## 8. 最小验收流程

完成配置后，按顺序验收：

```bash
rtk hermes coding doctor
rtk hermes plugins list
rtk proxy curl -sS http://127.0.0.1:8642/health
rtk lark-cli auth status --verify
rtk codex --version
```

飞书或 Hermes Gateway 对话验收：

```text
/coding help
/coding project list
进入coding
现在有多少个 task
退出coding
```

创建只读 plan 任务：

```text
/coding task 项目 <project_name>：只读取项目结构并输出计划，不修改文件。 --project <project_name>
```

预期：

- task 创建成功。
- plan-only 生成 run artifact。
- 有飞书来源时，`source_context` 包含 URL、token、`lark_cli_command`。
- plan-only 不修改项目文件。
- 外部来源读取失败时，report 必须写 `reason`、`impact`、`recovery_action`、`fallback_evidence`。

## 9. 常见问题定位

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

Sheet 同理测试 `sheets +read --as bot` 和 `--as user`。

### task 卡在 queued

如果使用 Hermes terminal background runtime，`queued` 可能只是后台 Codex 进程已启动的占位状态。检查：

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
