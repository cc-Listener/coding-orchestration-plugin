---
name: hermes-coding-health-check
description: Use when explaining Hermes coding health check, doctor, preflight, Lark scope, Codex, Gateway, or Feishu Project MCP readiness results to users.
---

# Hermes Coding Health Check

用于把 `/coding doctor`、`rtk hermes coding doctor`、preflight 或 health check 结果整理成用户能直接修复的说明。English anchors: health check, doctor output, readiness, repair command.

Required core skill: `../coding-health-core/SKILL.md`

本 skill 是 Hermes host binding。使用时先遵守 core skill 的 readiness 输出格式和修复口径，再将 core health check 输出映射到 Hermes `/coding doctor`、`rtk hermes coding doctor`、preflight、`lark-cli` 和插件本地配置。host binding 只处理 Hermes 命令、配置路径和当前插件集成细节。

## Host 映射边界

- 先读取并遵守 `../coding-health-core/SKILL.md`；本文件不重新定义 readiness 输出格式、状态翻译或健康检查准入规则。
- 只把 core health check 输出映射到 Hermes 命令、可直接运行的恢复命令、插件本地配置引用和验证入口。
- token 只展示占位符或配置键名，不展示真实值。
- 不创建任务，不启动执行；这里只解释 Hermes 集成恢复动作。

## 恢复命令映射

| 场景 | Hermes 恢复或验证入口 |
| --- | --- |
| 总体诊断 | `/coding doctor` 或 `rtk hermes coding doctor` |
| 飞书文档读取预检 | `rtk hermes coding lark-preflight` |
| 飞书登录状态验证 | `rtk lark-cli auth status --verify` |
| 飞书文档授权恢复 | `rtk lark-cli auth login --scope "<required-scopes>"` |
| 插件安装后复验 | `rtk python3 scripts/install_symlink.py --hermes-home ~/.hermes` |
| 飞书项目 MCP 预检 | `rtk hermes coding project-mcp-preflight` |

## 配置引用映射

| 场景 | 用户可见引用 |
| --- | --- |
| 飞书项目 MCP 本地配置 | `~/.hermes/coding-orchestration/mcp.json` |
| MCP user token 占位符 | `<MCP_USER_TOKEN_VALUE>` |
| MCP user token 配置键 | `mcpServers.feishu-project.env.MCP_USER_TOKEN` |
