# Codex Superpowers Bridge

本文件是 repo-local Codex custom agents 与 superpowers 工作流的 guidance bridge。它不是官方 subagent manifest；官方配置仍以 `.codex/config.toml` 和 `.codex/agents/*.toml` 为准。

## 读取顺序

1. 先读仓库根目录 `AGENTS.md`，遵守简体中文输出、`rtk` 命令前缀和 hard stops。
2. 再读 `contracts/project-context.yaml`，确认 guarded paths、验证 gate 和组件封装边界。
3. 再按任务读取 `docs/project-map.md`、`docs/conventions.md`、`docs/component-contract.md`。
4. 涉及已有计划时，读取 `docs/plans/` 下对应实施计划。
5. 最后读取 `.codex/config.toml` 和 `.codex/agents/*.toml`，确认当前 custom agent 的角色边界。

## Superpowers 使用边界

- 有明确实施计划时，按 `executing-plans` 的纪律逐步执行，不把计划改写成新的流程。
- 遇到 bug、测试失败或行为不明时，按 `systematic-debugging` 的纪律先找根因，再修复。
- 实现新功能或 bugfix 时，优先采用 `test-driven-development` 的节奏；如果现有测试结构不支持，说明替代验证方式。
- 完成前必须按 `verification-before-completion` 的纪律核对实际验证证据，不用“应该可以”替代结果。
- 收到 review 反馈时，按 `receiving-code-review` 的纪律逐条处理或说明不采纳原因。
- 完成开发分支或准备交付时，按 `finishing-a-development-branch` 的纪律检查状态、测试和提交边界。

如果当前 Codex 会话没有某个 superpowers skill，可按同等方法论执行，并在输出中说明该 skill 不可用。

## Agent 约束

- `implementer` 可以修改分配范围内文件，但必须保持最小改动并运行相邻验证。
- `reviewer` 默认只读，只输出 findings、证据和 pass/fail gate。
- 不要自动生成 `.codex/agents/topology.yaml`、`.codex/agents/roles/*.md` 或 `.codex/agents/bridges/*.md`。
- 不要把 `docs/local/`、`images/`、`output/` 或任何凭据/运行根内容当作项目事实提交。
- 不要自动 spawn subagents；是否使用 custom agent 由主会话显式决定。
