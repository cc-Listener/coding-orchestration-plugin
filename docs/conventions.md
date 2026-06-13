# 项目约定

## 基本规则

- 对话、提交说明和项目说明默认使用简体中文。
- 所有 shell 命令必须带 `rtk` 前缀。需要原始输出时使用 `rtk proxy <cmd>`。
- 优先修改现有模块，不新建平行实现；插件边界已经集中在 `coding_orchestration/`。
- 不把运行根、token、auth、`.env*`、本地 LLM Wiki 内容或 Task Ledger 数据提交到仓库。

## 开发入口

- 插件注册入口是 `coding_orchestration/__init__.py`。
- `/coding` 命令、人机门禁和运行阶段推进主要在 `coding_orchestration/orchestrator.py`。
- Hermes native tools 注册在 `coding_orchestration/plugin_tools.py`，CLI 子命令注册在 `coding_orchestration/cli.py`。
- Codex CLI 命令构造、resume、sandbox、结构化 report 读取在 `coding_orchestration/runners/codex_cli.py`。
- 安装和卸载逻辑优先改 `coding_orchestration/install.py`，脚本只保留入口和用户输出。

## 验证 Gate

| 场景 | 命令 |
| --- | --- |
| 完整单测 | `rtk proxy python3 -m unittest discover -s tests -v` |
| 单个测试文件 | `rtk proxy python3 -m unittest tests.test_install -v` |
| 安装前置检查 | `rtk python3 scripts/install_symlink.py --hermes-home ~/.hermes` |
| 卸载 dry-run | `rtk python3 scripts/uninstall_legacy.py --hermes-home ~/.hermes` |
| Hermes 插件状态 | `rtk hermes plugins list` |
| Hermes Gateway 状态 | `rtk hermes gateway status` |
| Gateway health | `rtk proxy curl -sS http://127.0.0.1:8642/health` |

运行安装脚本会访问本机 Hermes、Codex CLI、`lark-cli` 和飞书权限状态；在普通代码改动中，默认先跑单测。只有变更安装链路或本机联调时才执行安装脚本。

## 测试约定

- 测试使用标准库 `unittest`，测试文件位于 `tests/test_*.py`。
- 新增状态、命令、runner、source resolver、report gate 或用户可见文案时，应补充相邻测试。
- 变更 `orchestrator.py` 时优先查找并扩展 `tests/test_orchestrator_run_flow.py`、`tests/test_orchestrator_tools.py`、`tests/test_gateway_trigger.py`。
- 变更安装链路时优先查找并扩展 `tests/test_install.py`、`tests/test_docs_and_install_entry.py`。
- 变更 report contract 或 runner 输出时优先查找并扩展 `tests/test_report_contract.py`、`tests/test_report_admission.py`、`tests/test_codex_cli_runner.py`。

## 发布与运行约束

- 本项目当前只支持本地软链接安装到 Hermes：`~/.hermes/plugins/coding_orchestration -> 当前仓库/coding_orchestration`。
- 插件更新后必须重启 Hermes Gateway；Gateway 不会热加载 Python 插件代码。
- `implementation`、`QA`、`merge-test` 可使用受控高权限 Codex CLI session，但源码修改应落在任务 workspace；项目外写入只允许依赖缓存、git metadata、dev server/browser 临时文件和 QA artifact。
- `plan-only` 无论是否需要读取外部来源，都不应修改项目文件；diff guard 应阻断 plan 阶段写入。
- `merge-test` 和发布仍是人工触发，不由普通 implementation 自动发布或部署。

## 文档约定

- `AGENTS.md` 只做导航和 hard stops。
- `docs/project-map.md`、`docs/conventions.md`、`docs/component-contract.md` 是人类可读项目事实入口。
- `contracts/project-context.yaml` 是 machine-readable 项目事实，不承载 agent topology、角色拆分或执行顺序。
- `docs/deployment.md`、`docs/plugin-prerequisites.md`、`docs/plans/`、状态机/交付流文档属于项目沉淀，可以提交。
- superpowers 生成的执行计划统一放在 `docs/plans/`，不要再分散到 `docs/superpowers/`、`docs/local/superpowers*` 或 `docs/` 根目录。
- 宣讲、demo、分享材料放在 `docs/local/presentations/`；该目录被忽略，不作为 canonical 项目事实来源。
- 历史计划、流程图和阶段性报告不要复制进 canonical 文档；只在需要背景时按链接读取。
