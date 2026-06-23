# Hermes Codex Tools 项目导航

本仓库的对话和输出默认使用简体中文。所有 shell 命令必须使用 `rtk` 前缀，例如 `rtk git status`、`rtk proxy python3 -m unittest discover -s tests -v`。

## 读取顺序

1. 先读本文件，确认最小路由和 hard stops。
2. 再读 [docs/project-map.md](docs/project-map.md)、[docs/conventions.md](docs/conventions.md)、[docs/component-contract.md](docs/component-contract.md)。
3. 需要 machine-readable 项目事实时读 [contracts/project-context.yaml](contracts/project-context.yaml)。
4. 需要产品/运行背景时再读 [README.md](README.md)、[PLUGIN_USAGE.md](PLUGIN_USAGE.md)、[PLUGIN_PREREQUISITES.md](PLUGIN_PREREQUISITES.md)。

## 最小路由

- 插件入口：`coding_orchestration/__init__.py`
- Hermes 编排主线：`coding_orchestration/orchestrator/facade.py`、`coding_orchestration/orchestrator/__init__.py`
- 状态与数据模型：`coding_orchestration/models/contracts.py`、`coding_orchestration/state_machine/machine.py`、`coding_orchestration/ledger/facade.py`
- Runner 入口：`coding_orchestration/runners/router.py`、`coding_orchestration/runners/`
- 安装与卸载：`scripts/install_symlink.py`、`scripts/uninstall_legacy.py`、`coding_orchestration/integrations/install/install.py`
- 测试入口：`tests/`

## Hard Stops

- 不要绕过 `rtk` 直接执行 shell 命令。
- 不要把 `AGENTS.md` 扩写成完整治理文档；项目事实以 `docs/` 和 `contracts/` 为准。
- 不要生成或重写 `.codex/agents/topology.yaml`、`.codex/agents/roles/*.md`、`.codex/agents/bridges/*.md`。
- 不要把 Hermes auth、Codex auth、飞书 token、`.env*` 或本地运行根内容写入文档、测试 fixture 或 LLM Wiki。
- 不要把 plan-only 路径改成可写实现路径；plan-only 的只读语义由 orchestrator、runner flags 和 diff guard 共同约束。
