---
name: hermes-coding-health-check
description: Use when explaining Hermes coding health check, doctor, preflight, Lark scope, Codex, Gateway, or Feishu Project MCP readiness results to users.
---

# Hermes Coding Health Check

用于把 `/coding doctor`、`rtk hermes coding doctor`、preflight 或 health check 结果整理成用户能直接修复的说明。English anchors: health check, doctor output, readiness, repair command.

Required core skill: `../coding-health-core/SKILL.md`

本 skill 是 Hermes host binding。使用时先遵守 core skill 的 readiness 输出格式和修复口径，再将 core health check 输出映射到 Hermes `/coding doctor`、`rtk hermes coding doctor`、preflight、`lark-cli` 和插件本地配置。host binding 只处理 Hermes 命令、配置路径和当前插件集成细节。

## 核心原则

每个系统单独分区，只输出用户需要知道的状态、原因、修复动作和验证命令。

## 输出格式

每个系统固定使用这些字段，字段缺失时不要编造：

- `<系统名>`
- `状态：✅ 可用 | ❌ 不可用 | ❌ 未启用`
- `原因：<一句话>`
- `缺少权限：`，每个 scope 单独一行
- `修复命令：`，只放可直接运行的 `rtk ...` 命令
- `修复配置：`，只放配置键名、文件引用或 `<secret-ref>`，不要放 token 原文
- `验证命令：`，给出检查是否恢复的命令

系统分区至少覆盖：

- 飞书文档读取
- 飞书项目 MCP
- Hermes
- Codex

## 硬规则

- 不要输出 Task Ledger、ledger.db 或定时检查建议。
- 飞书文档读取必须以 `lark-cli auth status --verify` 的结构化结果为准；先看 appId，再看 user `tokenStatus` / `verified`，最后看 scope。
- `tokenStatus=needs_refresh` 且 `verified=true`、scope 已齐时，不要报缺权限；状态写 `✅ 可用`，并用 `提醒：` 说明 token 可自动刷新。
- 不要输出 raw status，例如 `permission_missing`、`disabled`、`auth_needed`，要翻译为中文状态和原因。
- 可用必须写成 `✅ 可用`；不可用或未启用必须写成 `❌ 不可用` / `❌ 未启用`。
- 不要把多条信息挤在一行；状态、原因、修复命令、验证命令必须分行。
- 飞书项目 MCP 只展示插件本地配置文件 `~/.hermes/coding-orchestration/mcp.json`，不要要求用户修改 Hermes 全局 `.env`。
- MCP token 只能展示为 `<MCP_USER_TOKEN_VALUE>` 或配置键名 `mcpServers.feishu-project.env.MCP_USER_TOKEN`，不要展示 token 值。
- 健康检查只解释和修复运行条件，不创建任务、不启动 Codex 执行。

## 示例

```text
飞书文档读取
状态：❌ 不可用
原因：缺少必要权限
缺少权限：
- docx:document:readonly
- wiki:node:read 或 wiki:node:retrieve
修复命令：
rtk lark-cli auth login --scope "docx:document:readonly wiki:node:read wiki:node:retrieve"
rtk python3 scripts/install_symlink.py --hermes-home ~/.hermes
验证命令：
rtk hermes coding lark-preflight
```
