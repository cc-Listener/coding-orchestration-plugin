---
name: coding-health-core
description: Use when explaining coding readiness or health check results independent of a host runtime.
---

# Coding Health Core

用于把 coding orchestration 的 readiness、doctor、preflight 或 health check 结果整理成用户能直接修复的说明。

English anchors: health check, doctor output, readiness, repair command.

## 核心原则

每个系统单独分区，只输出用户需要知道的状态、原因、修复动作和验证命令。

## 输出格式

每个系统固定使用这些字段，字段缺失时不要编造：

- `<系统名>`
- `状态：✅ 可用 | ❌ 不可用 | ❌ 未启用`
- `原因：<一句话>`
- `缺少权限：`，每个 scope 单独一行
- `修复命令：`，只放可直接运行的命令
- `修复配置：`，只放配置键名、文件引用或 `<secret-ref>`，不要放 token 原文
- `验证命令：`，给出检查是否恢复的命令

## 硬规则

- 不要输出内部任务账本、运行数据库路径或定时检查建议。
- 结构化授权检查结果优先于猜测；先看应用身份，再看用户 token 状态和验证结果，最后看 scope。
- token 可自动刷新且权限已齐时，不要报缺权限；状态写 `✅ 可用`，并用 `提醒：` 说明 token 可自动刷新。
- 不要输出 raw status，要翻译为中文状态和原因。
- 可用必须写成 `✅ 可用`；不可用或未启用必须写成 `❌ 不可用` / `❌ 未启用`。
- 不要把多条信息挤在一行；状态、原因、修复命令、验证命令必须分行。
- token 只能展示为占位符或配置键名，不要展示 token 值。
- 健康检查只解释和修复运行条件，不创建任务、不启动执行。

## 示例

```text
文档读取
状态：❌ 不可用
原因：缺少必要权限
缺少权限：
- docx:document:readonly
- wiki:node:read 或 wiki:node:retrieve
修复命令：
<host-auth-login-command>
验证命令：
<host-preflight-command>
```
