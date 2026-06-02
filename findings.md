# 发现与决策

## 需求
- 以 Hermes 中 `task_43141b20c03e` 为例，整理 coding plugin 的全量优化计划。
- 重点包括：
  - 不再要求每次显式输入 `/coding`
  - 分支名使用语义名称而不是纯 task id
  - prepare merge test 独立阶段
  - 最终结构化报告兜底
  - 验证受限必须给解决方案
  - Codex runner 使用可见 session，方便 CLI 查看

## 研究发现
- `task_43141b20c03e` 的业务实现基本完成，但最后状态仍被记录为 `blocked`。
- `blocked` 原因主要是验证环境受限，而不是实现未完成：
  - API refresh 脚本或 `.api-spec.json` 在 workspace 中不可用
  - DNS 阻断 API refresh
  - `pnpm build:test` 写 `dist/`，与 forbidden path 冲突
  - dev server 受沙箱限制无法监听端口
  - 全量 lint/tsc 有仓库既有错误
- 最后一轮 `run_5c0fa2540629` 没有生成 `report.json`，只有 stdout/stderr，导致最新状态无法被机器可靠消费。
- 当前分支名 `codex/bps-admin-task_43141b20c03e` 不利于人工识别，应改为 `codex/orderflows-filter-actions-43141b20c03e` 这类语义分支名。
- 每次显式 `/coding` 的调用成本较高，可用 `进入coding` / `退出coding` 作为会话级模式切换。
- 当前代码入口：
  - gateway 入口：`CodingOrchestrator.handle_gateway_event`
  - 显式命令解析：`_CODING_COMMAND_RE`、`_handle_explicit_gateway_command`、`_normalize_coding_gateway_command`
  - run/manifest：`start_run`、`_build_manifest`
  - runner 启动与 report 兜底：`CodexCliRunner.run_subprocess`、`load_or_build_report`、`build_fallback_report`
  - 状态映射：`TaskStateMachine`、`_task_status_for_run_result`、`_task_phase_for_run_result`
  - prompt/schema：`PromptBuilder`、`_write_report_schema`
- 当前测试已覆盖“普通自然语言不会进入 plugin”，实现 Coding Mode 时需要改成默认不触发、mode 开启后才触发。
- `prepare-merge-test` 当前已经是独立命令，直接更新 phase 和 merge record，不启动 run；仍缺自然语言 Coding Mode 下的语义分流。
- 当前分支名逻辑是 `codex/<project_name>-<task_id>`，位置在 `_source_branch_for_task`，可局部替换为 requirement semantic slug + task id 后缀。
- 当前 run-manifest 已有 `resume_session_id`、`workspace_path`、`source_branch`、`dangerous_bypass`，但没有独立 `session_id`、`attach_command` 字段，也没有 runner 完成后回写 manifest。
- 当前 report fallback 只覆盖 subprocess 正常结束后的缺失/非法 report；background wrapper 捕获异常时只更新 ledger failed，不创建 run artifact/report。
- 当前 `AgentRunStatus.COMPLETED_UNSTRUCTURED` 被映射成 task `blocked`，状态机需要显式区分 `runner_failed` 和 `ready_for_merge_test_with_known_gaps`。
- 本机 Codex CLI 支持 `codex resume <session>` 打开交互会话，也支持 `codex exec resume <session> -` 非交互续跑；未看到单独的 live attach 子命令。当前实现记录 `attach_command=codex resume <session_id>` 和 `resume_command=codex exec resume <session_id> -`。
- `rtk python3 -m unittest` 和 `rtk python3 -m unittest discover` 在仓库根目录未发现测试；需要使用 `rtk python3 -m unittest discover -s tests`。
- Hermes Gateway 已通过 `rtk hermes gateway restart` 重新加载当前 symlink 插件，`rtk hermes plugins list` 显示 `coding_orchestration` 为 enabled，`/health` 返回 ok。
- Gateway 重启后日志不再出现 `Plugin 'coding_orchestration' registered unknown hook 'command:commands'`，说明移除未知 hook 注册已生效。
- OpenAI-compatible API `POST /v1/chat/completions` 和 `hermes -z "/coding help"` 不会触发 plugin slash command handler，会被 Hermes 主 agent 当作普通文本处理；插件命令测试应走 Gateway slash command 分发或 Hermes 插件管理器 `get_plugin_command_handler`。
- 使用 Hermes venv 加载插件管理器可确认 `coding`、`coding-help` 已注册，coding/codex 相关命令共 21 个，`coding` handler 对 `help` 能返回新版帮助内容。
- Coding Mode 自然语言入口此前在开启后只识别 prepare merge test，其他输入会无条件 `_create_task_from_text`；因此“现在有多少个task”这类查询被误创建为低置信度 task。修复点应在创建前做意图分类：list/status 查询先分流，不明确或项目低置信度只回复确认，不写 ledger。
- `/coding list` 和 Coding Mode 的 task 列表原先显示 `phase/status/project_path`，飞书中信息密度不对。用户期望的是可读任务摘要：状态、id、项目名称、任务简单描述；路径可作为 status 详情保留，不适合作为 list 主字段。
- 用户明确不再需要 `/coding-*` 和 `/codex-*` 旧别名。插件注册层应只注册 `coding` 一个 slash command；Gateway 正则只接受 `/coding` 后接空白或结束；帮助和文档不再出现兼容别名说明。
- `task_43141b20c03e` 的最新 implementation run 被 diff guard / 验证受限标成 `blocked`，但后续人工已确认需求完成并要求准备 merge test。原 `command_prepare_merge_test` 对 `blocked` 直接拒绝，导致状态无法收敛到 P0 新增的 `ready_for_merge_test_with_known_gaps`。
- `task_43141b20c03e` 的 merge-test 并非阻塞失败：run `run_cc72448ac5b1` 成功完成，台账为 `done/merged_test`。接近 4 分钟的主要耗时来自完整 Git 合并流程和一次 `src/components/order/orderFlowFilterPresetUtils.test.ts` 冲突解析；当前 report/manifest 没有阶段耗时 timeline，只能通过 Gateway 时间、ledger 更新时间和 stdout 事件顺序还原。
- 对外状态展示应以 `TaskStatus` 为唯一入口；`TaskPhase` 目前仍被 ledger、manifest、run 完成映射和测试使用，直接删除会牵涉 schema/历史数据迁移。当前先保留内部 phase，但飞书/命令可见输出统一展示 `TaskStatus` 的中文标识和英文 code。
- implementation 完成且验证通过后的默认目标状态应是 `ready_for_merge_test`（等待手动执行 merge test），而不是旧实现完成状态或 `blocked`。若 runner 返回 `blocked` 但工作区已有允许范围内改动，Hermes 将其归一为 `ready_for_merge_test_with_known_gaps`；只有 diff guard 越权、runner_failed、缺少人工输入或没有完成任何实现时才保留 blocked/failed。
- 用户确认状态口径：开发完成并验证成功后进入 `ready_for_merge_test`；Hermes 只告知人工执行 `/coding merge-test <task_id>`，不会在 implementation 阶段自动 merge/push test。
- `task_52725d8d6ff5` 可复现 session 复用问题：历史上多次 plan-only / implementation run 产生了多个 Codex session；当前 ledger 的 `task_session.runner.resume_session_id` 已指向最后一次 session `019e48a9-4fa0-7bd3-9fde-338b9d50e116`，但旧逻辑只有 merge-test 会真正 resume。
- Codex CLI `exec resume` 支持 `--json`、`--output-last-message`、`-c` 和 `--dangerously-bypass-approvals-and-sandbox`，但帮助中没有 `--output-schema`、`--sandbox`、`-C`。因此后续 resumed plan/implementation 通过 prompt contract 要求结构化 JSON，并继续依赖 `report.json` 兜底来处理非结构化输出。
- 交给 Codex 的 prompt 之前存在英文标题和说明（例如 `Required Outputs`、`GitOps Implementation Contract`、`Resumed Task Session Increment`），和中文需求上下文不一致。已统一改为中文自然语言；保留 `summary_markdown`、`test_results`、`status`、`ready_for_merge_test` 等机器契约字段和值。
- 旧兼容状态已移除，不再属于 `TaskStatus` / `AgentRunStatus` / report schema / prompt contract。状态机只保留当前统一状态集合。
- 用户确认自动测试链路交给 Codex 的 `$qa` skill。Hermes 不自研测试执行器，新的职责边界是 Hermes 负责编排、session 复用、artifact 回收、状态归一和 merge gate，Codex + `$qa` 负责浏览器 QA、修复、复验和报告。
- `$qa` 的关键约束会影响 Hermes 编排：要求 clean working tree；无 URL 且在 feature branch 时默认 diff-aware；必须打开浏览器测试、截图留证、产出 `.gstack/qa-reports/qa-report-*.md`、`screenshots/` 和 `baseline.json`；修 bug 时按问题 atomic commit。
- 引入 QA run 后，开发完成可以优先进入 QA 链路，但 QA 不是 merge-test 的硬前置；没有 QA run 时仍允许人工 merge-test，只需明确提示缺少自动 QA 证据。
- 当前 implementation 往往留下未提交改动，而 `$qa` 需要 clean tree 并会自己提交 bugfix；因此 Hermes 需要在 QA 前创建 source branch checkpoint commit，merge-test 不再负责首次提交实现。
- 已新增 `RunMode.QA = "qa"`：QA run 复用 task 级 Codex session，prompt 明确使用 `$qa` skill、diff-aware mode，不执行 merge-test、不发布、不部署。
- implementation 完成后会自动追加 QA run；同步命令和后台通知都会保留 implementation 摘要并追加 QA 摘要。
- QA run 启动前会尝试创建 checkpoint commit，commit message 为 `Implement <task_id> before QA`；如果 checkpoint 失败，Hermes 跳过 runner 并生成 `blocked` report，恢复动作要求配置 git 身份或手动提交后重试。
- `/coding merge-test` 的 QA 证据是可选项：没有 QA run 时继续但提示缺少自动 QA 证据；最近 QA failed / runner_failed / blocked / known gaps 时要求 `--confirm-qa-risk`；存在 tested commit 但当前 HEAD 已变化时提示 QA 证据过期。
- 用户确认 merge-test 成功不等于 task 完成。`/coding merge-test` 成功后状态应为 `merged_test`（已合并 test，待人工完成），仍属于未结束 task；`/coding list` 必须输出它，直到用户显式 `/coding complete <task_id>`。
- `/coding list` 的飞书可读性需要优先于信息密度：每个 task 使用多行字段输出，字段名为 `id`、`状态`、`项目`、`任务描述`；会话绑定和切换提示压成一行 `tip`。
- 用户确认需求变更应该有独立入口 `/coding change <反馈>`，不要混入 bugfix。change 记录 `requirement_change`，回到 plan-only 做变更影响分析和短计划；bugfix 继续只表示修已有实现的问题。
- 带图片的 bugfix/change/continue 反馈不能只把 `[Image]` 文本交给 Codex；Gateway event 里的 `media_urls/media_types` 必须进入 human decision，并在增量 prompt 中转成自然语言附件说明。
- 如果反馈里出现 `[Image]` 但 event 没有可访问 media，继续启动 Codex 会让 runner 误以为只有文本需求，容易做错 UI 样式；此时应拦截并要求用户重发图片、图片链接或文字描述。
- Coding Mode 自然语言 rewrite 不能继续由 Hermes 本地关键词判断承担；本轮已改为只在“进入coding”后调用可注入 LLM rewriter，LLM 输出标准 `/coding <action>` JSON，Hermes 负责 schema 校验和最终执行。
- 用户最新确认：高置信度 rewrite 可以直接执行，例如“最近的记录/现在有多少 task”这类明确查询。低置信度、缺信息、非法命令或 destructive 候选不会自动创建 task、不会启动 Codex。
- “查看最近对话记录，自然语言 rewrite 表现不符合预期”在存在 active task 时是对当前 coding task 的修复反馈，应 rewrite 为 `/coding bugfix <原文>`，不是 `/coding list` 或新建 task。
- `task_41c786eddf54/run_66f9a3cec8bc` 证明 `workspace-write` 仍不足以完成自动测试链路：缺 `node_modules` 时需要联网或私有源安装依赖，`$qa` 需要写 `.gstack` 报告和截图，QA bugfix commit 需要写主仓库 `.git/worktrees/.../index.lock`，dev server/browser QA 也可能需要 sandbox 外资源。
- 受控高权限边界应是 runner 权限放开、工作目录和产物边界收紧：implementation/QA 的 Codex CLI 使用 bypass 以允许安装依赖和提交 QA 修复，但子进程 cwd 仍是 task worktree；prompt/manifest 明确源码修改只限 workspace，项目外只允许依赖缓存、git metadata、dev server/browser 临时产物和 `.gstack` QA artifact。
- 用户进入 Codex session 查看真实交互时，当前 `input-prompt.md` 仍会把插件执行契约、输出 JSON 字段、状态机和权限边界一起塞进对话，虽然机器可控，但人工观察体验很差；需要把机器规范移到 run artifact，只在 visible prompt 中保留本轮需要执行的动作。
- 当前真实 demo task `task_26603ef00507` 验证了项目补充回填链路：用户补充“项目文件夹名称为 `oms_operation_web`”后，task source 中 `project_name=oms_operation_web`、`project_confidence=1.0`、`match_evidence=human_project_folder`，run manifest 的 `project_path` 指向 `/Users/xiaojing/Desktop/project/oms_operation_web`。
- `task_26603ef00507/run_6205d109d808` 验证了 prompt 瘦身生效：`input-prompt.md` 只包含目标、来源、上下文 artifact 引用和本轮动作；详细 report/schema/状态要求被放入 `run-instructions.md`。
- `task_26603ef00507` 验证了 Figma 插件链路：原始链接 `node-id=0-1` 对应画布，`get_design_context(0:1)` 初次因选区限制失败，但 Codex 通过 metadata 定位到实际订单列表 Frame `1:11893`，并记录查询面板、列表区、工具栏、表头和订单行节点。
- `task_26603ef00507` 当前只有一个成功 `plan-only` run，状态为 `planned / plan_ready`，Codex session 为 `019e6725-4153-7df2-9fd5-48d1ccf94842`，可用 `codex resume 019e6725-4153-7df2-9fd5-48d1ccf94842` 进入真实交互。
- `task_26603ef00507` 后续已进入 implementation：Hermes 复用同一 Codex session，创建 workspace `/Users/xiaojing/.hermes/coding-orchestration/workspaces/task_26603ef00507/run_75079e08c896` 和 source branch `codex/oms-figma-https-www-26603ef00507`，active run 为 `run_75079e08c896`。
- `run_75079e08c896` 证明 implementation prompt 只追加增量：已确认计划、需求变更、计划反馈和本轮动作；详细执行要求仍在 `run-instructions.md`。
- 当前 implementation 的真实验证链路已开始：Codex 先按 TDD 跑 `order-list-2/logic.test.ts`，发现 `vitest` 缺失后安装依赖；安装后遇到 Rollup 原生包 macOS quarantine/provenance，Codex 清理 xattr 后继续推进到 `@vben/vite-config` 解析问题。
- `task_26603ef00507` 暴露了 long-running implementation 反馈缺口：Codex stdout 中已有连续进展，包括目标单测通过、typecheck 被仓库既有错误阻断、dev server 启动、页面重定向到登录页等，但 Hermes 飞书侧没有主动发送中间摘要；用户只能看到 task 长时间 running。
- 进程检查确认 `run_75079e08c896` 对应 Codex 进程和 dev server/验证相关进程仍存在，不是完全停滞；问题是缺少 heartbeat/progress/timeline，而不是没有执行。
- `run_75079e08c896` 最终变成 failed 的直接链路：implementation run 到达一小时 deadline 后 `CodexCliRunner.run_subprocess()` 捕获 `TimeoutExpired`，调用 `build_fallback_report(... status=TIMEOUT)`；ledger 记录 `last_run_status=timeout`，随后 `TaskStateMachine._RUN_TO_TASK` 将 `AgentRunStatus.TIMEOUT` 映射为 `TaskStatus.FAILED`。
- timeout fallback report 的 `verification_limitations.reason` 已是 `runner_timeout`，但 `risks` 仍使用通用文案 `Structured report was not produced or failed schema validation.`，导致飞书反馈看起来像 JSON/schema 问题，而不是一小时超时。
- `run_75079e08c896` 的 stdout 显示 Codex 已进入收尾核对并准备返回 report：目标单测通过、相关单测通过、全量 typecheck 被既有错误阻断、dev server 可达但登录拦截、临时 dev server 已停止、`git diff --check` 通过；但在最终 JSON report 输出前被 timeout 终止。
- timeout 不是同一种业务状态：没有代码改动的 timeout 更像 runner 执行失败；已有实现改动和验证证据的 implementation timeout 应保留为“待合并测试（有已知缺口）”，让用户可以继续同一 task 或人工决定 merge-test。
- 继续 `task_26603ef00507` 不需要新建 task：该 task 已有 implementation run、workspace 和 Codex session，`/coding implement task_26603ef00507` 会复用 workspace `/Users/xiaojing/.hermes/coding-orchestration/workspaces/task_26603ef00507/run_75079e08c896` 和 session `019e6725-4153-7df2-9fd5-48d1ccf94842`。
- `task_26603ef00507/run_8781c841e264` 的根因不是实现失败，而是 Codex 最终输出了半结构化 JSON：包含 `status=ready_for_merge_test_with_known_gaps`、`summary_markdown`、`changed_files`、`test_results`、`verification_limitations`，但缺少 strict schema 要求的 `runner/mode/modified_files/human_required/next_actions` 等字段。
- 旧逻辑把半结构化 JSON 视为 invalid report，只恢复 `summary_markdown`，并把 implementation fallback 文案写成 plan-only 的“确认计划后进入 implementation”；这会把已完成实现误导成 `blocked`。
- 已用新恢复逻辑回写真实 run：`task_26603ef00507` 现在为 `status=ready_for_merge_test_with_known_gaps`、`phase=ready_to_merge_test`，latest agent run status 同步为 `ready_for_merge_test_with_known_gaps`。

## 技术决策
| 决策 | 理由 |
|------|------|
| Coding Mode 采用会话级状态 | 先降低复杂度，避免跨会话误触发 |
| 高置信度 rewrite 直接执行，低置信度二次确认 | Coding Mode 本身是显式开启的操作模式，明确意图应减少二次确认；低置信度、缺信息和 destructive 候选仍保留人工确认 |
| 验证结果分层输出 | 区分本次改动验证、全仓验证、环境受限和人工验证 |
| 可见 Codex session 作为人工任务默认 runner profile | 用户可在 CLI 中观察 session，减少黑盒后台感 |
| 保留 batch noninteractive profile | cron 或无人值守任务仍需要后台批处理 |
| Coding Mode 先用 active binding 表扩展 | 可以复用 session binding，不新增表结构 |
| report 受限信息用对象数组表达 | `reason`、`impact`、`recovery_action`、`fallback_evidence` 需要机器可消费，避免散落在 risks 字符串里 |
| 可见 session 先落地为可附着元数据 | 当前 runner 仍保留 `codex exec --json` 以维持结构化输出；完成后从 stdout 解析 session id，并写入 manifest/task_session 的 attach/resume 命令 |
| task 级 session 复用 | 首个 Codex run 创建 session；后续 plan retry、implementation、bugfix、merge-test 在 manifest 预填 `resume_session_id` 并执行 `codex exec resume`，input prompt 只放本轮增量上下文 |
| prompt 中文化边界 | 标题、说明、契约、检查清单中文化；JSON schema 字段、status code、命令、branch 名和 skill 名保持英文 |
| Hermes 本地 API chat 不作为插件命令冒烟入口 | 该入口走主 agent；插件命令验证使用 Gateway 日志、插件管理器 handler 或真实 Feishu Gateway 消息 |
| Coding Mode 不明确输入默认不创建 task | 只有明确任务意图且项目解析不需要人工确认时才落 ledger；低置信度只提示用户补项目或显式 `/coding task --project ...` |
| task list 使用用户可读字段 | 列表行统一为 `状态=<status> | id=<task_id> | 项目=<project_name> | 任务=<summary>`，Gateway 和命令模式共用 formatter |
| 只保留 `/coding <action>` | 移除插件命令注册中的 `/coding-*` 和 `/codex-*`，旧形式不再被 Gateway 拦截 |
| 人工 prepare/merge-test 可收敛 blocked implementation | 如果 task 是 `blocked` 且有 source branch 和 worktree，`/coding merge-test` 会把缺 report、越权 diff、runner_failed 或未落地代码等情况作为可接受风险提示；人工 `--accept-risk` 后记录风险接受并转为 `ready_for_merge_test_with_known_gaps`。缺 implementation run、source branch、worktree 或 cancelled 仍是硬阻断 |
| implementation 成功后直接 ready for merge-test | `success` 归一为 `ready_for_merge_test`，中文标识为“等待手动执行 merge test”；有改动但受限的 `blocked` 归一为 `ready_for_merge_test_with_known_gaps` |
| 移除旧兼容状态 | 删除旧的实现完成、验证部分完成、待评审兼容状态，避免 task status 出现多套含义 |
| 首次 prompt 不下发当前阶段/工作目录/测试命令/禁止范围 | 用户确认这些信息在当前阶段不需要；Codex session 本身已在对应目录打开，项目内已有规则和禁止范围，首次 prompt 应只给目标、来源、上下文引用和本轮要求 |
| `task_52725d8d6ff5` 历史耗时由多因素叠加 | 该 task 有 3 次 plan-only、2 次 implementation、1 次 merge-test；历史 run 每次都创建/记录不同 Codex session 或完整 prompt，plan prompt 达 65-70KB，implementation prompt 25-33KB，导致每轮都重复读取项目规则、Wiki、API 文档和代码入口 |
| QA 不由 Hermes 直接执行测试命令 | 测试链路交给 Codex 复用 `$qa` skill；Hermes 只新增 `qa` run 编排、prompt wrapper、report/artifact 回收和可选 QA 证据提示 |
| implementation/QA 使用受控高权限 | 依赖安装、私有源访问、dev server、浏览器 QA、`.git/worktrees` 和 `.gstack` 写入超出 `workspace-write` 能力；Codex runner 使用 bypass，但子进程 cwd 仍限定在 task worktree，manifest/prompt 明确源码修改边界，Hermes diff guard 继续兜底 |
| visible session prompt 最小化 | Codex session 是人会进入查看的界面，不能充当插件规范日志；详细执行/报告契约写入 `run-instructions.md`，prompt 只引用路径并给本轮动作 |
| QA run 默认 diff-aware | `$qa` 在 feature branch 无 URL 时已有 diff-aware 流程，能基于 branch diff 识别页面/路由并进行浏览器验证 |
| QA 前 checkpoint commit 是必需 gate | 满足 `$qa` clean tree 要求，同时让 implementation baseline、QA fix commit、merge-test commit 三类变更可追踪 |
| QA evidence 不作为 merge-test 硬前置 | 用户确认 QA 是可选项；缺少 QA evidence 不阻断 merge-test，只在有失败、过期或 known gaps 证据时要求人工显式确认风险 |
| merge-test 与 task 完成拆开 | 合入 test 后只进入 `merged_test`；人工确认测试环境后用 `/coding complete <task_id>` 标记 `done`，并记录 human decision |
| list 的任务描述是一句话摘要 | 长需求不直接截断展示编号列表；优先抽取第一条核心目标，例如“批量绑定商品弹窗支持变体ID/商品名称搜索” |
| change 与 bugfix 分流 | `/coding change` 触发 plan-only 影响分析，`/coding bugfix` 触发 implementation 修复，避免 Codex 在 bugfix 里重新规划 |
| 图片反馈先转成附件说明，不引入视觉模型 | 当前 Hermes 能拿到的是媒体 URL/路径和类型；先把这些结构化信息写入 ledger/wiki/prompt，让 Codex 明确按截图样式处理。真正 OCR/视觉描述需要额外下载和视觉模型链路，后续单独评估 |
| implementation/QA 使用更长默认超时 | 真实 implementation 已接近收尾但被 3600 秒硬截止；默认改为 implementation/QA 10800 秒，merge-test 5400 秒，plan-only 保持 3600 秒 |
| timeout 状态按证据归一 | timeout 且有代码改动进入 `ready_for_merge_test_with_known_gaps`；timeout 无改动进入 `runner_failed`；避免把可恢复实现误标成 `failed` |
| 半结构化 report 应先规范化再 fallback | Codex 有时能给出可用状态和验证证据，但没有完全满足 schema；Hermes 应补齐机器字段，保留真实状态，而不是丢弃为 `completed_unstructured` |
| merge-test 二次确认必须回到 Hermes 统一编排 | 真实 `task_26603ef00507/run_d3f3a72ea9dc` 中，Codex `merge-to-test` skill 因未跟踪文件在 session 内追问用户；用户回复“确定”后 Hermes 没有 pending action 上下文，转而进入 LLM rewrite，误触发新的 implementation。新的链路将“待确认动作”作为 Hermes 会话状态，确认词优先续接 pending action，其次检查 active run，最后才进入 LLM rewrite |
| merge-test 的实现改动提交应由 Hermes 前置处理 | source worktree 的 tracked/untracked 实现文件在 merge-test runner 启动前创建 checkpoint commit；Codex 不再承担“是否提交未跟踪文件”的会话追问职责，避免把确认散落在 Codex session 内 |
| Codex human_required 是 Hermes 可续接信号 | merge-test run 如果返回 `human_required=true`，task 保持在 `ready_for_merge_test_with_known_gaps`，并在当前会话写入 pending action；用户回复“确认/继续/可以/确定可以提交”等会重试 merge-test，不会被 LLM rewrite 成 bugfix/implementation |
| active run 期间确认词不是新指令 | 当前 task 仍有 `active_run_id` 时，确认词只返回正在执行的 run 信息和恢复动作，不启动新 run，也不调用 rewriter |
| cancelled 是人工终态保护 | task 被人工标记 `cancelled` 后，不允许 pending action、自然语言确认、显式 `/coding run/implement/prepare-merge-test/merge-test` 或底层 `start_run()` 再启动 Codex；`continue/change/bugfix` 也只能返回终态提示 |
| cancelled 需要显式恢复出口 | 用户可能误 cancel；普通动作仍被保护，但新增 `/coding restore <task_id>` 作为唯一恢复入口。restore 只恢复 Task Ledger 到最近可操作状态并清理 stale active run，不自动启动 Codex |
| LLM Wiki 项目初始化按稳定性分层 | 通用初始化不把项目文档全文塞入 prompt；稳定知识写 verified profile/contract，历史计划写 candidate index，API/Figma/飞书/Swagger 等动态来源只写 source index 并要求 read-before-use |
| API 契约不沉淀为长期 verified | `.api-spec.json`、`api-spec.md`、OpenAPI/Swagger 等只作为 `external_source_index`，具体 endpoint/schema/enum 必须在当前任务中重新读取并记录本次来源 |
| 人工补充项目也要增强初始化 | 用户通过“项目文件夹名称”补充的新项目不能只写空 `project_profile`；应扫描 AGENTS、contracts、docs、`.codex/.agents/skills`、package scripts 和历史 plans，形成可复用项目知识包 |
| Coding Mode enter/exit 需要幂等 | `进入coding` 日志命中 `coding_mode_entered`，不是正则误判；为防止平台重复事件或延迟消息造成重复回复，同一 Gateway message_id 只处理一次，重复 enter/exit 输出幂等文案 |
| runner status 必须在边界归一化 | Codex report 可能返回 task/phase 语义状态；Hermes 统一在 runner、orchestrator、schema 和 state machine helper 边界归一到 `AgentRunStatus`，再映射为 `TaskStatus` |

## 遇到的问题
| 问题 | 解决方案 |
|------|---------|
| `blocked` 语义过宽 | 增加 `ready_for_merge_test`、`ready_for_merge_test_with_known_gaps` 等状态 |
| 验证受限只记录风险 | 强制输出 `reason`、`impact`、`recovery_action`、`fallback_evidence` |
| 分支名不可读 | 使用语义 slug + task id 后缀 |
| 用户无法看到后台 Codex session | 使用可见 `codex` session，并写入 attach/resume 信息 |
| 仓库 unittest 默认发现不到测试 | 使用 `unittest discover -s tests` 作为全量验证命令 |
| CLI 沙箱读取 `~/.hermes/coding-orchestration` 可能被拒 | 对需要读取 Hermes home 或重启 Gateway 的命令使用提升权限；验证受限时记录 reason、impact、recovery_action、fallback_evidence |
| Coding Mode 查询被误建 task | 增加 list 查询意图分流，并在低置信度项目解析时只确认不创建 task |
| task list 暴露项目路径且缺任务摘要 | 改为显示项目名称和 requirement summary，路径不在 list 主行展示 |
| 帮助里仍展示兼容别名 | 删除帮助和文档中的兼容别名段，注册层只保留 `coding` |
| 已完成任务停留在 blocked | 对 blocked implementation 增加 prepare 收敛路径，并已将真实 `task_43141b20c03e` 更新为 `ready_for_merge_test_with_known_gaps` / `ready_to_merge_test` |
| merge-test 长时间无感等待 | 当前 runner 只在完成后回写结构化 report；后续应增加阶段进度回传和 run timeline，至少记录 Git 步骤 started/completed 时间、冲突文件、push 阶段耗时 |
| 用户侧 status/phase 双轴认知成本高 | 对外只显示 `TaskStatus`，格式为中文标签加英文 code，例如 `受阻(blocked)`；`TaskPhase` 暂作为内部过程字段保留，后续再做迁移删除 |
| 开发完成后仍可能 blocked | 新增 `ready_for_merge_test`，并在 implementation run 完成时做状态归一；blocked 仅保留给越权、runner 崩溃、缺人工输入或确实没有完成实现的场景 |
| 旧兼容状态残留 | 生产代码与用户文档不再出现旧兼容状态；测试保留负向断言，防止回归 |
| 首次 Codex prompt 过重 | 将 Wiki 正文、已确认计划、实现上下文等写入 run 级 artifact，prompt 只引用文件路径和短摘要，避免每次首次 run 都塞入完整上下文 |
| `task_52725d8d6ff5` implementation 慢的直接证据 | 首次实现 run 执行 84 条 command，耗时约 16m36s，包含读取多个 superpowers/project docs、API skill、代码入口、补测试、实现、反复验证；缺少 `.api-spec.json` 与 `node_modules` 导致 API 校验和 lint/build 受限 |
| `task_52725d8d6ff5` bugfix/返工慢的直接证据 | 返工 run 执行 59 条 command，耗时约 8m29s；它重新加载完整上下文并处理用户反馈，同时跑定点测试、定向 eslint、全量 lint、build:test 和 Sentry 环境变量 fallback；`build:test` 写入 `dist/` 触发 diff_guard violation，最终 status=blocked |
| `task_52725d8d6ff5` merge-test 慢的直接证据 | merge-test run 耗时约 8m22s，执行 33 条 command；流程包含 source branch commit/push、尝试切换 test 被另一个 worktree 占用、改走现有 test worktree、pull、merge、解决 `orderFlowFilterPresetUtils.test.ts` 冲突、commit、push 与校验 |
| 缺少自动 QA 证据提示 | 下一步新增 `RunMode.QA`；merge-test 不强制要求 QA run，但如果存在 QA 证据，要检查是否覆盖当前 source branch HEAD，并在过期或失败时展示结构化风险 |
| merge-test 成功后 task 被隐藏或误标完成 | 新增 `TaskStatus.MERGED_TEST` 并加入 active list；merge-test 成功映射到 `merged_test`，完成动作改由 `/coding complete` 人工触发 |
| list 输出太啰嗦 | 改为多行字段格式，并将长需求压缩为一句话摘要；tip 合并当前会话绑定和切换命令 |
| 需求变更与 bugfix 混用 | 新增 `/coding change <反馈>`，将其记录为 `requirement_change` 并启动 plan-only，不再直接进入 implementation |
| 图片反馈丢失 | human decision 新增 `media`，增量 prompt 输出 `图片附件`、`media_type` 和 URL/路径；只有 `[Image]` 占位但无 media 时不启动 Codex，提示重发图片或链接 |
| Coding Mode rewrite 误触发 | 移除自然语言关键词直连，改为 LLM rewriter 产出标准命令；高置信度直接执行，低置信度交给 Hermes 主 agent，destructive 候选进入 pending confirmation |
| Coding Mode 低置信度误把插件当最终回复方 | 低置信度 rewrite 原先直接发送“需要人工二次确认”并 `skip` 掉消息，导致 Hermes 主 agent 没机会结合上下文理解；已改为 `rewrite` handoff 给主 agent，高置信度 direct execute 和 destructive pending confirmation 保持不变 |
| 用户习惯先初始化项目再提需求 | 新增 `/coding project list/init/use/status/clear` 和 active_project binding；project init 只写 LLM Wiki 项目知识并绑定会话，不创建 task、不启动 Codex |
| 低置信度 handoff 缺可复用操作指南 | 新增 plugin 内置 skill `hermes-coding-operator`，包含 intent triage、project-first workflow、task next step、feedback router、LLM Wiki helper 和 merge-test risk helper |
| needs_human 的项目补充没有结构化回填 | 真实 `task_f758ed7b9d99` 中“项目为 oms 后台，文件夹名称为 `oms_operation_web`”只写入 human_clarification/wiki，未更新 `project_path/source.project_name/task_session.project_name`；已新增人工补充项目文件夹识别、LLM Wiki project_profile 写入和 task 项目上下文回填 |
| plan-only 因 invalid_json_schema 被误报 blocked | 真实 `task_41c786eddf54/run_b8c47b4f3a5b` 的根因不是 stderr 中的 model refresh warning，而是 Hermes 生成的 `report.schema.json` 不满足 strict structured output：`qa_artifacts` 有 properties 但 required 不完整；已改为所有 object 的 properties 都完整列入 required，并将该类 stdout error 归类为 `runner_failed` |
| `/coding run` 长时间无输出 | Gateway 显式 `/coding run` 原先直接调用同步 `command_coding_run()`，Feishu 只有 Codex 完成后才收到回复；已改为 Gateway 先 ACK、后台执行 plan-only，且 running/queued task 不重复启动 |
| implementation 复用 session 继承只读沙箱 | `task_41c786eddf54/run_cf9f3582af41` 复用 plan-only session 后，Codex 报告环境仍是 `read-only` 且 approval `never`；根因是 `codex exec resume` 分支未覆盖 sandbox。已对 implementation/QA resume 增加 `-c sandbox_mode="workspace-write"`，manifest `resume_command` 同步展示该参数，并允许已有 implementation 记录的 blocked task 直接重试实现 |
| resume implementation 仍把 Hermes agent 目录当项目边界 | `task_41c786eddf54/run_12dec1860a6a` 的 stdout 显示 `pwd=/Users/xiaojing/.hermes/hermes-agent`，`apply_patch` 因目标仓库不在当前 project scope 被拒绝。`codex exec resume` 不支持 `-C`，因此仅改命令参数不够；已在 `subprocess.Popen(cwd=workspace_path)` 层把 implementation/QA/merge-test 限定到任务 worktree |
| 自动测试链路仍被 sandbox 限制 | implementation/QA 改为 Codex CLI bypass 权限，允许依赖安装、测试、dev server、浏览器 QA、`.git/worktrees` 和 `.gstack` 写入；安全边界改由 task worktree cwd、manifest/prompt 权限说明和 Hermes diff guard 共同兜底 |
| Codex session 输入噪音过多 | 将 report schema 字段、verification_limitations 细节、权限清单和状态码映射移出 visible prompt，写入 `run-instructions.md`；prompt 只保留必要动作、delta 和 artifact 引用 |
| implementation timeout 被误报 failed | 延长 implementation/QA 默认 timeout；`AgentRunStatus.TIMEOUT` 不再全局映射到 `failed`；fallback report 使用 runner_timeout 专用风险与恢复动作 |
| 半结构化 implementation report 被误报 blocked | 新增 partial structured report recovery：从 raw report/stdout 提取 JSON，补齐缺失字段，`changed_files` 归一为 `modified_files`，并按真实 `status` 更新任务 |
| merge-test 二次确认回复被误 rewrite | 新增会话级 pending action binding；QA 风险确认和 Codex `human_required` 都写入该 binding；确认词优先续接 pending action，active run 时只返回运行中信息；merge-test human_required 不再把 task 降为长期 blocked |
| cancelled task 仍可能被续接 | 已在 pending action、Gateway 命令、active task 反馈和 `start_run()` 层增加 cancelled gate；一旦 cancelled，不再操作该 task |
| 误 cancel 后无法继续 task | 新增 `/coding restore <task_id>`；真实 `task_26603ef00507` 已从 `cancelled` 恢复为 `ready_for_merge_test_with_known_gaps` / `ready_to_merge_test`，依据是最近 merge-test 未完成 |
| 分享/demo 文档落后于最新流程 | `docs/feishu-workflow-update-20260526.md` 已同步 Coding Mode rewrite、pending action、QA 可选证据、merge-test checkpoint、session/prompt 瘦身、`merged_test` 人工完成和 `/coding restore`；后续流程变更需要同步更新该总览文档，避免演示口径和插件行为不一致 |
| 飞书 Wiki/Doc 链接由 Codex 读取 | 真实 `task_f9eae60e8f1a` 的 `bestfulfill.feishu.cn/wiki/...` 证明只把 URL 当普通文本会让 Codex 不知道恢复动作；当前边界改为 Hermes 创建 task 时只索引 URL/token/推荐 `lark-cli docs +fetch` 命令，Codex plan-only session 自行读取，读取失败再结构化 blocked |
| Hermes 不再要求飞书用户身份绑定 | `lark-cli config bind --source hermes --identity user-default` 属于安全敏感配置，不应成为创建 task 前置条件；当前绑定建议改为 Codex session 内的 `rtk lark-cli config bind --source codex --identity user-default` 或由用户粘贴来源内容 |
| implementation source branch 默认从 `main` 创建 | workspace 创建必须显式传 base branch，不能隐式继承项目当前工作区 HEAD；默认 `source_base_branch=main`，可通过 task session 或 source 的 `source_base_branch/base_branch` 覆盖，manifest 会记录实际使用值 |
| implementation 完成后立即 checkpoint commit | implementation runner 返回可进入 merge-test 的状态后，Hermes 会先通过 diff guard，再创建 `Implement <task_id> after implementation` commit；QA 前 checkpoint 仍保留，但正常情况下只会看到 clean，提交失败会阻断 QA 并给恢复动作 |
| plan-only 不应使用 bypass | 规划阶段可能需要飞书/Lark 文档、Swagger/OpenAPI、私有 API 元数据、Keychain/认证上下文和网络资源；当前边界是 Hermes 只索引外部来源，Codex plan-only 自行读取并结构化报告恢复动作，仍保持 `read-only` sandbox，避免 bypass 后对项目外写入不可审计 |
| Hermes autonomous-ai-agents/codex 先作为 runner 后端接入 | 该 Hermes skill 当前是 agent-facing terminal/process 使用说明，不是 plugin-callable Python API；先新增 `hermes_autonomous_codex` runner 作为可切换后端，保留 orchestration 的状态机、ledger、report fallback、checkpoint 和 diff guard，后续再把底层 direct Codex subprocess 替换为 Hermes terminal/process |
| 文档口径必须跟随权限 profile 更新 | 当前准确口径是 plan-only 使用 `plan_read_only` 且 `dangerous_bypass=false`；implementation/QA/merge-test 使用受控高权限并由 cwd、manifest/prompt 和 diff guard 收口 |
| 新增 Python 模块必须进入 git diff | `command_rewriter.py` 与 `runners/hermes_autonomous_codex.py` 被 orchestrator/router 无条件 import；如果只是未跟踪文件，干净 checkout 会直接 `ModuleNotFoundError`，需要至少标记 intent-to-add 或正式 git add |
| runner fallback report 必须满足统一结构 | `_runner_failed_result` 和 checkpoint failed report 也要补齐 `qa_artifacts` 与 `tested_commit`，否则 runner 崩溃兜底报告仍会被后续结构化读取视为不完整 |
| blocked 风险默认确认后可人工覆盖 | `/coding merge-test` 对 blocked task 增加分层评估：缺 implementation run、source branch、worktree 或 cancelled 是硬阻断；缺 report、缺 session、diff guard 越权、runner_failed/failed、结构化字段不完整或未落地代码证据会返回风险确认，人工 `--accept-risk` 后记录 `accepted_risk` 和 `blocked_merge_test_released` 并继续 merge-test |
| 缺 Codex session 不再阻断 merge-test | 如果 source branch 和 worktree 存在但没有 resume_session_id，Hermes 会把它作为可接受风险提示；人工 `--accept-risk` 后启动新的 Codex session 执行 merge-test，避免老任务因 session 元数据缺失无法推进 |
| LLM Wiki 初始化只有极简 project_profile | 新增 `ProjectKnowledgeInitializer` 生成项目指导合同、架构地图、开发约定、验证画像、工具画像、agent tooling、动态来源索引、历史计划索引和风险画像；registry bootstrap 与人工项目补充都会调用 |
| 动态 API 来源容易过期 | `external_source_index` 使用 `status=candidate` 和 `freshness.mode=read_before_use`，prompt 召回时只能提示去实时读取，不能直接用旧 Wiki 内容实现字段 |
| 敏感配置不能进入 Wiki | `.env*` 只记录为 guarded/sensitive path，不读取内容、不生成 source hash，避免把 token 或环境值写入 LLM Wiki |
| Coding Mode 退出回复可能重复 | 增加 5 分钟 message_id 防抖；同时 `退出coding` 在未开启时回复“当前未开启”，避免重复事件第二次还返回“已退出” |
| Hermes plugin discovery 会把 symlink 当独立入口 | `~/.hermes/plugins/coding-orchestration-plugin/coding_orchestration` 和 `~/.hermes/plugins/coding_orchestration` symlink 会被加载成两个不同 module，导致两个 `pre_gateway_dispatch` hook 同时发送回复；注册入口需要进程级 guard，或后续清理重复 symlink |
| Codex 会返回任务语义 status | plan-only 可能返回 `ready_for_implementation` 这类人类语义状态；它不应进入 `AgentRunStatus` 状态机，runner 边界需要先归一为 `success`，再由 orchestrator 映射为 `planned/plan_ready` |
| 状态机边界不只在 runner | orchestrator 收尾、partial structured recovery、report schema 和 `TaskStateMachine.task_status_for_run_status()` 也可能接触外部 status；已改为统一调用 `normalize_agent_run_status()`，未知值降级为 `completed_unstructured` 而不是抛异常 |
| Coding Mode 低置信度交回 Hermes 主 agent | rewrite 低置信度、`intent=unknown`、缺 command 或缺信息时，plugin 不创建 task、不启动 runner、不直接发二次确认，而是返回 Gateway `rewrite` action，把原话、LLM 候选、拒绝原因、active task、known tasks 和 allowed commands 交给 Hermes 主 agent |
| command catalog 是 `/coding` 单一事实源 | `/coding help`、`/commands`、rewriter prompt、handoff allowed commands 都从 `coding_orchestration/command_catalog.py` 生成，避免 CLI 增加后 prompt 和文案漂移 |
| active_project 是会话级 binding | 支持用户先初始化/选择项目再提需求；active_project 存在时，新需求可注入项目上下文创建 task，但 active task 优先级更高 |
| 低置信度 handoff 使用 plugin 内置 skill | 插件注册 `hermes-coding-operator`，handoff prompt 要求 Hermes 主 agent 优先 `skill_view(name="coding_orchestration:hermes-coding-operator")`，让低置信度处理有固定 playbook |
| 上午 `task_7802123463ab` 项目匹配失败不是用户没给项目 | 12:03 raw text 已包含“商户后台 / bestvoy-admin”，但当时 project profile 尚未建立，create task 未从本地文件夹候选回退解析；12:18 project init 只绑定 active_project，没有回填既有 active task；12:24 `/coding continue` 又被归类为 plan_feedback，绕过项目澄清逻辑 |
| skill 建议不可用的根因是状态上下文不完整 | low-confidence handoff 只给 status，不给 phase/next_step；`hermes-coding-operator` 只覆盖理想状态，缺 failed、runner_failed、blocked、plan_revision，导致主 agent 容易建议当前状态下不能推进的动作 |
| 飞书 Wiki/Doc 权限失败不应阻断创建 task | 新口径改为 Codex-owned external source resolution：Hermes 只记录 URL/token/error/推荐 `lark-cli docs +fetch` 命令；只要项目已确定，task 继续进入 plan-only，由 Codex 在 session 内调用 `lark-cli` 读取，Codex 读取仍失败时才结构化 blocked 并给绑定/补充内容恢复动作 |
| 外部来源上下文没有进入可见 prompt | `source_context` 原先只写入 ledger，prompt 的“来源”和 `context-index.json` 没有展示 read_status、document_token、error 和 lark-cli 命令；已补充来源块和 context index，避免 Codex 不知道该读哪个飞书文档 |
| 真实 `task_449a0649f70c` 的失败来自创建 task 前强依赖飞书预读 | Gateway/adapter 返回 `read_status=failed`、`requires_human_context=true`、`docx:document:readonly` 后，插件输出“任务需要人工确认”。当前已取消 orchestrator 创建 task 时的 `FeishuProjectReader` 预读环节，改为直接索引文档来源；只要项目能识别，就继续 plan-only |
| `FeishuProjectReader` 不再处于创建 task 主链路 | `CodingOrchestrator._read_source_context()` 已改为 `_index_external_source_context()`，即使注入旧 reader 也不会调用；飞书 Project/Wiki/Docx 均记录为 `read_status=indexed`、`codex_resolvable=true`、`resolution_owner=codex` |
| “文件夹名称为 bestvoy-admin”需要在 source 失败时仍被解析 | 项目识别不应被飞书文档读取失败短路；run 前会从 source raw_text、normalized_text、requirement_summary 重新提取项目文件夹，并写回 `project_path/source.project_name/task_session.project_name` |

## 资源
- `/Users/xiaojing/.hermes/coding-orchestration/runs/task_43141b20c03e`
- `/Users/xiaojing/.hermes/coding-orchestration/workspaces/task_43141b20c03e/run_7ac73acb1520`
- `/Users/xiaojing/.hermes/coding-orchestration/llm-wiki/wiki/index.md`

## 视觉/浏览器发现
- 本轮没有新增浏览器或图片验证。

---
*每执行2次查看/浏览器/搜索操作后更新此文件*
*防止视觉信息丢失*
