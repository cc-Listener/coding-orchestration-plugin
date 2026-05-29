# Hermes plugin - coding-orchestration 安装指南

本文用于部署 `coding_orchestration` 插件，并在安装前检查 Hermes 环境、Codex 前置环境和项目接入配置。插件默认注册 Hermes `pre_gateway_dispatch` hook 和 `/coding` 命令。测试部署和生产部署必须使用不同运行根目录，通过 `CODING_ORCHESTRATION_ROOT` 区分。

## 适用范围

- 插件名：`coding_orchestration`
- 当前版本：`0.1.0`
- 默认 Runner：`codex_cli`
- 测试数据目录：`~/.hermes/coding-orchestration-test`
- 生产数据目录：`~/.hermes/coding-orchestration-prod`
- 兼容默认目录：未设置 `CODING_ORCHESTRATION_ROOT` 时使用 `~/.hermes/coding-orchestration`
- 默认插件目录：`~/.hermes/plugins/coding_orchestration`
- 生产安装方式：`rtk hermes plugins install git@github.com:cc-Listener/coding-orchestration-plugin.git --enable`
- 本地调试方式：软链接当前 checkout 的 `coding_orchestration/` 到 Hermes plugins 目录

## 部署前检查

### 1. Hermes 环境

确认部署机上 Hermes CLI 可用，Gateway 能启动，并且当前用户对 Hermes home 有写权限：

```bash
rtk which hermes
rtk hermes --version
rtk hermes plugins list
rtk hermes gateway status
rtk ls ~/.hermes
```

Hermes 环境需要满足：

- 支持用户插件目录 `~/.hermes/plugins`。
- 支持插件入口 `register(ctx)`。
- 支持 `ctx.register_hook("pre_gateway_dispatch", ...)`。
- 支持 `ctx.register_command("coding", ...)`。
- Gateway 进程的 `PATH` 能找到 `codex`、`git`，如需读取飞书文档还要能找到 `lark-cli`。
- Gateway 进程能写入当前环境的 `CODING_ORCHESTRATION_ROOT`，以及其中的 `runs`、`workspaces`、`llm-wiki` 和 `ledger.db`。

如 Hermes 以 systemd、launchd、Docker 或远程服务方式运行，不要只检查当前终端的环境变量；需要确认 Gateway 进程实际继承了相同的 `PATH`、`HOME` 和飞书/Codex 相关环境变量。

### 2. SSH 仓库访问检查

生产安装统一使用 SSH Git URL。安装前必须确认部署机和 Gateway 运行用户能通过 SSH 访问插件仓库：

```bash
rtk git ls-remote git@github.com:cc-Listener/coding-orchestration-plugin.git HEAD
```

符合判定：

- 符合：命令返回一行 commit hash 和 `HEAD`，说明 SSH key、GitHub 权限和仓库地址都可用。
- 不符合：出现 `Permission denied (publickey)`、`Repository not found`、超时或无输出时，不要继续安装；先配置 GitHub SSH key、仓库权限和网络连通性。

可选地检查 SSH 身份：

```bash
rtk ssh -T git@github.com
```

如果输出包含 `successfully authenticated`，说明 SSH 身份可用；GitHub 不提供 shell access，命令返回非 0 时也要以输出内容为准。

### 3. Python 环境

插件源码使用 Python 标准库实现，建议 Hermes 插件运行时使用 Python 3.10 或更高版本：

```bash
rtk python3 --version
```

当前仓库没有额外 Python 三方依赖；部署失败时优先检查 Hermes 插件加载时使用的 Python 解释器版本和模块搜索路径。

### 4. Codex 前置环境

默认 runner 会执行 `codex exec`，并依赖 Codex CLI 支持结构化输出、resume、只读沙箱和受控高权限实现模式：

```bash
rtk which codex
rtk codex --version
rtk codex exec --help
```

Codex 环境需要满足：

- Codex CLI 已登录，并且 Gateway 运行用户可以访问同一份 Codex 凭据。
- CLI 支持 `codex exec`、`codex exec resume`、`--json`、`--output-schema`、`--output-last-message`、`--sandbox read-only`、`-C`。
- implementation、QA、merge-test 阶段需要 CLI 支持 `--dangerously-bypass-approvals-and-sandbox`；Hermes 会把 cwd 固定到 task worktree，并通过 diff guard 和 run manifest 收口风险。
- 如果 Codex 不在默认 `PATH`，在 Gateway 环境里设置 `CODEX_CLI_COMMAND=/absolute/path/to/codex`。
- 如使用 `hermes_autonomous_codex` runner，还需要设置或确认 `HERMES_AUTONOMOUS_CODEX_SKILL` 指向 Hermes autonomous Codex skill。

示例环境变量：

```text
CODEX_CLI_COMMAND=/opt/homebrew/bin/codex
HERMES_AUTONOMOUS_CODEX_COMMAND=/opt/homebrew/bin/codex
HERMES_AUTONOMOUS_CODEX_SKILL=/Users/<user>/.hermes/hermes-agent/skills/autonomous-ai-agents/codex/SKILL.md
```

### 5. Git 和目标项目环境

implementation 会在目标项目上创建 `codex/<slug>-<task_id>` source branch，并优先使用 `git worktree` 创建隔离工作区。QA 和 merge-test 前会尝试创建 checkpoint commit，因此 Git 用户信息必须可用：

```bash
rtk git --version
rtk git config --global user.name
rtk git config --global user.email
```

目标项目需要满足：

- 项目路径在部署机上存在，Gateway 运行用户可读写。
- 推荐是 Git 仓库；非 Git 目录会降级为复制目录，但 merge-test 能力会受限。
- 默认 base branch 是 `main`；如项目使用其他分支，需要在需求来源或项目配置中声明 `base_branch` / `source_base_branch`。
- 项目内推荐提供 `WORKFLOW.md` 或 `.codex/AGENTS.md`，写清 allowed paths、forbidden paths、测试命令和发布策略。
- 所有测试命令建议使用 `rtk` 前缀，例如 `rtk pnpm test`、`rtk pytest -q`。

### 6. 飞书和需求来源读取

如果只从纯文本创建任务，可以跳过本节。若需求里包含飞书 Project、Wiki 或 Doc 链接，需要配置对应读取能力。

飞书 Project / Meegle 工作项读取：

```text
FEISHU_PROJECT_PLUGIN_TOKEN=...
FEISHU_PROJECT_USER_KEY=...
FEISHU_PROJECT_WORK_ITEM_DETAIL_URL_TEMPLATE=https://project.feishu.cn/open_api/{project_key}/work_item/{work_item_type_key}/{work_item_id}
```

飞书 Wiki / Doc 读取默认使用 `lark-cli`：

```bash
rtk which lark-cli
rtk lark-cli config bind --source hermes --identity user-default
```

可选环境变量：

```text
FEISHU_DOC_LARK_CLI=/absolute/path/to/lark-cli
FEISHU_DOC_FETCH_TIMEOUT_SECONDS=20
```

如果飞书读取权限缺失，插件会创建任务但停在 `needs_human`，不会把只有链接、没有正文的需求交给 Codex 自动规划。

## 符合性判断

执行生产安装前，按下面标准判断部署环境是否符合：

| 检查项 | 必需性 | 符合标准 |
|-|-|-|
| Hermes CLI / Gateway | 必需 | `rtk hermes --version`、`rtk hermes gateway status` 可正常返回 |
| SSH 仓库访问 | 必需 | `rtk git ls-remote git@github.com:cc-Listener/coding-orchestration-plugin.git HEAD` 返回 commit hash |
| Python | 必需 | `rtk python3 --version` 返回 Python 3.10 或更高版本 |
| Codex CLI | 必需 | `rtk codex --version` 和 `rtk codex exec --help` 可正常返回 |
| Git identity | implementation / QA / merge-test 必需 | `rtk git config --global user.name` 和 `rtk git config --global user.email` 有值 |
| 项目注册 | 可选 | 不需要在初始化时带入；如需批量 bootstrap，再手动创建 `${CODING_ORCHESTRATION_ROOT}/project-registry.json` |
| 飞书 Project / Wiki / Doc 读取 | 使用飞书链接时必需 | Project token 或 `lark-cli` 绑定可用 |

判定规则：

- 全部必需项通过：可以执行生产安装。
- SSH 仓库访问不通过：不符合，禁止执行安装命令。
- Codex CLI 不通过：不符合，安装后也无法执行 plan-only / implementation。
- 飞书读取不通过但只使用纯文本需求：可以安装，但飞书链接任务会停在 `needs_human`。

## 部署目录规划

测试部署和生产部署必须拆分运行根目录。不要让两套环境共享同一个 `ledger.db`、`runs`、`workspaces` 或 `llm-wiki`；可选的 `project-registry.json` 也必须按环境独立维护。

| 环境 | Gateway 环境变量 | 运行根目录 | 用途 |
|-|-|-|-|
| 测试 | `CODING_ORCHESTRATION_ROOT=~/.hermes/coding-orchestration-test` | `~/.hermes/coding-orchestration-test` | 验证插件安装、命令入口、runner、飞书读取和项目注册 |
| 生产 | `CODING_ORCHESTRATION_ROOT=~/.hermes/coding-orchestration-prod` | `~/.hermes/coding-orchestration-prod` | 团队正式任务、长期 Task Ledger、正式 LLM Wiki 知识 |

每个运行根目录内部结构一致：

```text
<CODING_ORCHESTRATION_ROOT>/
  ledger.db
  runs/
  workspaces/
  llm-wiki/
```

部署约束：

- 同一个 Hermes Gateway 进程只能绑定一个 `CODING_ORCHESTRATION_ROOT`。
- 测试和生产需要同时在线时，使用两个独立 Gateway 进程或两套 Hermes home，并分别设置不同的 `CODING_ORCHESTRATION_ROOT`。
- 修改 `CODING_ORCHESTRATION_ROOT` 后必须重启对应 Gateway。
- 初始化不需要带入 `project-registry.json`。生产项目知识应通过 LLM Wiki `project_profile` 或后续人工确认沉淀；如临时使用 registry 做批量 bootstrap，必须逐项确认项目路径、allowed paths、forbidden paths 和测试命令。

## 项目注册配置（可选）

插件按当前运行根目录尝试读取可选 registry：

```text
${CODING_ORCHESTRATION_ROOT}/project-registry.json
```

如果文件不存在，插件会使用空 registry 启动，不影响安装和命令加载。不要在初始化时复制示例 registry 到生产。

如需测试环境批量 bootstrap，可显式复制示例后再改成测试项目路径：

```bash
rtk mkdir -p ~/.hermes/coding-orchestration-test
rtk cp examples/project-registry.json ~/.hermes/coding-orchestration-test/project-registry.json
```

生产环境只创建目录，不预置 registry：

```bash
rtk mkdir -p ~/.hermes/coding-orchestration-prod
```

如果生产确实需要 registry bootstrap，必须由维护者手动创建，并把项目名、路径、关键词和测试命令改成真实项目：

```json
{
  "projects": [
    {
      "name": "order-system",
      "aliases": ["订单系统", "OMS"],
      "path": "/Users/xiaojing/Desktop/projects/order-system",
      "keywords": ["订单", "发货", "库存"],
      "allowed_paths": ["src/", "tests/"],
      "forbidden_paths": [".env", "deploy/", "scripts/release"],
      "default_test_commands": ["rtk pnpm test", "rtk pnpm build"],
      "default_runner": "codex_cli"
    }
  ]
}
```

验收时至少确认一个真实项目能被 `/coding task --project <项目名> ...` 命中。

## 测试部署步骤

### 1. 配置测试运行目录

把测试 Gateway 进程环境设置为：

```text
CODING_ORCHESTRATION_ROOT=~/.hermes/coding-orchestration-test
```

如果 Hermes 由 launchd、systemd、Docker 或其他进程管理器启动，需要在对应服务配置里设置该环境变量；只在当前终端设置不会影响已运行的 Gateway。

### 2. 安装插件

测试环境也使用 SSH Git URL 安装，先确认 SSH 仓库访问符合：

```bash
rtk git ls-remote git@github.com:cc-Listener/coding-orchestration-plugin.git HEAD
```

安装命令：

```bash
rtk hermes plugins install git@github.com:cc-Listener/coding-orchestration-plugin.git --enable
```

### 3. 准备测试运行目录

```bash
rtk mkdir -p ~/.hermes/coding-orchestration-test
```

测试初始化不需要带入 registry。需要批量 bootstrap 时，再手动创建 `~/.hermes/coding-orchestration-test/project-registry.json` 并指向测试项目路径或测试分支项目路径。

### 4. 重启测试 Gateway

```bash
rtk hermes gateway restart
```

### 5. 测试验收

在飞书或 Hermes Gateway 会话里发送：

```text
/commands
/coding help
/coding status
```

用测试项目做一次 plan-only 验收：

```text
/coding task --runner codex_cli --project <测试项目名> 测试部署验收：只检查项目结构并输出实现计划，不修改文件
```

预期结果：

- `~/.hermes/coding-orchestration-test/ledger.db` 被创建或更新。
- `~/.hermes/coding-orchestration-test/runs` 生成本次 run artifact。
- `~/.hermes/coding-orchestration-test/workspaces` 在 implementation 前不应产生生产项目写入。
- `/coding help`、`/coding status` 正常响应。
- plan-only 阶段不修改项目文件。

## 生产部署步骤

### 1. 安装插件

生产安装前必须先完成测试部署验收。生产环境仍使用 SSH Git URL，并在安装前确认 SSH 仓库访问符合：

```bash
rtk git ls-remote git@github.com:cc-Listener/coding-orchestration-plugin.git HEAD
```

安装命令：

```bash
rtk hermes plugins install git@github.com:cc-Listener/coding-orchestration-plugin.git --enable
```

### 2. 配置生产运行目录

把生产 Gateway 进程环境设置为：

```text
CODING_ORCHESTRATION_ROOT=~/.hermes/coding-orchestration-prod
```

生产环境目录必须独立于测试环境。不要使用 `~/.hermes/coding-orchestration-test` 或兼容默认目录承载生产任务。

### 3. 准备生产运行目录

```bash
rtk mkdir -p ~/.hermes/coding-orchestration-prod
```

生产初始化不需要带入 registry。首次项目识别和项目画像应通过 LLM Wiki `project_profile` 或人工确认流程沉淀；只有需要批量 bootstrap 时才手动创建 registry。

### 4. 配置 Hermes

在 Hermes 配置中启用插件，并保留默认 `codex_cli` runner：

```yaml
plugins:
  enabled:
    - coding_orchestration

coding_orchestration:
  enabled: true
  default_runner: codex_cli
  runners:
    codex_cli:
      command: codex
    hermes_autonomous_codex:
      command: codex
      skill_path: ~/.hermes/hermes-agent/skills/autonomous-ai-agents/codex/SKILL.md
  ledger_db: ~/.hermes/coding-orchestration-prod/ledger.db
  run_root: ~/.hermes/coding-orchestration-prod/runs
  workspace_root: ~/.hermes/coding-orchestration-prod/workspaces
  llm_wiki:
    adapter: local
    root: ~/.hermes/coding-orchestration-prod/llm-wiki
```

当前插件代码使用 `CODING_ORCHESTRATION_ROOT` 选择运行根目录；如未设置该环境变量，会回退到兼容默认目录 `~/.hermes/coding-orchestration`。生产部署必须显式设置 `CODING_ORCHESTRATION_ROOT=~/.hermes/coding-orchestration-prod`。

### 5. 重启生产 Gateway

```bash
rtk hermes gateway restart
```

### 6. 验证插件加载

```bash
rtk hermes plugins list
rtk hermes gateway status
```

在飞书或 Hermes Gateway 会话里发送：

```text
/commands
/coding help
/coding status
```

预期结果：

- `/commands` 能看到 `/coding help`、`/coding task`、`/coding status`、`/coding delete`。
- `/coding help` 输出完整命令说明。
- 普通自然语言默认不会进入插件；发送“进入coding”后，自然语言才会进入 Coding Mode rewrite。
- 生产 run artifact 写入 `~/.hermes/coding-orchestration-prod/runs`，不会写入测试目录。

### 7. 执行一次只读验收任务

用生产真实项目做一次 plan-only 验收：

```text
/coding task --runner codex_cli --project <生产项目名> 生产部署验收：只检查项目结构并输出实现计划，不修改文件
```

预期结果：

- Task Ledger 创建新任务。
- `~/.hermes/coding-orchestration-prod/runs` 生成 `input-prompt.md`、`run-manifest.json`、`stdout.log`、`stderr.log`、`report.json`、`summary.md`。
- 任务进入 `plan_ready` 或在缺少上下文时进入 `needs_human`。
- plan-only 阶段不修改项目文件。

## 本地调试安装

本地开发或临时调试时，可以把当前 checkout 软链接到 Hermes plugins 目录：

```bash
rtk proxy python3 scripts/install_symlink.py --hermes-home ~/.hermes
rtk hermes plugins enable coding_orchestration
rtk hermes gateway restart
```

确认软链接：

```bash
rtk ls -l ~/.hermes/plugins/coding_orchestration
```

软链接安装只适合 debug。生产环境不要依赖本地 checkout，因为源码改动会立即影响运行中的 Hermes。

## 安装后自检清单

基础自检：

```bash
rtk python3 -m unittest tests.test_docs_and_install_entry
rtk python3 -m unittest tests.test_plugin_registration
rtk python3 -m unittest tests.test_router_prompt_summary
```

运行态自检：

- `~/.hermes/plugins/coding_orchestration` 存在，或生产插件安装记录里已启用 `coding_orchestration`。
- 初始化后不要求存在 `project-registry.json`；如果使用 registry bootstrap，测试和生产必须使用各自运行根目录下的独立文件。
- 测试环境 `~/.hermes/coding-orchestration-test/runs` 和 `workspaces` 可写；生产环境 `~/.hermes/coding-orchestration-prod/runs` 和 `workspaces` 可写。
- Gateway 进程环境里的 `CODING_ORCHESTRATION_ROOT` 指向当前要验收的环境目录。
- Gateway 环境里 `codex` 可执行。
- Gateway 环境里 `rtk git config --global user.name` / `rtk git config --global user.email` 可用。
- 需要飞书文档读取时，Gateway 环境里 `lark-cli` 可执行且已绑定 Hermes 身份。
- `/coding help`、`/coding task`、`/coding status` 均可响应。

## 权限边界

- plan-only 使用只读 profile：只允许读取项目文件和外部上下文，不允许修改项目文件。
- implementation / QA / merge-test 使用受控高权限 Codex CLI session：源码修改必须留在 task worktree 内。
- 项目外写入仅限依赖缓存、Git metadata、dev server/browser 临时文件和 QA artifacts。
- merge-test 只处理 source branch 到 `test` 的合并；发布测试环境仍由人工控制。
- Task Ledger 是运行期事实源；LLM Wiki 只保存知识、草稿、run summary 和 QA 经验。

## 回滚

优先通过禁用插件回滚，保留 Task Ledger 和 run artifacts 便于审计：

```bash
rtk hermes plugins disable coding_orchestration
rtk hermes gateway restart
```

确认 `/coding help` 不再响应后，再按团队发布流程处理插件包或调试软链接。不要直接删除 `~/.hermes/coding-orchestration-prod` 或 `~/.hermes/coding-orchestration-test`，除非已经确认不需要保留对应环境的历史任务、run artifacts 和 LLM Wiki。

## 常见问题

`/commands` 看不到 `/coding`

- 插件未 enable，或 Gateway 没有重启。
- Hermes 插件目录没有加载到 `coding_orchestration`。
- 插件加载时 Python 版本或 import path 不正确。

`/coding task` 创建后停在 `needs_human`

- 飞书 Project / Wiki / Doc 链接没有被成功读取。
- 检查 `FEISHU_PROJECT_PLUGIN_TOKEN`、`FEISHU_PROJECT_USER_KEY` 和 `rtk lark-cli config bind --source hermes --identity user-default`。
- 也可以直接在 `/coding task` 里粘贴完整需求正文。

Codex runner 报 `process_start_failed`

- Gateway 环境找不到 `codex`。
- 设置 `CODEX_CLI_COMMAND` 为绝对路径，并重启 Gateway。
- 确认 Gateway 运行用户已登录 Codex CLI。

QA 或 merge-test 前 checkpoint commit 失败

- 检查 Git 用户信息：

```bash
rtk git config --global user.name
rtk git config --global user.email
```

- 如生产环境不允许 global config，需要在目标项目或 Gateway 用户环境中配置等价的 Git identity。

plan-only 阶段出现文件修改

- 确认 Codex CLI 支持 `--sandbox read-only`。
- 检查 runner 是否仍为 `codex_cli`，没有被改成自定义高权限 runner。
- 保留 run 目录和 diff 证据，先不要进入 `/coding implement`。

## 一键安装 Agent Prompt

把下面整段复制给具备终端权限的 Agent，用于在目标机器执行生产安装。Agent 必须在关键步骤后输出检查结果；任一必需检查不通过时必须停止，不要继续安装。

```text
请帮我在这台机器上按生产部署安装 Hermes plugin `coding_orchestration`。

约束：
- 全程使用简体中文汇报。
- 所有 shell 命令必须加 `rtk` 前缀。
- 生产插件来源固定为 SSH 仓库：`git@github.com:cc-Listener/coding-orchestration-plugin.git`。
- 生产运行根目录固定为：`~/.hermes/coding-orchestration-prod`。
- 初始化时不要复制或创建 `project-registry.json`；项目注册后续通过 LLM Wiki `project_profile` 或人工确认流程沉淀。
- 不要删除 `~/.hermes/coding-orchestration-prod` 里的历史数据；如果是重装，只删除 Hermes 插件安装物和插件入口。
- 如果任何前置检查失败，停止并说明失败原因、影响和修复建议。

前置检查：
1. 执行 `rtk which hermes`、`rtk hermes gateway status`，确认 Hermes 可用。
2. 执行 `rtk which codex`，确认 Codex CLI 可用；如 `.env` 里有 `CODEX_CLI_COMMAND`，同时确认该绝对路径存在。
3. 执行 `rtk git ls-remote git@github.com:cc-Listener/coding-orchestration-plugin.git HEAD`，必须返回 commit hash 和 `HEAD`。
4. 执行 `rtk ls -ld ~/.hermes ~/.hermes/plugins`，确认 Hermes home 和 plugins 目录可写。

安装步骤：
1. 备份配置：
   - 先执行 `rtk date +%Y%m%d%H%M%S` 获取时间戳。
   - `rtk cp ~/.hermes/config.yaml ~/.hermes/config.yaml.bak-coding-install-<timestamp>`
   - `rtk cp ~/.hermes/.env ~/.hermes/.env.bak-coding-install-<timestamp>`，如果 `.env` 存在。
2. 如已安装旧插件，先禁用：
   - `rtk hermes plugins disable coding_orchestration`
3. 删除旧插件安装物，但不要删除生产运行根目录：
   - 删除 `~/.hermes/plugins/coding_orchestration` 软链或目录。
   - 删除 `~/.hermes/plugins/coding-orchestration-plugin` 克隆目录。
   - 不要删除 `~/.hermes/coding-orchestration-prod`。
4. 安装插件：
   - 优先执行 `rtk hermes plugins install git@github.com:cc-Listener/coding-orchestration-plugin.git --enable`。
   - 安装后检查 `~/.hermes/plugins/coding-orchestration-plugin/coding_orchestration/plugin.yaml` 是否存在。
   - 如果 Hermes install 因 clone 超时失败，改用：
     `rtk git clone --depth 1 git@github.com:cc-Listener/coding-orchestration-plugin.git ~/.hermes/plugins/coding-orchestration-plugin`
   - 如果仓库根目录没有 `plugin.yaml`，这是当前仓库结构的预期情况；需要把真实插件子目录注册为 Hermes 插件入口：
     `rtk ln -s ~/.hermes/plugins/coding-orchestration-plugin/coding_orchestration ~/.hermes/plugins/coding_orchestration`
   - 禁用无效根目录插件名：
     `rtk hermes plugins disable coding-orchestration-plugin`
   - 启用真实插件名：
     `rtk hermes plugins enable coding_orchestration`
5. 配置生产运行根目录：
   - 在 `~/.hermes/.env` 中设置或更新：
     `CODING_ORCHESTRATION_ROOT=~/.hermes/coding-orchestration-prod`
   - 在 `~/.hermes/config.yaml` 中确认：
     `plugins.enabled` 包含 `coding_orchestration`，`plugins.disabled` 包含 `coding-orchestration-plugin` 且不包含 `coding_orchestration`。
   - 确认 `coding_orchestration` 配置使用生产路径：
     `ledger_db: ~/.hermes/coding-orchestration-prod/ledger.db`
     `run_root: ~/.hermes/coding-orchestration-prod/runs`
     `workspace_root: ~/.hermes/coding-orchestration-prod/workspaces`
     `llm_wiki.root: ~/.hermes/coding-orchestration-prod/llm-wiki`
   - 不要配置 `project_registry`，除非我明确要求 registry bootstrap。
6. 创建生产运行基础目录：
   - `rtk mkdir -p ~/.hermes/coding-orchestration-prod/runs ~/.hermes/coding-orchestration-prod/workspaces ~/.hermes/coding-orchestration-prod/llm-wiki`
7. 重启 Gateway：
   - `rtk hermes gateway restart`

验收：
1. `rtk hermes plugins list` 必须显示 `coding_orchestration enabled`。
2. `rtk hermes gateway status` 必须显示 Gateway service loaded。
3. `rtk curl -i -s http://127.0.0.1:8642/health` 必须返回 `200 OK` 和 `{"status": "ok", "platform": "hermes-agent"}`。
4. `rtk git -C ~/.hermes/plugins/coding-orchestration-plugin rev-parse HEAD` 输出的 commit 必须和 `git ls-remote ... HEAD` 一致。
5. 验证插件命令注册：
   `rtk ~/.hermes/hermes-agent/venv/bin/python -c "import os; os.environ['CODING_ORCHESTRATION_ROOT']=os.path.expanduser('~/.hermes/coding-orchestration-prod'); from hermes_cli.plugins import get_plugin_commands; print(sorted(get_plugin_commands()))"`
   输出里必须包含 `coding`。
6. 验证 LLM Wiki 初始化：
   - `~/.hermes/coding-orchestration-prod/llm-wiki/purpose.md`
   - `~/.hermes/coding-orchestration-prod/llm-wiki/schema.md`
   - `~/.hermes/coding-orchestration-prod/llm-wiki/raw/sources/`
   - `~/.hermes/coding-orchestration-prod/llm-wiki/wiki/index.md`
   - `~/.hermes/coding-orchestration-prod/llm-wiki/wiki/overview.md`
   - `~/.hermes/coding-orchestration-prod/llm-wiki/wiki/log.md`
7. 最后汇总：安装来源、安装 commit、生产运行根目录、是否未带入 `project-registry.json`、Gateway 状态、插件命令列表。
```
