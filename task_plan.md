# 任务计划：Coding Plugin P0 实现

## 目标
实现 Hermes/Codex coding plugin P0 优化，优先用最小改动补齐自然语言 Coding Mode、语义化分支名、可见 Codex session 元数据、prepare merge test 独立阶段、report.json 兜底、细化状态机，以及验证受限结构化恢复信息。

## 当前阶段
阶段 211：Task 34 run command executor 第十四切片（complete）

## 各阶段

### 阶段 1：需求与发现
- [x] 理解用户意图：减少 `/coding` 前缀负担，提升 coding plugin 可用性
- [x] 以 `task_43141b20c03e` 为样本复盘 Hermes 记录
- [x] 将关键发现记录到 `findings.md`
- **状态：** complete

### 阶段 2：规划与结构
- [x] 将优化项按 P0/P1/P2 分组
- [x] 明确验证受限解决方案
- [x] 明确 Codex session 可见化方案
- **状态：** complete

### 阶段 3：方案输出
- [x] 形成全量优化计划
- [x] 保持方案可 review、可拆任务
- **状态：** complete

### 阶段 4：验证与一致性检查
- [x] 确认计划覆盖用户新增关注点：语义分支名、Coding Mode、验证受限、Codex 可见 session
- [x] 记录受限项：本轮只输出产品/技术计划，不改 coding plugin 代码
- **状态：** complete

### 阶段 5：交付
- [x] 创建规划文件
- [x] 输出全量优化计划
- **状态：** complete

### 阶段 6：P0-A 自然语言 Coding Mode
- [x] 测试：`进入coding` 开启当前 gateway 会话 coding mode，`退出coding` 关闭。
- [x] 测试：coding mode 开启后，同会话自然语言高置信度创建 task 并自动 plan-only；普通无关话术不误触发。
- [x] 测试：低置信度自然语言只记录确认请求，不自动启动 run。
- [x] 实现：复用现有 active binding 表或 task_session 结构，增加会话级 mode binding，不引入跨会话持久策略。
- [x] 实现：更新 help/listing 文案，移除“普通自然语言不会进入 plugin”的绝对说法。
- **状态：** complete

### 阶段 7：P0-B 语义化分支名
- [x] 测试：implementation 分支名为 `codex/<semantic-slug>-<task-short-id>`，例如 `codex/orderflows-filter-actions-43141b20c03e`。
- [x] 测试：中文/特殊符号需求能生成稳定 ASCII slug；无法提取语义时回退项目名或 `task`。
- [x] 实现：在 `_source_branch_for_task` 最小改动，基于 requirement summary 和 task id 生成语义 slug，兼容已有 `source_branch`。
- **状态：** complete

### 阶段 8：P0-C 可见 Codex Session 与 run-manifest
- [x] 测试：人工触发 implementation 记录可见 Codex session 附着信息。
- [x] 测试：`run-manifest.json` 写入 `session_id`、`attach_command`、`workspace_path`、`source_branch`。
- [x] 实现：扩展 `RunManifest` 字段；runner 从 stdout 解析 thread/session 后回写 manifest 和 task_session。
- [x] 实现：保留 batch/noninteractive 能力给无人值守 run，避免破坏现有 plan-only。
- **状态：** complete

### 阶段 9：P0-D prepare merge test 独立阶段
- [x] 测试：`/coding prepare-merge-test` 只进入准备阶段和 merge record，不启动 implementation。
- [x] 测试：自然语言 coding mode 下“准备 merge test / 可以 merge test”映射到 prepare 阶段，不走 bugfix/implementation。
- [x] 实现：增加自然语言解析分流；必要时细化 phase/status，不扩大 merge-test 自动权限。
- **状态：** complete

### 阶段 10：P0-E report.json 兜底与 runner_failed
- [x] 测试：runner 正常退出但无有效 report 时生成 `completed_unstructured` 或状态映射报告。
- [x] 测试：runner 启动/执行异常也生成 `report.json`，状态为 `runner_failed`，并写入 reason、impact、recovery_action、fallback_evidence。
- [x] 实现：把 background run 异常兜底落到 run artifact，而不是只更新 ledger failed。
- **状态：** complete

### 阶段 11：P0-F 状态机细化
- [x] 测试：支持 `ready_for_merge_test`、`ready_for_merge_test_with_known_gaps`、`runner_failed`。
- [x] 测试：run status 到 task status/phase 的映射区分等待手动 merge-test、已知验证缺口、runner 崩溃。
- [x] 测试：implementation 完成后默认进入 `ready_for_merge_test`，不再停留在 `blocked` 或旧实现完成状态。
- [x] 实现：扩展 `TaskStatus`、`TaskPhase`、`AgentRunStatus` 和 `TaskStateMachine`，并移除旧兼容状态。
- **状态：** complete

### 阶段 12：P0-G 验证受限结构化恢复
- [x] 测试：任何 blocked/partial report 都必须包含 `reason`、`impact`、`recovery_action`、`fallback_evidence`。
- [x] 测试：格式化完成消息展示可执行恢复方案，而不只展示 blocked。
- [x] 实现：扩展 report schema、fallback report、prompt contract、diff guard violation 注入逻辑。
- **状态：** complete

### 阶段 13：P0 集成验证
- [x] 运行 focused tests：`rtk python3 -m unittest tests.test_gateway_trigger tests.test_orchestrator_run_flow tests.test_codex_cli_runner tests.test_state_machine`
- [x] 运行更广泛测试：`rtk python3 -m unittest discover -s tests`
- [x] 更新 `progress.md`、`findings.md`，输出修改文件、验证结果、剩余风险和下一步。
- **状态：** complete

### 阶段 23：ready_for_merge_test 语义收敛
- [x] 测试：`ready_for_merge_test` 中文标识为“等待手动执行 merge test”。
- [x] 测试：implementation 完成提示必须给出 `/coding merge-test <task_id>`。
- [x] 测试：TaskStatus 状态机允许 `ready_for_merge_test -> queued -> running -> done` 的人工 merge-test 流程。
- [x] 实现：更新中文状态、completion message、prompt contract、README 和技术方案中的状态流转描述。
- **状态：** complete

### 阶段 24：task 级 Codex session 复用
- [x] 测试：同一 task 的第二次 Codex run 在启动前的 `run-manifest.json` 已写入既有 `resume_session_id` / `attach_command`。
- [x] 测试：implementation 有 task 级 session 时使用增量 prompt，不再重复注入完整 LLM Wiki 和 plan summary。
- [x] 测试：Codex CLI runner 在非 merge-test 模式下也会根据 manifest 执行 `codex exec resume <session_id> -`。
- [x] 实现：首个 run 解析到 thread/session 后写入 `task_session.runner.resume_session_id`；后续 plan retry、implementation、bugfix、merge-test 统一复用。
- **状态：** complete

### 阶段 25：Codex prompt 中文化
- [x] 测试：完整 prompt 的标题、工作流字段、执行契约、必需输出说明改为中文。
- [x] 测试：增量 prompt 的 session 复用说明和本轮新增信息说明改为中文。
- [x] 测试：旧英文 prompt 标题不再出现在实际 prompt 生成路径。
- [x] 实现：保留 JSON 字段名、status code、命令和 skill 名英文，其他自然语言说明转为中文。
- **状态：** complete

### 阶段 26：首次 Codex prompt 极简化
- [x] 测试：首次 plan-only prompt 只包含目标、来源、相关上下文引用、执行要求和输出要求。
- [x] 测试：首次 prompt 不再包含当前阶段、工作目录、项目路径、测试命令、允许/禁止范围、完整工作流和 Wiki 正文。
- [x] 测试：首次 implementation prompt 引用已确认计划 artifact，不内联完整 plan 正文。
- [x] 实现：生成 run 级 context artifacts（context index、wiki context、confirmed plan 或 implementation context），prompt 只引用路径和短摘要。
- [x] 实现：保留增量 session 复用逻辑，并去掉增量 prompt 中的工作目录/当前阶段字段。
- [x] 验证：运行 prompt/orchestrator 定向测试、全量 unittest、`rtk git diff --check`，并重启 Hermes 验证插件加载。
- **状态：** complete

### 阶段 27：`task_52725d8d6ff5` 耗时分析
- [x] 分析 plan-only、implementation、bugfix、merge-test 各 run artifact、stdout command 数量和 report。
- [x] 确认历史慢点主要来自大 prompt、多 session、重复上下文读取、验证环境缺口、merge-test Git 冲突和缺少 timeline。
- [x] 将下一步优化收敛到已完成项之外，避免重复规划 session 复用和 prompt 极简化。
- **状态：** complete

### 阶段 28：Codex QA Run 编排
- [x] 测试：新增 `RunMode.QA = "qa"`，QA run 能复用当前 task 的 Codex session。
- [x] 测试：implementation 完成后自动进入 QA run，而不是直接 `ready_for_merge_test`。
- [x] 测试：QA run prompt 明确要求使用 `$qa` skill，优先 diff-aware mode，不发布、不部署、不 merge test。
- [x] 测试：QA run 结束后，`ready_for_merge_test`、`ready_for_merge_test_with_known_gaps`、`failed` 映射正确。
- [x] 实现：在 orchestrator 中新增 QA run 启动入口和 completion mapping。
- [x] 实现：新增 QA prompt wrapper，保持极简 artifact 引用，不重新塞完整上下文。
- [x] 实现：QA artifact 回收 `.gstack/qa-reports/qa-report-*.md`、`baseline.json`、`screenshots/`，并写入 run manifest / report 摘要。
- [x] 实现：`/coding status` 展示最近 QA report、QA health score、known gaps 和可执行恢复动作。
- **状态：** complete

### 阶段 29：QA 前 checkpoint commit 与 clean tree
- [x] 测试：implementation 完成后，QA run 启动前 source branch 有 checkpoint commit，working tree 为 clean。
- [x] 测试：checkpoint commit message 可追踪 task，例如 `Implement <task_id> before QA`。
- [x] 测试：QA 中 `$qa` 产生的 bugfix commit 不会与 implementation 首次提交混在一起。
- [x] 实现：implementation 完成且有允许范围内改动时，QA 前先提交 source branch checkpoint。
- [x] 实现：checkpoint 失败时不进入 QA，返回 `blocked` 并给出 `reason`、`impact`、`recovery_action`、`fallback_evidence`。
- [x] 实现：merge-test 不再承担“首次提交实现”的职责，只负责 merge/push 到 test。
- **状态：** complete

### 阶段 30：QA merge-test 可选证据 gate
- [x] 测试：`/coding merge-test <task_id>` 在没有 QA run 时仍允许继续，但必须提示“未发现自动 QA 证据”。
- [x] 测试：存在 QA run 时，tested commit 必须覆盖当前 source branch HEAD；QA 后有新 commit 时提示 QA 证据已过期。
- [x] 测试：存在 QA run 且 QA status 为 `ready_for_merge_test` 或 `ready_for_merge_test_with_known_gaps` 时，merge-test 可继续。
- [x] 测试：存在 QA run 且 QA status 为 `failed` / `runner_failed` / `blocked` 时，merge-test 不硬阻断，但必须展示失败摘要、影响和恢复动作，要求人工显式确认。
- [x] 测试：known gaps 可进入 merge-test，但必须展示缺口摘要并要求人工确认。
- [x] 实现：在 merge-test precheck 中可选读取 QA manifest/report 的 tested commit、health score、known gaps。
- [x] 实现：缺少 QA 时记录 `qa_evidence=missing` 并继续；QA 过期或 QA failed 时记录结构化风险和恢复动作。
- **状态：** complete

### 阶段 31：merge-test 成功后等待人工完成（P0 补充）
- [x] 测试：merge-test run 成功后 task status 进入 `merged_test`，phase 保持 `merged_test`，不直接 `done`。
- [x] 测试：`merged_test` 状态有中文标识，并允许由人工完成命令进入 `done`。
- [x] 测试：`/coding list` 会继续展示 `merged_test` task，因为它还未被人工标记完成。
- [x] 测试：`/coding complete <task_id>` 只允许完成 `merged_test` task；其他状态给出明确提示。
- [x] 实现：新增 `TaskStatus.MERGED_TEST`，更新状态机、merge-test run 映射、帮助文案、命令列表和人工完成记录。
- **状态：** complete

### 阶段 32：Run timeline 与 merge-test preflight（P1）
- [ ] 测试：每个 run 写入 `timeline.jsonl`，至少包含 run_started、prompt_ready、command_started、command_completed、report_written。
- [ ] 测试：merge-test preflight 能提前发现 test worktree 占用、source branch 未 push、远端 test 过期等问题。
- [ ] 实现：runner 记录关键 command duration，report/manifest 汇总耗时。
- [ ] 实现：merge-test 开始前输出明确阶段进度，减少长时间无感等待。
- **状态：** planned

### 阶段 33：`/coding list` 输出格式优化
- [x] 测试：列表从单行 `状态=... | id=...` 改为多行 `id:`、`状态:`、`项目:`、`任务描述:`。
- [x] 测试：Gateway/Coding Mode list 输出 `tip: 当前会话绑定：无;使用 /coding use <task_id> 切换当前任务。`。
- [x] 测试：长需求描述被压缩为一句话摘要，不直接输出编号列表或大段需求。
- [x] 实现：更新 `_format_task_list`、`_format_task_list_for_event` 和 list 描述摘要逻辑。
- **状态：** complete

### 阶段 34：`/coding change` 需求变更入口
- [x] 测试：`/coding change <反馈>` 出现在 `/coding help` 和 `/commands` 中。
- [x] 测试：Gateway 中 `/coding change <反馈>` 记录 `requirement_change`，进入 `plan_revision`，启动 plan-only，不启动 implementation。
- [x] 实现：新增 command dispatch、Gateway dispatch、active task 处理、需求变更记录和提示文案。
- [x] 实现：plan-only 增量 prompt 识别 `requirement_change`，要求先做变更影响分析和短计划，不直接实现。
- **状态：** complete

### 阶段 35：图片反馈传递给 Codex
- [x] 测试：`/coding bugfix` 带图片时，human decision 保存 media，增量 implementation prompt 输出自然语言图片附件说明。
- [x] 测试：`/coding change` 带图片时，`requirement_change` 保存 media，增量 plan-only prompt 输出自然语言图片附件说明。
- [x] 测试：反馈文本只有 `[Image]` 占位但 Hermes 没有拿到 media 时，不启动 Codex，并提示重发图片或图片链接。
- [x] 实现：在反馈记录中保存 `event.media_urls/media_types`，同步写入 requirement summary 和 LLM Wiki draft。
- [x] 实现：复用 task session 的增量 prompt 展示 `图片附件`、`media_type`、URL/路径，以及 Codex 无法访问图片时的恢复动作。
- **状态：** complete

### 阶段 36：Coding Mode LLM rewrite 实装
- [x] 测试：未发送“进入coding”时，自然语言不会进入 plugin，也不会调用 rewriter。
- [x] 测试：Coding Mode 中高置信度自然语言直接执行合法 `/coding <action>`，例如 task/list/bugfix/prepare。
- [x] 测试：低置信度或缺信息 rewrite 不执行任何 coding 操作，只提示人工二次确认。
- [x] 测试：`现在有多少个task` 通过 LLM rewrite 为 `/coding list` 后直接执行 list，不创建 task。
- [x] 测试：active task 下“查看最近对话记录，自然语言 rewrite 表现不符合预期”改写为 `/coding bugfix <反馈>`，高置信度时直接写入 implementation feedback 并启动 implementation。
- [x] 测试：destructive 或 LLM 显式 `needs_confirmation=true` 的高置信度候选仍需确认。
- [x] 实现：新增可注入 `command_rewriter`，默认运行时使用 Hermes auxiliary LLM 生成 JSON 候选命令。
- [x] 实现：高置信度直接把 canonical command 交给现有 `/coding` handler；需要确认时才保存 pending rewrite。
- [x] 实现：移除 Coding Mode 自然语言的 list/task/prepare 关键词直连分流，只保留进入/退出和确认/取消控制词。
- [x] 验证：运行 focused/full unittest、`git diff --check`，并重启 Hermes 验证插件加载。
- **状态：** complete

### 阶段 37：高置信度 rewrite 直接执行
- [x] 测试：高置信度 `/coding task` rewrite 直接创建 task 并启动 plan-only。
- [x] 测试：高置信度 `/coding list` rewrite 直接输出任务列表，不要求用户再回复“确认”。
- [x] 测试：active task 下高置信度 `/coding bugfix <反馈>` rewrite 直接写入 feedback 并启动 implementation。
- [x] 测试：高置信度 `/coding prepare-merge-test <task_id>` rewrite 直接进入等待 merge-test，不启动 implementation/merge-test run。
- [x] 测试：`needs_confirmation=true` 或 destructive 风险候选仍进入 pending 确认。
- [x] 实现：增加 `_rewrite_requires_confirmation`，仅对显式确认标记、`risk_level=destructive`、`delete/cancel` 保存 pending。
- [x] 实现：默认 rewriter prompt 改为高置信度完整信息输出 `needs_confirmation=false`。
- [x] 验证：运行 focused/full unittest、`git diff --check`，并重启 Hermes 验证插件加载。
- **状态：** complete

### 阶段 38：needs_human 项目补充回填
- [x] 测试：未知项目 task 进入 `needs_human` 后，用户补充“项目文件夹名称为 `xxx`”应回填 `project_path/source.project_name/task_session.project_name`。
- [x] 测试：补充的本地项目文件夹会沉淀为 LLM Wiki `project_profile`，中文项目名进入 aliases。
- [x] 测试：项目回填成功后自动启动 plan-only，避免用户补了项目仍无法继续。
- [x] 实现：`TaskLedger.update_project_context` 原子更新 task 项目结构化字段。
- [x] 实现：needs_human 的 `/coding continue` 重新解析项目；支持从反引号/“文件夹名称为”中提取本地项目目录，并在已知项目父目录与 `~/Desktop/project` 下定位。
- [x] 验证：focused/相关/full unittest、`git diff --check`，并重启 Hermes。
- **状态：** complete

### 阶段 39：Codex structured output schema 修复
- [x] 测试：`report.schema.json` 中每个 object 的 `properties` 必须完整等于 `required`，满足 strict structured output。
- [x] 测试：Codex stdout 出现 `invalid_json_schema` / `Invalid schema for response_format` 时归类为 `runner_failed`，不再普通 fallback 到 `completed_unstructured`。
- [x] 实现：将 top-level `qa_artifacts`、`tested_commit` 加入 required；`qa_artifacts` 内部 required 包含 `report`、`baseline`、`screenshots_dir`。
- [x] 实现：fallback/contract 补默认 `qa_artifacts` 和 `tested_commit`。
- [x] 实现：`runner_failed` 不写入可复用 Codex session，避免后续 run 复用失败 turn 的 session。
- [x] 实现：prompt 输出要求明确没有 QA 产物时填空字符串对象。
- [x] 验证：focused/full unittest、`git diff --check`。
- **状态：** complete

### 阶段 40：`/coding run` 即时 ACK 与防重复启动
- [x] 测试：Gateway 收到 `/coding run <task_id>` 后立即回复“已开始 plan-only”，并后台启动 run，不同步等待 Codex 完成。
- [x] 测试：task 已处于 `queued/running` 时，`/coding run` 不再重复启动，回复当前 active run 信息和恢复动作。
- [x] 实现：保留 `command_coding_run()` 的同步命令语义；仅调整 Gateway 显式命令分支。
- [x] 验证：focused/full unittest、`git diff --check`，并重启 Hermes。
- **状态：** complete

### 阶段 41：resume implementation/QA 写权限修复
- [x] 测试：复用 task session 的 implementation resume 命令包含 `sandbox_mode="workspace-write"`，不再继承 plan-only 只读沙箱。
- [x] 测试：QA resume 命令同样包含 `sandbox_mode="workspace-write"`，满足 `$qa` 产物和 bugfix 写入需求。
- [x] 测试：run-manifest 的 `resume_command` 展示可写 sandbox override，避免人工按旧命令续跑时仍只读。
- [x] 测试：已有 implementation 记录的 blocked task 可直接重试 `/coding implement <task_id>`。
- [x] 实现：`codex exec resume` 不支持 `--sandbox`，改用 `-c sandbox_mode="workspace-write"`；merge-test 保持 bypass。
- [x] 验证：focused/相关/full unittest、`git diff --check`。
- **状态：** complete

### 阶段 42：resume 子进程工作目录限定到任务 worktree
- [x] 测试：implementation resume 的 Codex 子进程从任务 `workspace_path` 启动，避免 apply_patch 把 Hermes agent 目录当作项目边界。
- [x] 测试：plan-only 子进程仍从 `project_path` 启动，保持只读规划上下文。
- [x] 实现：`CodexCliRunner.run()` 计算 `subprocess_cwd`；implementation/QA/merge-test 使用 worktree，plan-only 使用项目目录。
- [x] 实现：继续使用 `workspace-write`，不启用全盘 bypass；写权限由 Codex workspace-write + Hermes worktree/diff guard 双层限制在项目内。
- [x] 验证：focused/full unittest、`git diff --check`，并重启 Hermes。
- **状态：** complete

### 阶段 43：implementation/QA 受控高权限测试链路
- [x] 测试：plan-only 继续使用 read-only sandbox，不允许修改文件。
- [x] 测试：implementation 和 QA 的新 session / resume session 都使用 `--dangerously-bypass-approvals-and-sandbox`，从任务 `workspace_path` 启动，允许依赖安装、测试、浏览器 QA、git metadata 和 `$qa` 产物写入。
- [x] 测试：run-manifest 对 implementation/QA 记录 `dangerous_bypass=true`、权限原因、允许的项目外写入类型和“源码修改只限 workspace”的约束。
- [x] 测试：implementation/QA prompt 明确缺依赖时先安装并继续验证，安装或测试失败时输出结构化 `verification_limitations`。
- [x] 实现：只调整 Codex CLI runner、manifest 字段和 prompt contract，不引入独立测试执行器。
- [x] 实现：保留 Hermes diff guard；源码改动仍以 task worktree 为执行根，`.gstack/qa-reports` 作为 QA artifact 回收，越权项目 diff 继续 blocked。
- [x] 验证：focused runner/orchestrator/prompt tests、full unittest、`git diff --check`，并重启 Hermes。
- **状态：** complete

### 阶段 44：Codex visible session prompt 瘦身
- [x] 测试：首次 implementation/QA prompt 只包含本轮动作、必要上下文引用和 run instructions 路径，不内联插件状态机、权限清单、report 字段细节。
- [x] 测试：resume 增量 prompt 只包含 task、session、本轮 delta、简短动作和 run instructions 路径，不再重复输出完整执行契约。
- [x] 测试：每个 run 生成 `run-instructions.md` artifact，保存详细执行/报告契约，供 Codex 必要时读取，避免污染 visible session。
- [x] 实现：`PromptBuilder` 拆分 visible prompt 与 run instructions；`orchestrator` 写入 `run-instructions.md` 并传给 prompt。
- [x] 验证：focused prompt/orchestrator tests、full unittest、`git diff --check`，并重启 Hermes。
- **状态：** complete

### 阶段 45：分享 Demo 逻辑文档
- [x] 整理本轮对话中形成的 coding plugin 产品逻辑、命令体系、状态机、task/run/session 关系、prompt 策略、QA 链路和演示脚本。
- [x] 新建面向分享的 Markdown 文档，方便后续补截图和讲解。
- [x] 验证 Markdown 文件已创建，`git diff --check` 通过。
- **状态：** complete

### 阶段 46：`task_26603ef00507` 真实流程跟踪文档
- [x] 读取真实 task ledger、active binding、run manifest、input prompt、run instructions、report、summary、stdout/stderr 关键证据。
- [x] 新建真实 task 流程跟踪文档，覆盖飞书输入、项目补充、Coding Mode 绑定、plan-only run、Codex session、Figma 解析、plan 输出和下一步 demo 脚本。
- [x] 明确该文档替代泛化 demo 叙述，聚焦当前 task `task_26603ef00507`。
- **状态：** complete

### 阶段 47：`task_26603ef00507` Demo 文档精简
- [x] 将流程跟踪文档改成演示短版，只保留现场需要讲解的字段和证据。
- [x] 删除过细的 artifact 解释、完整计划步骤和实现预期细节，保留 task/session/Figma/plan/下一步命令。
- **状态：** complete

### 阶段 48：补充 LLM/Codex 步骤拆解
- [x] 在 demo trace 文档中补充按步骤拆解的 LLM rewrite、Hermes 编排、Codex 项目分析和 Figma 解析动作。
- [x] 保持文档精简，只新增演示时需要解释后台行为的关键步骤。
- **状态：** complete

### 阶段 49：补充 implementation 已启动后的真实步骤
- [x] 读取 `task_26603ef00507` 最新 ledger、run 列表、plan revision artifacts 和 active implementation run。
- [x] 将文档状态从 plan-ready 更新为 running/implementing，补充 workspace、source branch、active run 和 implementation 当前进展。
- [x] 补充需求变更、计划反馈、确认实现、Codex TDD/依赖安装/测试推进等未记录步骤。
- **状态：** complete

### 阶段 50：implementation 长时间无反馈诊断
- [x] 检查 `task_26603ef00507` ledger、active run、stdout/stderr、worktree diff 和本机进程。
- [x] 确认 Codex implementation 仍在运行，已完成部分代码、目标单测、typecheck 尝试和浏览器可达性检查。
- [x] 记录产品缺口：Hermes 未把 long-running run 的 stdout 进度主动反馈到飞书，需要后续补 heartbeat/progress/timeline。
- **状态：** complete

### 阶段 51：implementation timeout 被映射为 failed 的根因
- [x] 检查 `run_75079e08c896` manifest、ledger agent_runs、fallback `report.json`、stdout/stderr 和状态映射代码。
- [x] 确认 run 是 `timeout`：created_at `2026-05-27T02:48:21Z`，deadline_at `2026-05-27T03:48:21Z`，timeout_seconds `3600`。
- [x] 确认 task 变成 failed 的直接原因：`AgentRunStatus.TIMEOUT -> TaskStatus.FAILED`。
- [x] 确认提示文案不准确：fallback report 对 timeout 仍使用通用风险 `Structured report was not produced or failed schema validation.`。
- **状态：** complete

### 阶段 52：implementation timeout 修复与继续任务恢复
- [x] 测试：implementation 默认 timeout 从 3600 秒延长到 10800 秒，manifest 和 runner 入参一致。
- [x] 测试：implementation timeout 且有允许范围内代码改动时，不再进入 `failed`，而是进入 `ready_for_merge_test_with_known_gaps`。
- [x] 测试：implementation timeout 但没有任何代码改动时，进入 `runner_failed`，不再使用笼统 `failed`。
- [x] 测试：历史上因 timeout 标为 `failed` 的 task 可以继续 `/coding implement <task_id>`，并复用已有 workspace/session。
- [x] 测试：timeout fallback report 的风险和恢复动作使用 timeout 专用文案。
- [x] 实现：按 run mode 设置默认 timeout：plan-only 3600、implementation 10800、QA 10800、merge-test 5400。
- [x] 实现：`AgentRunStatus.TIMEOUT` 全局映射为 `runner_failed`；implementation/QA 若已有改动则状态归一为 `ready_for_merge_test_with_known_gaps`。
- [x] 验证：focused/相关/full unittest、`git diff --check`。
- **状态：** complete

### 阶段 53：半结构化 implementation report 容错恢复
- [x] 测试：Codex stdout 最后一条 agent_message 输出半结构化 JSON 时，Hermes 能补齐 `runner/mode/modified_files/test_commands/human_required/next_actions` 等 schema 字段。
- [x] 测试：`changed_files` 自动归一为 `modified_files`，`test_commands` 从 `test_results[].command` 派生。
- [x] 测试：implementation fallback 恢复摘要时，不再提示“确认计划后进入 implementation”。
- [x] 实现：`CodexCliRunner.load_or_build_report()` 在 fallback 前尝试从 raw report/stdout 恢复半结构化 report。
- [x] 恢复真实 `task_26603ef00507/run_8781c841e264`：report 和 ledger 更新为 `ready_for_merge_test_with_known_gaps` / `ready_to_merge_test`。
- [x] 验证：focused/相关/full unittest、`git diff --check`。
- **状态：** complete

### 阶段 54：Coding Mode 确认/续接链路重构
- [x] 测试：merge-test run 如果返回 `human_required=true`，Hermes 将其记录为会话级 pending action，用户回复“确定/继续/可以”时优先续接该动作，不调用 LLM rewrite。
- [x] 测试：没有 pending action 但当前 task 有 active run 时，确认词不会被 rewrite 成新的 coding 命令，也不会重复启动 implementation/merge-test。
- [x] 测试：最近一次 merge-test human_required 可作为兼容恢复信号，用户补充“未跟踪文件确定可以提交”时重试 merge-test，而不是创建 bugfix/implementation。
- [x] 测试：Gateway `/coding merge-test ... --confirm-qa-risk` 与自然语言确认走同一条异步启动路径。
- [x] 实现：新增会话级 pending action binding，优先级高于 pending rewrite 和 LLM rewrite。
- [x] 实现：merge-test 前由 Hermes checkpoint source worktree；Codex run instructions 明确不要在 session 中直接追问用户，需通过 `human_required` report 交回 Hermes。
- [x] 实现：merge-test human_required 不把 task 长期打成 blocked，而是保持可重试的 `ready_for_merge_test_with_known_gaps`。
- [x] 验证：focused/相关/full unittest、`git diff --check`。
- **状态：** complete

### 阶段 55：cancelled 终态保护
- [x] 测试：已 cancelled task 的 pending action 确认不会启动 merge-test，也不会进入 rewrite。
- [x] 测试：已 cancelled task 不能继续 `/coding run`、`/coding implement`、`/coding prepare-merge-test`、`/coding merge-test`。
- [x] 测试：active task 是 cancelled 时，`continue/change/bugfix` 只返回终态提示，不启动 Codex run。
- [x] 实现：在 Gateway、命令入口、pending action 和 `start_run()` 增加 cancelled gate。
- [x] 验证：focused/相关/full unittest、`git diff --check`。
- **状态：** complete

### 阶段 56：误取消 task 显式恢复
- [x] 测试：`/coding restore <task_id>` 只恢复 `cancelled` task，非 cancelled task 返回“不需要 restore”。
- [x] 测试：restore 根据最近 run 恢复到可操作状态，例如最近 merge-test 未完成时恢复到 `ready_for_merge_test_with_known_gaps`。
- [x] 测试：restore 清理 stale `active_run_id/active_mode`，但不自动启动 Codex。
- [x] 实现：新增 `/coding restore <task_id>`，作为唯一允许从 cancelled 恢复的显式动作。
- [x] 恢复真实 `task_26603ef00507`：`cancelled` -> `ready_for_merge_test_with_known_gaps` / `ready_to_merge_test`。
- [x] 验证：focused/相关/full unittest、`git diff --check`。
- **状态：** complete

### 阶段 57：飞书工作流分享文档更新
- [x] 将最新 Coding Mode rewrite、pending action、merge-test checkpoint、QA 可选证据、session/prompt 瘦身、restore 状态恢复补充到 `docs/feishu-workflow-update-20260526.md`。
- [x] 保持文档面向分享/demo，不写成代码实现细节清单，也不承诺未实现能力。
- [x] 验证 Markdown diff 和空白检查。
- **状态：** complete

### 阶段 58：飞书 Wiki/Doc 链接读取修复
- [x] 排查真实 `task_f9eae60e8f1a`：需求中的 `bestfulfill.feishu.cn/wiki/...` 被保存为普通文本，`source_context` 为空，Codex plan-only 兜底读取 `lark-cli docs +fetch` 时因 Hermes context 未绑定而 blocked。
- [x] 测试：`FeishuProjectReader` 能识别 `/wiki/` 和 `/docx/` 文档链接，并把 `lark-cli docs +fetch` 返回内容规范成 `feishu_wiki` / `feishu_docx` source context。
- [x] 历史测试：旧方案中文档读取失败会停在人工补充；阶段 78 已改为创建 task 时只索引来源。
- [x] 历史实现：旧方案曾在 source reader 中增加 Feishu Wiki/Doc reader；阶段 78 已从创建 task 主链路移除预读。
- [x] 实现：source refs 和 ledger source context 保存 `document_kind`、`document_token`、`document_id`、`revision_id`。
- [x] 验证：focused/相关/full unittest、`git diff --check`。
- **状态：** complete

### 阶段 59：implementation worktree 显式 base branch
- [x] 排查：真实项目当前停在 `test` 时，旧逻辑未显式传 base branch，`git worktree add -b <source_branch> <target>` 会从当前 HEAD 创建 source branch。
- [x] 测试：当项目工作区当前分支是 `test`，但 `main` 和 `test` 文件不同，implementation worktree 默认从 `main` 创建，不继承 `test` 文件。
- [x] 实现：新增 `source_base_branch` 任务/manifest 字段，implementation/QA/merge-test 记录该字段；implementation workspace 调用 `create_workspace(..., base_branch=...)`。
- [x] 策略：默认 base branch 为 `main`；如果 task session 或 source 显式配置 `source_base_branch/base_branch`，则优先使用配置值。
- [x] 验证：focused/相关/full unittest、`git diff --check`。
- **状态：** complete

### 阶段 60：implementation 完成后强制 checkpoint commit
- [x] 测试：implementation runner 改动源码后，Hermes 在 run 收尾阶段创建 `Implement <task_id> after implementation` checkpoint commit，并保证工作树 clean。
- [x] 实现：`RunManifest` 增加 `implementation_checkpoint`，implementation 收尾写入 manifest 和 agent run。
- [x] 策略：只有 implementation 归一为 `ready_for_merge_test` 或 `ready_for_merge_test_with_known_gaps` 且 diff guard 没有越权时才提交；提交失败则阻断后续 QA。
- [x] 保留：QA 前 checkpoint 与 merge-test 前 checkpoint 继续作为二次兜底。
- [x] 验证：focused/相关/full unittest、`git diff --check`。
- **状态：** complete

### 阶段 61：按阶段补齐权限 profile
- [x] 测试：plan-only 新 session 保持 read-only sandbox，只允许读取项目并输出计划。
- [x] 测试：plan-only resume session 同样保持 `sandbox_mode="read-only"` 和 `approval_policy="never"`。
- [x] 测试：plan-only 若异常修改项目文件，会被 diff guard 标记为 `blocked`。
- [x] 实现：`RunManifest` 增加 `permission_profile`，所有 run 写入当前权限 profile。
- [x] 实现：plan-only manifest 写入 `permission_profile=plan_read_only` 且 `dangerous_bypass=false`；外部飞书/Swagger 等上下文以来源索引、读取建议或 artifact 形式注入。
- [x] 实现：implementation/QA/merge-test 保持原受控高权限 profile，并继续由 task worktree、manifest/prompt 和 diff guard 收口。
- [x] 验证：focused/相关/full unittest、`git diff --check`。
- **状态：** complete

### 阶段 62：分享文档同步权限 profile
- [x] 更新 `docs/feishu-workflow-update-20260526.md`，把 plan-only `plan_read_only`、implementation/QA/merge-test 受控高权限和对应硬边界补充到分享文档。
- [x] 文档明确 `permission_profile` 会写入 run manifest，便于后续排查权限问题。
- [x] 验证：Markdown diff、`git diff --check` 和尾随空白检查。
- **状态：** complete

### 阶段 63：接入 Hermes autonomous Codex runner 后端
- [x] 排查：Hermes `autonomous-ai-agents/codex` 是 agent-facing skill，提供 terminal/process 使用约定，不是当前插件可直接调用的 Python API。
- [x] 测试：RunnerRouter 可选择 `hermes_autonomous_codex`，并读取 command/skill_path 配置。
- [x] 测试：`hermes_autonomous_codex` runner 会写入 backend metadata，标明当前仍是 direct Codex CLI 后端，可后续替换为 Hermes terminal/process。
- [x] 测试：orchestrator 将 `hermes_autonomous_codex` 视为 Codex session 型 runner，支持复用 thread/session、attach/resume command。
- [x] 实现：新增 `HermesAutonomousCodexRunner`，保留现有 report fallback、manifest、checkpoint、diff guard 和状态机。
- [x] 实现：新增 `RunnerName.HERMES_AUTONOMOUS_CODEX`，RunnerRouter 默认注册该 runner，可通过 `default_runner` 或 `--runner hermes_autonomous_codex` 使用。
- [x] 验证：focused/相关/full unittest、`git diff --check`。
- **状态：** complete

### 阶段 64：blocked task 人工放行 merge-test
- [x] 测试：`blocked` task 如果最近 implementation 有 source branch 和 worktree，可在风险评估后进入 merge-test 放行流程。
- [x] 测试：缺 report、缺 session、diff guard 越权、runner_failed/failed 或报告显示未落地代码时，默认不启动 merge-test，提示 `/coding merge-test <task_id> --accept-risk`。
- [x] 测试：人工 `--accept-risk` 后记录 `accepted_risk` 和 `blocked_merge_test_released`，再归一为 `ready_for_merge_test_with_known_gaps` 并继续 merge-test。
- [x] 测试：缺 implementation run、缺 source branch、缺 worktree 或 cancelled 仍不允许 merge-test。
- [x] 测试：Gateway 异步 `/coding merge-test` 对可放行 blocked 先记录 `blocked_merge_test_released`，再启动后台 merge-test。
- [x] 实现：新增 blocked merge-test assessment 和 release record；CLI/Gateway merge-test 共享同一套评估逻辑。
- [x] 实现：状态机允许 `blocked -> ready_for_merge_test_with_known_gaps`，但只能由 Hermes 风险评估后执行。
- [x] 验证：focused/相关/full unittest、`git diff --check`。
- **状态：** complete

### 阶段 65：blocked 风险接受快速放宽
- [x] 测试：缺 report、缺 Codex session 等 blocked 默认返回风险确认，不直接启动 merge-test。
- [x] 测试：`/coding merge-test <task_id> --accept-risk` 会记录 `accepted_risk` 并继续 merge-test。
- [x] 测试：Gateway 中 blocked 风险确认写入 pending action，用户回复“确认”会按 `--accept-risk` 继续。
- [x] 实现：硬阻断只保留缺 implementation run、缺 source branch、缺 worktree 或 cancelled；其他 blocked 风险允许人工接受。
- [x] 实现：缺 Codex session 时不再阻断 ready/known-gaps merge-test，可开启新 session 执行。
- [x] 验证：focused/相关/full unittest、`git diff --check`。
- [x] 验证：最终复跑相关/full unittest、`git diff --check`、尾随空白检查，并重启 Hermes Gateway 确认 `coding_orchestration enabled`。
- **状态：** complete

### 阶段 66：code review 问题修复
- [x] 修复：`command_rewriter.py` 和 `runners/hermes_autonomous_codex.py` 标记 intent-to-add，确保 base diff 包含新增模块。
- [x] 修复：plan-only 新 session 回到 `--sandbox read-only` + `approval_policy="never"`。
- [x] 修复：plan-only resume session 和 manifest `resume_command` 回到 `sandbox_mode="read-only"` + `approval_policy="never"`。
- [x] 修复：plan-only manifest 使用 `permission_profile=plan_read_only` 且 `dangerous_bypass=false`。
- [x] 修复：runner failed / checkpoint failed 兜底 report 补齐 `qa_artifacts` 和 `tested_commit`。
- [x] 文档：README、PLUGIN_USAGE、PLUGIN_TECHNICAL_SOLUTION、findings、progress 同步修正权限口径。
- [x] 验证：focused/相关/full unittest、`git diff --check`、尾随空白检查。
- **状态：** complete

### 阶段 67：通用 LLM Wiki 项目知识初始化
- [x] 测试：registry bootstrap 对存在的项目路径不只写极简 `project_profile`，还会沉淀项目指导合同、架构地图、开发约定、验证画像、工程工具画像、agent tooling、动态来源索引、历史计划索引和风险画像。
- [x] 测试：API/OpenAPI/Swagger 等动态来源只写 `external_source_index`，状态为 `candidate`，并标记 `read_before_use`，不把 endpoint/schema 正文沉淀为长期 verified 知识。
- [x] 测试：`.env*` 只记录为敏感入口/guarded path，不读取内容、不写入 source ref。
- [x] 测试：所有项目文件来源写入 `source_refs.path/sha256/mtime/size`，支持后续增量刷新和可追溯。
- [x] 实现：新增 `ProjectKnowledgeInitializer`，通用扫描 Markdown、contracts、工程配置、验证入口、`.codex/.agents/skills`、历史 plans 和动态外部来源。
- [x] 实现：`ProjectKnowledgeResolver.bootstrap_registry()` 对真实本地项目自动走增强初始化；路径不存在或初始化失败时保留原极简 profile 兜底。
- [x] 实现：人工补充项目文件夹时同样触发增强初始化，避免新项目只沉淀一个空 profile。
- [x] 验证：focused/相关/full unittest、真实 bps-admin 临时初始化、py_compile、尾随空白检查。
- **状态：** complete

### 阶段 68：Coding Mode enter/exit 重复回复防抖
- [x] 排查：日志显示 `进入coding` 实际命中 `coding_mode_entered`，不是正则误判；重复/串线风险来自 Gateway hook 内主动发送消息和平台事件重复分发。
- [x] 测试：相同 Gateway `message_id` 的 `进入coding` / `退出coding` 只处理一次，不重复发送回复。
- [x] 测试：重复发送新的 `进入coding` / `退出coding` 是幂等文案，已开启时提示“当前已在”，未开启时提示“当前未开启”，避免重复“已退出”。
- [x] 实现：在 `handle_gateway_event` 开头增加 5 分钟 message_id 防抖；enter/exit 文案按当前 mode 状态幂等输出。
- [x] 验证：focused/full unittest、py_compile、`git diff --check`、尾随空白检查，并重启 Hermes Gateway。
- **状态：** complete

### 阶段 69：Coding 插件重复加载根因修复
- [x] 排查：Hermes discovery 同时加载 canonical package 和历史 symlink，导致两个 `pre_gateway_dispatch` hook 同时主动回复。
- [x] 测试：重复调用 plugin `register()` 只注册一次 hook/command。
- [x] 实现：插件入口增加进程级注册 guard，注册失败时清理 guard 允许重试。
- [x] 验证：Hermes discovery 从 2 个 hook 收敛为 1 个 hook，并重启 Gateway。
- **状态：** complete

### 阶段 70：plan-only 非标准 runner status 归一化
- [x] 排查：Codex plan-only report 返回 `ready_for_implementation`，这是 task 语义，不是 `AgentRunStatus`，导致收尾状态映射抛 `ValueError`。
- [x] 测试：plan-only report 中 `ready_for_implementation` / `plan_ready` / `planned` 被归一为 `success`。
- [x] 实现：runner 边界在读取、修复和写回 `report.json` 前统一归一化 plan-only 状态。
- [x] 验证：真实 `task_d7bd20850ef5` 被恢复为 `planned/plan_ready`，相关 focused/full unittest 通过。
- **状态：** complete

### 阶段 71：runner status / task status 边界统一归一化
- [x] 排查：除 runner 边界外，orchestrator 收尾、report schema、partial structured recovery 和公共状态机 helper 都可能接触 Codex 返回的外部语义状态。
- [x] 测试：plan-only 的 `ready_for_implementation`、`ready_to_implement`、`plan_ready`、`planned` 统一归一为 `success`；merge-test 的 `merged_test`、`merge_test_complete`、`merge_test_completed` 统一归一为 `success`。
- [x] 测试：implementation 中出现 `planned` 等 task 语义状态时不会误判成功，而是归一为 `completed_unstructured`；公共状态机 helper 遇到未知 runner status 不再崩溃。
- [x] 实现：新增 `normalize_agent_run_status()`，在 runner、orchestrator 收尾、report 写回、schema enum 和状态机 helper 中统一使用。
- [x] 实现：prompt contract 明确 plan-only 成功必须返回 `status=success`，不要返回 Hermes 内部 task 状态。
- [x] 验证：状态扫描只剩合法 TaskStatus/TaskPhase 文档、测试断言和 prompt 禁止项；focused/full unittest、py_compile、`git diff --check` 通过。
- **状态：** complete

### 阶段 72：Coding Mode 低置信度 Hermes fallback
- [x] 测试：Coding Mode 中 LLM rewrite 低置信度时不发送插件二次确认、不创建 task、不启动 runner，而是把消息交给 Hermes 主 agent。
- [x] 测试：`intent=unknown` / `canonical_command=null` 时带插件上下文 handoff 给 Hermes 主 agent。
- [x] 测试：高置信度 destructive 候选仍保存 pending rewrite 并等待人工确认，不走 Hermes fallback。
- [x] 实现：在 rewrite rejection 分支返回 `pre_gateway_dispatch` 的 `rewrite` action，给 Hermes 主 agent 注入原话、拒绝原因、候选结果、active task 和 allowed commands。
- [x] 实现：补齐 command rewriter system prompt 的 `/coding restore <task_id>`，并明确非 coding 意图返回 unknown 交主 agent。
- [x] 验证：focused/full unittest、py_compile、`git diff --check`，并同步到 Hermes 实际插件目录后重启 Gateway。
- **状态：** complete

### 阶段 73：Project-First 与低置信度 Skill 化
- [x] 测试：新增 command catalog，覆盖 `/coding` 全量 action，并包含 `project list/init/use/status/clear`。
- [x] 测试：`/coding help`、`/commands`、rewriter prompt 和 handoff allowed commands 均从 catalog 生成。
- [x] 测试：`/coding project init <path>` 扫描项目并写入或刷新 LLM Wiki，绑定 active_project，不创建 task。
- [x] 测试：`/coding project list/use/status/clear` 正确读写当前会话 active_project。
- [x] 测试：active_project 存在时，Coding Mode 高置信度新需求可创建 task 并注入项目上下文。
- [x] 测试：低置信度 handoff 包含 recommended skill、active_project、known_projects 和 command catalog。
- [x] 测试：插件注册 `hermes-coding-operator` skill，skill 内容覆盖 project-first workflow 和“不默认使用插件仓库”的约束。
- [x] 实现：新增 `coding_orchestration/command_catalog.py`，作为命令单一事实源。
- [x] 实现：新增会话级 active_project binding，和 active task binding 分离，不写入 Task Ledger。
- [x] 实现：新增 plugin 内置 skill `coding_orchestration/skills/hermes-coding-operator/SKILL.md`，并在 plugin register 中注册。
- [x] 实现：扩展 handoff prompt，明确低置信度不创建 task、不启动 runner、不写 LLM Wiki。
- [x] 验证：全量 unittest、py_compile、`git diff --check`、尾随空白检查，并按需同步 Hermes 实际插件目录。
- **状态：** complete

### 阶段 74：上午聊天回溯与项目/状态建议修复
- [x] 回溯 2026-06-02 上午 Gateway 日志和 prod ledger，确认 `task_7802123463ab` 已收到 `bestvoy-admin` 项目补充但没有回写 `project_path`。
- [x] 测试：创建 task 时，需求文本里的“项目名称/文件夹名称/路径”能解析为本地项目并写入 task。
- [x] 测试：已有 active_project 时，对缺项目 task 执行 `/coding run <task_id>` 会先回填项目再启动 plan-only。
- [x] 测试：缺项目 task 收到 `/coding continue <项目补充>` 时记录为 human clarification，不再误归类为 plan_feedback。
- [x] 测试：低置信度 handoff 会给 active task 注入 phase 和可执行 next_step。
- [x] 实现：项目候选解析支持反引号 repo、文件夹名称、项目路径、普通“路径/目录”表达和 active_project 回填。
- [x] 实现：`hermes-coding-operator` skill 补齐 failed、runner_failed、blocked、plan_revision 的下一步建议。
- [x] 验证：相关测试、全量 unittest、`git diff --check`。
- **状态：** complete

### 阶段 75：飞书文档读取降阻（旧 Codex-owned 口径，已由阶段 81 替代；阶段 86 重新收敛为 Codex plan-owned）
- [x] 方案：飞书 Wiki/Doc/Docx 链接由 Hermes 记录来源索引；飞书权限失败不再让 task 进入 `needs_human`。
- [x] 测试：`lark-cli docs +fetch` 失败时，文档 source context 标记为 `codex_resolvable`，保留 URL/token/error/推荐命令。
- [x] 测试：带飞书 Wiki 链接的 `/coding task` 在项目已确定时仍创建 `planned` task 并自动 plan-only。
- [x] 测试：首次 plan prompt 展示外部来源上下文。（阶段 86 重新要求 Codex plan session 使用 `rtk lark-cli` 读取来源。）
- [x] 实现：更新 source reader、orchestrator、prompt/context-index 和文档口径。
- [x] 验证：focused/full unittest、py_compile、`git diff --check`。
- **状态：** complete

### 阶段 76：`/coding help` 参数展示完善
- [x] 测试：help/listing/rewriter prompt 均从 command catalog 展示必填参数。
- [x] 测试：`/coding task` 展示 `--project`、`--runner`、`--bug-of`、`--parent-task`。
- [x] 测试：`/coding merge-test` 展示 `--accept-risk`、`--confirm-qa-risk`。
- [x] 测试：`/coding delete` 展示 `--keep-artifacts`、`--keep-wiki`、`--force`。
- [x] 实现：command catalog 增加 `options` 字段，help/listing/rewriter 统一使用参数渲染。
- [x] 验证：focused/full unittest、py_compile、`git diff --check`，并重启 Hermes。
- **状态：** complete

### 阶段 77：Gateway 文档失败 context 归一与历史 task 修复
- [x] 测试：Gateway/adapter 返回 `read_status=failed`、`requires_human_context=true`、`docx:document:readonly` 时，归一为 Codex 可解析文档来源。
- [x] 测试：需求文本包含“文件夹名称为 bestvoy-admin”时，即使飞书文档权限失败，也能识别项目并自动 plan-only。
- [x] 测试：已有 `needs_human` 历史 task 在 `/coding run` / `start_run` 前自动修复项目和 source_context。
- [x] 实现：reader 与 orchestrator 双边界归一失败文档 context；Ledger 增加 source_context 更新能力；run 前自动修复历史 task。
- [x] 验证：focused/full unittest、py_compile、`git diff --check`，并重启 Hermes。
- **状态：** complete

### 阶段 78：移除创建 task 时的 FeishuProjectReader 预读环节
- [x] 测试：创建 task 时即使注入 `FeishuProjectReader`，也不会调用 `read_from_text`。
- [x] 测试：飞书 Project/Wiki/Docx 链接只写入 indexed source context，并继续启动 plan-only。
- [x] 实现：`CodingOrchestrator._read_source_context()` 只做链接索引，不再调用 reader/gateway 预读飞书正文。
- [x] 文档：README、PLUGIN_USAGE、PLUGIN_TECHNICAL_SOLUTION、findings、progress 曾统一为 Codex-owned 飞书读取口径；阶段 81 曾修正为 Hermes-first deferred，阶段 86 已重新收敛为 Codex plan-owned。
- [x] 验证：focused/full unittest、py_compile、`git diff --check`。
- **状态：** complete

### 阶段 79：外部 failed source context 创建 task 归一化
- [x] 排查：真实回复仍来自旧 `render_task_needs_source_context`，且实际加载目录 `/Users/xiaojing/.hermes/plugins/coding-orchestration-plugin/` 仍是旧 orchestrator。
- [x] 测试：当 Gateway/adapter 传入 `read_status=failed`、`requires_human_context=true`、`docx:document:readonly`，即使没有真实文档 URL，只要文本里有项目文件夹，也应创建 planned task。
- [x] 实现：`_create_task_from_text()` 开头对传入的 failed 文档 source context 做 Codex-owned 归一化。
- [x] 实现：`render_task_needs_source_context()` 删除旧 `FEISHU_PROJECT_PLUGIN_TOKEN` / `lark-cli --source hermes` 指引。
- [x] 验证：focused unittest、py_compile、全量 unittest、`git diff --check`。
- **状态：** complete

### 阶段 80：未提交变更汇总与提交前更新
- [x] 汇总：当前未提交 diff 涉及 18 个文件，约 1433 insertions / 184 deletions。
- [x] 汇总：核心变更包括 command catalog/help 参数展示、project-first active_project、低置信度 handoff operator skill、飞书来源 Codex-owned resolution、项目文件夹回填和历史 task 修复。
- [x] 汇总：实际 Hermes 插件目录已同步并重启 Gateway，避免运行旧 `FeishuProjectReader` 逻辑。
- [x] 验证：全量 unittest、py_compile、`git diff --check`、Gateway health。
- **状态：** complete

### 阶段 81：飞书来源读取从 Codex-owned 改为 Hermes-first deferred（历史口径，已由阶段 86 替代）
- [x] 排查：真实 `task_b859b49449e9` 中 Codex plan-only 无法稳定拿到 `lark-cli` 用户授权，导致需求文档无法读取并 blocked。
- [x] 测试：Gateway / Feishu reader 读取成功时，source context 合并 URL/token/source_type 并把正文摘要注入 plan。
- [x] 测试：Gateway / Feishu reader 读取失败、异常或无权限时，不阻断 task 创建；source context 标记 `deferred_source_resolution=true`、`resolution_owner=hermes_or_human`。
- [x] 实现：`_read_source_context()` 恢复非阻塞 reader 调用；成功优先注入，失败降级为索引和恢复动作。
- [x] 实现：plan-only prompt 不再要求 Codex session 自行绑定 `lark-cli`；缺正文时返回结构化 blocked，恢复动作指向 Hermes/Feishu 授权或人工粘贴正文。
- [x] 文档：README、PLUGIN_USAGE、PLUGIN_TECHNICAL_SOLUTION、findings、progress 同步新口径。
- [x] 验证：focused/full unittest、py_compile、`git diff --check`。
- **状态：** complete

### 阶段 82：lark-cli 调用收口到 Hermes source enrichment（历史口径，已由阶段 86 替代）
- [x] 测试：已有 deferred 飞书来源的 task 在 `/coding run` 前会重新 enrichment；reader 成功后更新 source context 和 requirement_summary，Codex prompt 使用注入正文。
- [x] 实现：`FeishuProjectReader` 默认通过 `rtk lark-cli docs +fetch ...` 兜底读取文档，避免裸 `lark-cli`。
- [x] 实现：`_repair_task_context_from_existing_task()` 对 failed/indexed/deferred 飞书来源执行非阻塞 preflight enrichment；成功清理 deferred 字段，失败继续保留恢复动作。
- [x] 文档：README、PLUGIN_USAGE、PLUGIN_TECHNICAL_SOLUTION 说明 `lark-cli` 位于 Hermes source enrichment 层，并在 plan 前重试。
- [x] 验证：focused/full unittest、py_compile、`git diff --check`。
- **状态：** complete

### 阶段 83：强制本地软链接与固定运行根
- [x] 排查：README、PLUGIN_USAGE、PLUGIN_TECHNICAL_SOLUTION 和文档测试仍保留 Git 安装副本、旧运行根和插件 update 口径。
- [x] 实现：`CodingOrchestrator._default_runtime_root()` 固定返回 `~/.hermes/coding-orchestration`，不再读取 `CODING_ORCHESTRATION_ROOT` 覆盖。
- [x] 实现：README、PLUGIN_USAGE、PLUGIN_TECHNICAL_SOLUTION 统一为本地软链接安装、当前仓库更新、重启 Gateway 生效。
- [x] 测试：文档测试断言软链接命令存在，旧 Git 安装命令和旧运行根不再出现在用户文档。
- [x] 验证：focused/full unittest、py_compile、`git diff --check`。
- [x] 运行态：清理或停用 `~/.hermes/plugins/` 下历史安装副本，确认只加载 `coding_orchestration` 软链接，并重启 Hermes Gateway。
- **状态：** complete

### 阶段 84：状态机与 Coding 流程图产出
- [x] 核对：当前 `TaskStatus`、`TaskStateMachine`、README/技术方案中的状态口径。
- [x] 产出：生成 `docs/coding-state-machine-flow-20260602.md`，包含整体 Coding 流程图、TaskStatus 状态机图、中文状态表和人工动作速查表。
- [x] 验证：`rtk git diff --check`。
- **状态：** complete

### 阶段 86：外部来源读取改为 Codex plan-owned + source-aware plan 高权限
- [x] 测试：创建 task 时只索引飞书 Project/Wiki/Docx 链接，不调用 `FeishuProjectReader.read_from_text()` 预读正文。
- [x] 测试：失败或 indexed 的飞书来源归一为 `codex_resolvable=true`、`deferred_source_resolution=true`、`resolution_owner=codex`，并保留 `lark_cli_command`。
- [x] 测试：带外部来源的 plan-only manifest 使用 `permission_profile=plan_source_read_elevated`、`dangerous_bypass=true`，resume command 同步带 bypass。
- [x] 测试：普通 plan-only 仍保持 `plan_read_only`，不使用 bypass。
- [x] 实现：`_read_source_context()` 改为先索引外部来源并直接返回 Codex-owned source context，不把 Hermes 飞书权限作为 task 创建 gate。
- [x] 实现：`_enrich_deferred_source_context_before_run()` 对 Codex-owned 来源不再重试 Hermes reader，避免再次卡在 Hermes 身份/scope。
- [x] 实现：Codex CLI runner 根据 `run-manifest.json.dangerous_bypass` 为 plan-only 新 session 和 resume session 开启受控高权限。
- [x] 实现：plan prompt 明确要求 Codex 使用 `lark_cli_command` 或等价 `rtk lark-cli` 读取来源；若失败必须结构化 blocked，并写 reason、impact、recovery_action、fallback_evidence。
- [x] 文档：README、PLUGIN_USAGE、PLUGIN_TECHNICAL_SOLUTION 同步普通 plan 和外部来源 plan 的权限边界。
- [x] 验证：focused/full unittest、`git diff --check`。
- **状态：** complete

### 阶段 87：queued 误报与飞书 URL 解析修复
- [x] 排查：最近 task `task_9e5c6e0676ec` 创建后显示 `queued`，但 run manifest 中 `pid=null`，stdout/report 显示 Hermes runtime 返回 `{"error": "Unknown tool: terminal"}`。
- [x] 排查：该 run 并非真实排队，而是 Hermes runtime dispatch 错误被误包装为 `queued`。
- [x] 排查：同一 task 的 Feishu Wiki URL 被中文分号后的“背景/目标”文本污染，导致 `lark_cli_command --doc` 不是纯 URL。
- [x] 测试：Hermes runtime 返回 `Unknown tool: terminal` 时，`HermesRuntime.start_command()` 返回 `ok=false`。
- [x] 测试：Codex runner 收到 runtime 启动失败时返回 `runner_failed`，不再写 `queued`。
- [x] 测试：Feishu Wiki/Docx 链接后跟中文标点和正文时，只提取纯链接。
- [x] 实现：`HermesRuntime.start_command()` 识别 dispatch 返回的 `error` / `ok=false`，并透传 reason/raw。
- [x] 实现：收紧 orchestrator 与 Feishu reader 的文档链接正则，排除中文逗号、句号、分号和顿号。
- [x] 验证：focused/full unittest、py_compile、`git diff --check`。
- **状态：** complete

### 阶段 89：终端 lark-cli 与 Hermes appId 一致性安装门禁
- [x] 测试：`coding_lark_preflight` 在终端默认 `lark-cli` appId 不等于 Hermes `FEISHU_APP_ID` 时返回 `app_mismatch`。
- [x] 测试：`coding_lark_preflight` 在 appId 一致且 scope 足够时返回 ok。
- [x] 测试：安装前置检查能从 Hermes `.env` 读取 `FEISHU_APP_ID`。
- [x] 实现：`SourceResolver.preflight_lark()` 增加 `rtk lark-cli config show` appId 一致性检查。
- [x] 实现：`scripts/install_symlink.py` 默认执行 appId 一致性 preflight；`--skip-preflight` 仅用于隔离测试。
- [x] 文档：README、PLUGIN_USAGE、PLUGIN_TECHNICAL_SOLUTION 写入“终端默认 `lark-cli` appId 必须等于 Hermes `FEISHU_APP_ID`”硬规范、修复命令和验收命令。
- [x] 验证：focused unittest、全量 unittest、安装脚本真实 preflight、`git diff --check`。
- **状态：** complete

### 阶段 90：Feishu 来源新需求 rewrite 阻断修复
- [x] 排查：Marketplace 需求仍被回复“未授权”，根因不是终端 `lark-cli` 不可用，而是 Coding Mode rewriter 把包含飞书/source/授权词的明确开发需求统一降级 handoff。
- [x] 实现：rewriter prompt 改为区分“纯授权/source 诊断”和“明确项目 + 明确开发需求 + 飞书来源链接”；后者高置信度生成 `/coding task <原需求> --project <项目>`。
- [x] 实现：`hermes-coding-operator` skill 同步新规则，低置信度 handoff 不再要求先授权或粘贴正文来阻止明确项目的新 task。
- [x] 测试：提示词不再包含旧 blanket handoff 规则，并包含 Codex plan 阶段使用 `rtk lark-cli` 读取来源的规则。
- [x] 测试：Coding Mode 中带 `bestvoy-admin` 和 Feishu Wiki 的 Marketplace 需求会创建 `source_deferred` task，不调用 Hermes 侧飞书预读 reader。
- [x] 验证：focused unittest、py_compile、全量 unittest、`git diff --check`。
- **状态：** complete

### 阶段 91：Plugin 使用前置准备清单
- [x] 文档：新增 `PLUGIN_PREREQUISITES.md`，整理使用 plugin 前必须准备的 Hermes `.env`、Codex CLI 绝对路径、`lark-cli` appId、飞书 user scope / bot 权限、项目 LLM Wiki、Kanban/Dashboard 和最小验收流程。
- [x] 本地草稿：`docs/deployment.md` 和 `docs/plugin-prerequisites.md` 也已收口为当前安装与快速验收口径，但 `docs/` 目录按仓库规则被 ignore，不作为正式版本化入口。
- [x] 文档：README、PLUGIN_USAGE、PLUGIN_TECHNICAL_SOLUTION 增加前置准备清单入口。
- [x] 测试：文档测试覆盖 `PLUGIN_PREREQUISITES.md` 的硬规范，并防止重新引入旧 Git 安装命令、旧仓库 SSH 检查和旧运行根环境变量赋值。
- [x] 验证：focused 文档测试、py_compile、`git diff --check` 和全量 unittest 通过。
- **状态：** complete

### 阶段 92：Hermes 组件卸载脚本
- [x] 实现：新增 `scripts/uninstall_legacy.py`，默认 dry-run，`--execute` 才删除。
- [x] 实现：卸载逻辑默认清理旧插件副本、旧 `coding-orchestration-prod/test` 运行根、当前软链接和当前运行根。
- [x] 保护：脚本不删除 `~/.hermes/.env`、Hermes auth、Codex auth 或 `lark-cli` 授权文件。
- [x] 保护：如果实际删除包含当前正式组件，必须输入 `确认卸载` 做二次确认。
- [x] 文档：README、PLUGIN_USAGE、PLUGIN_PREREQUISITES 增加卸载和清理旧组件命令。
- [x] 测试：新增卸载函数与脚本 dry-run 测试。
- [x] 验证：focused unittest、py_compile、`git diff --check`、全量 unittest 通过。
- **状态：** complete

### 阶段 93：安装脚本完整硬门禁
- [x] 实现：`run_install_preflight()` 从单一 lark app 检查升级为聚合检查，覆盖 Hermes `.env`、Hermes CLI/Gateway、Codex CLI 路径与能力、旧组件冲突、`lark-cli` app/scope。
- [x] 实现：安装脚本失败时逐项输出 check status、error 和 recovery_action。
- [x] 实现：安装门禁要求 `sheets:spreadsheet:read`，避免需求文档内嵌 Sheet 时安装后才暴露权限缺口。
- [x] 测试：新增完整成功、缺 env、旧组件冲突、缺 Sheet scope、脚本 dry-run 等回归。
- [x] 文档：README、PLUGIN_USAGE、PLUGIN_PREREQUISITES 改为“完整硬门禁”口径。
- [x] 验证：focused unittest、py_compile、`git diff --check`、全量 unittest 通过。
- **状态：** complete

### 阶段 94：安装后自动启用并重启 Hermes
- [x] 实现：`scripts/install_symlink.py` 在创建软链接后自动执行 `rtk hermes plugins enable coding_orchestration`。
- [x] 实现：插件启用成功后自动执行 `rtk hermes gateway restart`，让安装后的插件立即生效。
- [x] 兜底：启用或重启失败时输出 exit code、命令输出和手动恢复动作。
- [x] 测试：脚本入口测试使用环境变量替换真实 enable/restart 命令，并断言安装输出包含自动启用和自动重启。
- [x] 文档：README、PLUGIN_USAGE、PLUGIN_PREREQUISITES、PLUGIN_TECHNICAL_SOLUTION 改为“install 是完整安装入口”口径。
- [x] 验证：focused install/docs tests、py_compile、`git diff --check`、全量 unittest 通过。
- **状态：** complete

### 阶段 95：lark-cli needs_refresh 恢复动作修正
- [x] 排查：安装失败时 appId 已匹配，失败点是 `lark-cli user identity needs_refresh`，不是 Hermes app 配置错误。
- [x] 排查：当前 `lark-cli auth` 没有 `refresh` 子命令，旧恢复动作 `auth refresh/login` 不可直接执行。
- [x] 实现：needs_refresh 恢复动作改为重新执行 `rtk lark-cli auth login --scope ...`，并包含 Docx/Wiki/Sheet 读取 scope。
- [x] 实现：缺 scope 恢复动作按缺失项生成可执行 `auth login --scope` 命令。
- [x] 测试：source resolver 回归断言不再输出 `auth refresh`，并包含必要 scope。
- [x] 验证：focused source/install/docs tests、py_compile、`git diff --check`、全量 unittest 通过。
- **状态：** complete

### 阶段 96：解耦架构 presentation presenter 拆分
- [x] 实现：新增 `coding_orchestration/task_list_presenter.py`，承接 `/coding list` 任务摘要、项目标签和描述摘要。
- [x] 实现：新增 `coding_orchestration/run_completion_presenter.py`，承接 plan/implementation/QA/merge-test/stale run completion 消息、summary/risk/next_actions fallback。
- [x] 兼容：`CodingOrchestrator._format_task_list()`、`_task_project_label()`、`_task_description_label()`、`_format_*completion_message()` 和 `_completion_*()` 保留 wrapper，避免旧测试和外部调用断裂。
- [x] 测试：新增 presenter contract tests，并跑相关 completion/plan/implementation/gateway safety flow。
- [x] 治理：更新解耦设计、实施计划、项目地图、组件合同和约定；`orchestrator.py` 从 6534 行降至 6334 行，architecture guard 仍只 watch legacy orchestrator。
- **状态：** complete

### 阶段 97：解耦架构 task status presenter 拆分
- [x] 实现：新增 `coding_orchestration/task_status_presenter.py`，承接 `/coding status` 任务详情、Kanban 同步、完成回传、QA report、QA health score 和 known gaps 展示。
- [x] 兼容：`CodingOrchestrator._format_task_status_details()`、`_kanban_sync_status_display()`、`_completion_notification_status_display()`、`_latest_qa_run()`、`_read_report_json()` 和 `_qa_health_score_from_report_path()` 保留 wrapper，避免旧测试和内部调用断裂。
- [x] 测试：新增 `tests/test_task_status_presenter.py`，并跑 `tests.test_status_reconcile_flow` 相邻主流程测试。
- [x] 治理：更新解耦设计、实施计划、项目地图、组件合同和约定；`orchestrator.py` 从 6334 行降至 6244 行，architecture guard 仍只 watch legacy orchestrator。
- **状态：** complete

### 阶段 98：解耦架构 gateway rewrite presenter 拆分
- [x] 实现：新增 `coding_orchestration/gateway_rewrite_presenter.py`，承接 Coding Mode rewrite 确认、低置信度补充和 handoff 用户可见文案。
- [x] 兼容：`CodingOrchestrator._rewrite_confirmation_message()`、`_rewrite_needs_human_confirmation_message()`、`_rewrite_rejection_user_text()` 和 `_rewrite_handoff_to_hermes_message()` 保留 wrapper/上下文收集，避免旧测试和内部调用断裂。
- [x] 测试：新增 `tests/test_gateway_rewrite_presenter.py`，并跑 rewrite/pending confirmation/natural language command 相邻主流程测试。
- [x] 治理：更新解耦设计、实施计划、项目地图、组件合同和约定；`orchestrator.py` 从 6244 行降至 6171 行，architecture guard 仍只 watch legacy orchestrator。
- **状态：** complete

### 阶段 99：解耦架构 run start presenter 拆分
- [x] 实现：新增 `coding_orchestration/run_start_presenter.py`，承接 plan-only/implementation/QA 启动 ACK、active run 重复启动和 cannot-start 恢复提示。
- [x] 兼容：`CodingOrchestrator._implementation_started_message()`、`_qa_started_message()`、`_implementation_blocked_before_plan_ready_message()`、`_plan_only_started_message()`、`_plan_only_already_running_message()`、`_cannot_start_run_message()` 和 `_active_run_already_running_message()` 保留 wrapper，避免旧测试和内部调用断裂。
- [x] 测试：新增 `tests/test_run_start_presenter.py`，并跑 command run、plan run、QA flow 和 RunService 相邻主流程测试。
- [x] 治理：更新解耦设计、实施计划、项目地图、组件合同和约定；`orchestrator.py` 从 6171 行降至 6131 行，architecture guard 仍只 watch legacy orchestrator。
- **状态：** complete

### 阶段 100：解耦架构 feedback presenter 拆分
- [x] 实现：新增 `coding_orchestration/feedback_presenter.py`，承接 `/coding continue/change/bugfix` 反馈、需求变更、图片未捕获和人工澄清用户可见文案。
- [x] 兼容：`CodingOrchestrator._missing_feedback_media_message()`、`_plan_feedback_received_message()`、`_blocked_plan_feedback_received_message()`、`_requirement_change_received_message()`、`_requirement_change_queued_message()`、`_implementation_feedback_received_message()`、`_runtime_feedback_received_message()`、`_human_clarification_received_message()` 和 `_human_clarification_project_resolved_message()` 保留 wrapper，避免旧测试和内部调用断裂。
- [x] 测试：新增 `tests/test_feedback_presenter.py`，并跑 gateway feedback、change/continue、task control 和 natural language command 相邻主流程测试。
- [x] 治理：更新解耦设计、实施计划、项目地图、组件合同和约定；`orchestrator.py` 从 6131 行降至 6095 行，architecture guard 仍只 watch legacy orchestrator。
- **状态：** complete

### 阶段 101：解耦架构 merge-test presenter 拆分
- [x] 实现：新增 `coding_orchestration/merge_test_presenter.py`，承接 prepare/merge-test 状态提示、blocked 风险确认、风险放行说明、QA 风险确认和 merge-test 启动 ACK。
- [x] 兼容：`CodingOrchestrator._blocked_merge_test_risk_confirmation_message()`、`_blocked_merge_test_release_note()`、`_fallback_evidence_user_line()`、`_merge_test_qa_risk_confirmation_message()` 和 `_merge_test_started_message()` 保留 wrapper，避免旧测试和内部调用断裂。
- [x] 测试：新增 `tests/test_merge_test_presenter.py`，并跑 merge-test basic、blocked、QA gate、readiness 和 natural language command 相邻主流程测试。
- [x] 治理：更新解耦设计、实施计划、项目地图、组件合同和约定；`orchestrator.py` 从 6095 行降至 6056 行，architecture guard 仍只 watch legacy orchestrator。
- **状态：** complete

### 阶段 102：解耦架构后台 run 通知服务化
- [x] 实现：新增 `coding_orchestration/background_run_notifier.py`，承接后台线程启动、sender 调度、reply fallback、失败通知模板和 completion notification 记录构造。
- [x] 兼容：`CodingOrchestrator._start_background_*()`、`_run_*_and_notify()`、`_reply_if_possible()`、`_schedule_sender()`、`_call_sender()` 和 `_record_completion_notification()` 保留 wrapper/回调入口，避免旧测试和内部调用断裂。
- [x] 边界：`start_run()`、等待 run 完成、任务状态推进、merge-test pending action 和失败状态 transition 仍留在 orchestrator，不让通知服务承载业务决策。
- [x] 测试：新增 `tests/test_background_run_notifier.py`，并跑 plan run、QA flow、merge-test QA gate 和 command run 相邻主流程测试。
- [x] 治理：更新解耦设计、实施计划、项目地图、组件合同和约定；`orchestrator.py` 从 6056 行降至 6003 行，architecture guard 仍只 watch legacy orchestrator。
- **状态：** complete

### 阶段 103：解耦架构 gateway binding service 拆分
- [x] 实现：新增 `coding_orchestration/gateway_binding_service.py`，承接 gateway event source、binding key、active task、coding mode、active project、pending rewrite 和 pending action 的存取。
- [x] 兼容：`CodingOrchestrator._event_source_for_ledger()`、`_binding_key_for_event()`、`_active_task_id_for_event()`、`active_task_for_session()`、`_coding_mode_*()`、`_active_project_*()`、`_pending_rewrite_*()` 和 `_pending_action_*()` 保留 wrapper，避免旧测试和内部调用断裂。
- [x] 边界：pending action 的确认后命令执行、cancelled task gate、active project 应用到 task、rewrite 上下文组装仍留在 orchestrator，binding service 只负责会话绑定存取和过期 binding 清理。
- [x] 测试：新增 `tests/test_gateway_binding_service.py`，并跑 coding mode、pending confirmation、active project/task、rewrite 和 natural language command 相邻主流程测试。
- [x] 治理：更新解耦设计、实施计划、项目地图、组件合同和约定；`orchestrator.py` 从 6003 行降至 5843 行，architecture guard 仍只 watch legacy orchestrator。
- **状态：** complete

### 阶段 104：解耦架构全线阶段与长期职责固化
- [x] 梳理：确认设计文档已有 0-17 全线阶段、阶段责任矩阵、阶段执行合同和长期职责模型。
- [x] 实施计划：补充 Task 28-36 长期执行队列，覆盖 workspace/git/diff checkpoint service、Command/Gateway controller、Run orchestration service、SourcePort 消费闭环、Tool/MCP dispatcher、Skill 零耦合复查、orchestrator façade 降载、legacy test final cleanup 和 release readiness。
- [x] 职责：明确每个后续任务的主责域、覆盖设计阶段、状态和退出标准，避免后续新能力重新堆回 `orchestrator.py`。
- [x] 验证：运行文档/架构检查、architecture guard、空白检查和敏感值扫描；只剩 `orchestrator.py` 已登记 legacy large-file watch。
- **状态：** complete

### 阶段 105：解耦架构 workspace checkpoint service 拆分
- [x] 实现：新增 `coding_orchestration/workspace_checkpoint_service.py`，承接 implementation workspace 复用/创建、source branch/base branch、QA artifact 收集、clean-tree checkpoint、git HEAD 和 diff guard QA artifact 过滤。
- [x] 兼容：`CodingOrchestrator._implementation_workspace()`、`_merge_test_workspace()`、`_workspace_clean_checkpoint()`、`_git_head()`、`_source_branch_for_task()`、`_source_base_branch_for_task()` 和 `_collect_qa_artifacts()` 保留 wrapper，避免旧调用断裂。
- [x] 测试迁移：新增 `tests/test_workspace_checkpoint_service.py`，并把纯 source branch helper 私有测试从 `tests/test_implementation_workspace_flow.py` 迁到 service contract tests。
- [x] 边界：runner 启动、状态映射、diff guard violation 到 report/status 的风险注入仍留在 orchestrator，workspace service 不承载业务状态推进。
- [x] 治理：更新解耦设计、实施计划、项目地图、组件合同和约定，并运行聚焦测试、完整单测、architecture guard、空白检查和敏感扫描。
- **状态：** complete

### 阶段 106：解耦架构 run manifest service 拆分
- [x] 实现：新增 `coding_orchestration/run_manifest_service.py`，承接 run-manifest 基础字段、artifact record、Codex attach/resume 展示命令、controlled bypass 权限 profile、source elevated plan 权限判断和 manifest session metadata 字段投影。
- [x] 兼容：当时 `CodingOrchestrator._build_manifest()`、`_artifact_record()`、`_codex_attach_command()`、`_codex_resume_command()`、`_permission_profile()`、`_run_uses_controlled_bypass()` 和 `_update_manifest_session_metadata()` 保留 wrapper，避免旧调用断裂；阶段 157 已删除无调用的 permission/bypass wrapper。
- [x] 测试迁移：新增 `tests/test_run_manifest_service.py`，并把 plan-only resume command 私有 helper 测试从 `tests/test_orchestrator_run_flow.py` 迁到 service contract tests。
- [x] 边界：runner 启动、状态映射、diff guard violation 到 report/status 的风险注入仍留在 orchestrator，run manifest service 不承载业务状态推进或 subprocess 执行。
- [x] 治理：更新解耦设计、实施计划、项目地图、组件合同和约定，并运行聚焦测试、architecture guard、空白检查和敏感扫描。
- **状态：** complete

### 阶段 107：解耦架构 gateway command controller 第一切片
- [x] 实现：新增 `coding_orchestration/gateway_command_controller.py`，承接 `/coding` 命令归一化、project 子命令映射、确认/取消词分类、rewrite 风险确认、plugin-generated message 过滤、Gateway event dedupe key/cache 和授权探测。
- [x] 兼容：`CodingOrchestrator._normalize_coding_gateway_command()`、`_rewrite_requires_confirmation()`、`_is_*confirmation*()`、`_looks_like_*()`、`_dedupe_gateway_event()`、`_gateway_event_dedupe_key()` 和 `_gateway_user_is_authorized()` 保留 wrapper，避免旧调用断裂。
- [x] 测试：新增 `tests/test_gateway_command_controller.py`，覆盖 command alias、project 子命令、确认/取消分类、风险确认、dedupe、授权兜底和 wrapper 兼容。
- [x] 边界：`_handle_explicit_gateway_command()` 大分发、ledger/runner 副作用、状态 gate 和消息回复仍留在 orchestrator；后续 Task 29 继续按命令分发职责拆迁。
- [x] 治理：更新解耦设计、实施计划、项目地图、组件合同和约定；运行 controller/相邻 Gateway flow、文档/架构、完整单测、空白检查和敏感扫描；`orchestrator.py` 从 5600 行降至 5486 行，architecture guard 仍只 watch legacy orchestrator。
- **状态：** complete

### 阶段 108：解耦架构 gateway command controller 第二切片
- [x] 实现：`gateway_command_controller.py` 新增显式 `/coding` / `/commands` 解析、merge-test 参数解析和 rewrite canonical command 规则。
- [x] 兼容：`CodingOrchestrator._handle_explicit_gateway_command()`、`_handle_commands_gateway_command()`、`command_coding_merge_test()` 和 `_canonical_rewrite_command()` 委托 controller 纯解析；命令执行、状态 gate、pending action、ledger/runner 副作用仍留在 orchestrator。
- [x] 测试：扩展 `tests/test_gateway_command_controller.py`，覆盖显式命令解析、`/commands` 参数、merge-test flag/task fallback、rewrite canonical command 和 wrapper 兼容。
- [x] 边界：本切片仍不把 `_handle_explicit_gateway_command()` 大分发表整体搬出；下一步可抽命令分发 plan/route table，再按 handler 逐步迁移。
- [x] 治理：更新解耦设计、实施计划、项目地图、组件合同和约定；`orchestrator.py` 从 5486 行降至 5447 行，architecture guard 仍只 watch legacy orchestrator。
- **状态：** complete

### 阶段 109：解耦架构全线阶段技术方案固化
- [x] 方案：在 `PLUGIN_TECHNICAL_SOLUTION.md` 新增“解耦改造工作阶段全线图”，面向团队评审列出 A-D 四个批次、0-17 全线阶段、Task 28-36 长期执行队列、职责归属和退出标准。
- [x] 治理：明确大文件与 hard code 是专项治理对象，`orchestrator.py` 先降到 3000 行以内，再退出 legacy large-file watchlist；新增业务模块超过 600 行需说明边界，超过 1000 行必须拆分或登记例外。
- [x] 职责：再次固化 core/service/tool 层不得新增 Hermes 命令、`lark-cli`、`Path.home()`、`os.getenv()`、`subprocess`、token key 或真实 secret 模式；hard code 只允许落在 config、adapter binding、domain policy 或明确 fixture。
- [x] 验证：本阶段为文档方案固化，执行 `git diff --check`、文档/架构测试、architecture guard 和敏感扫描。
- **状态：** complete

### 阶段 110：解耦架构 gateway command controller 第三切片
- [x] 实现：`gateway_command_controller.py` 新增 `GatewayCommandRoute`、`route_coding_gateway_command()` 和 `gateway_route_task_id()`，集中维护命令族、task id 来源策略和 pending action 清理元数据。
- [x] 兼容：`CodingOrchestrator._handle_explicit_gateway_command()` 改为消费 route plan；具体命令执行、状态 gate、pending action、ledger/runner 副作用和消息回复仍留在 orchestrator。
- [x] 测试：扩展 `tests/test_gateway_command_controller.py`，覆盖 project route、active task fallback route、merge-test flags/active fallback route 和 task id 解析。
- [x] 治理：更新解耦设计、实施计划、项目地图、组件合同和约定；记录 `gateway_command_controller.py` 为 348 行，`orchestrator.py` 当前 5458 行，下一步继续按 route family 收敛 `_handle_explicit_gateway_command()` 大分支。
- **状态：** complete

### 阶段 111：解耦架构 gateway command controller 第四切片
- [x] 实现：`gateway_command_controller.py` 扩展 route metadata，新增 handler key 与 reply mode，明确哪些命令属于 immediate reply，哪些仍走 custom complex dispatch。
- [x] 兼容：`CodingOrchestrator._handle_explicit_gateway_command()` 新增 `_handle_gateway_immediate_route()`，集中处理 help、diagnostic、list、project、use、exit、status、complete、cancel、restore 和 delete；task/run/implement/QA/prepare/merge-test 等复杂副作用仍留在原分支。
- [x] 行为修正：Gateway 层 `/coding lark-preflight` 与 `/coding source-resolve <url>` 现在会被插件诊断分支截获并回复，不再因缺显式分支落回 Hermes 主 agent。
- [x] 测试：扩展 `tests/test_gateway_command_controller.py` 与 `tests/test_gateway_command_group_flow.py`，覆盖 route handler/reply metadata 和 diagnostic immediate reply。
- [x] 验证：相邻 Gateway/command/merge-test 回归 73 tests passed；完整单测 639 tests passed；`architecture_guard.py` passed，仅 watch `orchestrator.py: 5457 lines`；`git diff --check` passed；敏感扫描无命中。
- [x] 边界：Task 29 仍是 In Progress；复杂命令 handler 副作用、pending action 执行、active project/task 应用和 runner/ledger 状态推进尚未迁出 orchestrator。
- **状态：** complete

### 阶段 112：解耦架构 gateway command executor 第五切片
- [x] 实现：新增 `coding_orchestration/gateway_command_executor.py`，作为 Gateway custom route 的 host shell helper，消费 controller route metadata。
- [x] 迁移：将 task creation、feedback、plan run、delivery、implementation、QA、prepare merge-test 和 merge-test 的 custom route 分发从 `CodingOrchestrator._handle_explicit_gateway_command()` 迁出。
- [x] 兼容：`CodingOrchestrator._handle_explicit_gateway_command()` 现在只保留 route parsing、pending action 清理、immediate dispatch 和 executor 委托；ledger/runner/status/pending action 副作用仍通过 orchestrator façade/callback 调用，不塞进纯 controller。
- [x] 测试：新增 `tests/test_gateway_command_executor.py`，覆盖 immediate route 不处理、plan run active task fallback 和 delivery route handler key 分发；相邻 Gateway/command/merge-test flow 继续保护主流程。
- [x] 治理：`orchestrator.py` 从 5457 行降至 5283 行；新增 executor 230 行，低于大文件 watch；Task 29 仍是 In Progress，pending action 路由、active context 应用和 run orchestration 副作用还未完全迁出。
- [x] 验证：相邻 Gateway/command/merge-test 回归 76 tests passed；完整单测 642 tests passed；`architecture_guard.py` passed，仅 watch `orchestrator.py: 5283 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 113：解耦架构全线阶段责任矩阵补强
- [x] 方案：在 `PLUGIN_TECHNICAL_SOLUTION.md` 的“解耦改造工作阶段全线图”中补充阶段责任矩阵，覆盖 0-17 阶段的主责、协作和长期沉淀。
- [x] 合同：补充阶段执行合同，明确每轮只迁移一个职责域、先补 contract/main-flow tests、orchestrator 只做 façade、core/service/tool 层不得新增 host/hard-code 细节。
- [x] 治理：保持 Task 28-36 长期队列不变，继续把大文件和 hard code 作为专项治理对象；本阶段只补文档，不改运行行为。
- [x] 验证：`git diff --check` passed；文档/架构相关测试 17 tests passed；`architecture_guard.py` passed，仅 watch `orchestrator.py: 5283 lines`；敏感扫描无命中。
- **状态：** complete

### 阶段 114：解耦架构 gateway pending action executor 第六切片
- [x] 实现：新增 `coding_orchestration/gateway_pending_action_executor.py`，作为 Gateway pending action 的 host shell helper。
- [x] 迁移：将 pending action 确认/取消、latest human_required merge-test fallback、取消任务 gate 和确认后显式命令续接从 `CodingOrchestrator._handle_pending_action_gateway_message()` 迁出。
- [x] 兼容：`CodingOrchestrator._handle_pending_action_gateway_message()` 和 `_pending_action_from_latest_human_required_run()` 保留 wrapper，仍通过 orchestrator façade/callback 调用 binding、ledger、消息回复和显式命令执行；controller 继续只做纯解析/分类。
- [x] 测试：新增 `tests/test_gateway_pending_action_executor.py`，覆盖绑定确认、取消、latest human_required fallback 和失效候选命令提示；相邻 pending/rewrite/cancel/merge-test flow 继续保护主流程。
- [x] 验证：聚焦 pending/rewrite/cancel/merge-test 回归 46 tests passed；完整单测 646 tests passed；`architecture_guard.py` passed，仅 watch `orchestrator.py: 5238 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 115：解耦架构 gateway active context helper 第七切片
- [x] 实现：新增 `coding_orchestration/gateway_active_context.py`，作为 Gateway active context 的 host helper。
- [x] 迁移：将 active project 应用到缺项目 task 的 project context 回填和 human decision 记录从 `CodingOrchestrator._apply_active_project_to_task_if_missing()` 迁出。
- [x] 兼容：`CodingOrchestrator._apply_active_project_to_task_if_missing()` 保留 wrapper；active project binding 存取仍归属 `gateway_binding_service.py`，项目初始化和项目画像生成不迁入该 helper。
- [x] 测试：新增 `tests/test_gateway_active_context.py`，覆盖 active project 回填、已有 project_path 不覆盖、无 active project 不改 task；相邻 active project / natural language / command run flow 继续保护主流程。
- [x] 验证：聚焦 active project / natural language / command run 回归 25 tests passed；完整单测 649 tests passed；`architecture_guard.py` passed，仅 watch `orchestrator.py: 5212 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 116：解耦架构 run orchestration service 第一切片
- [x] 实现：新增 `coding_orchestration/run_orchestration_service.py`，作为 Run orchestration 迁移期 application helper。
- [x] 迁移：将后台 queued/running 等待完成、后台启动失败状态收敛、merge-test `human_required` 转会话级 pending action 从 `CodingOrchestrator` 迁出。
- [x] 兼容：`CodingOrchestrator._wait_for_background_run_completion()`、`_mark_background_run_failed()` 和 `_store_pending_action_from_merge_test_result()` 保留 wrapper；`start_run()`、runner 启动、report 写回、diff guard 和完整 run result 映射仍留在 orchestrator，后续 Task 30 继续迁。
- [x] 测试：新增 `tests/test_run_orchestration_service.py`，覆盖等待完成 reconcile、stale active run、后台失败 transition、终态保护、transition rejected decision 记录、merge-test 非人工确认忽略和 QA 风险 pending action flag。
- [x] 文档：同步 `docs/project-map.md`、`docs/conventions.md`、`docs/component-contract.md`、`contracts/project-context.yaml`、`docs/plans/2026-06-16-decoupled-architecture-design.md`、`docs/plans/2026-06-16-decoupled-architecture-implementation.md`、`PLUGIN_TECHNICAL_SOLUTION.md` 和 `findings.md`。
- [x] 治理：`orchestrator.py` 从 5212 行降至 5154 行；新增 helper 99 行、测试 171 行，均低于大文件阈值。
- [x] 验证：新增 helper tests 7 tests passed；相邻 run/QA/merge-test 回归 41 tests passed；完整单测 656 tests passed；`architecture_guard.py` passed，仅 watch `orchestrator.py: 5154 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 117：解耦架构 run completion projection 第二切片
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `RunCompletionProjection` 和 `project_run_completion()`。
- [x] 迁移：将 run completion 后的 task status、task phase、run_still_active 和 report `run_status/status/task_status` 字段投影从 `CodingOrchestrator.start_run()` 迁出。
- [x] 兼容：新 helper 复用 `RunService.task_status_for_run_result()` 与 `RunService.task_phase_for_run_result()`；保留 running override 和 merge-test `human_required` 回到 `ready_for_merge_test` 的人工续接语义；orchestrator 继续负责 report 写回、ledger transition、artifact/agent_run append 和 session metadata 更新。
- [x] 测试：扩展 `tests/test_run_orchestration_service.py`，覆盖 plan success 映射、running phase 保留、merge-test `human_required` 可重试、failed merge-test 不因 human_required 被放行。
- [x] 文档：同步 `docs/project-map.md`、`docs/conventions.md`、`docs/component-contract.md`、`contracts/project-context.yaml`、`docs/plans/2026-06-16-decoupled-architecture-design.md`、`docs/plans/2026-06-16-decoupled-architecture-implementation.md`、`PLUGIN_TECHNICAL_SOLUTION.md` 和 `findings.md`。
- [x] 治理：`orchestrator.py` 从 5154 行降至 5149 行；`run_orchestration_service.py` 当前 151 行、测试 227 行，均低于大文件阈值。
- [x] 验证：新增/相邻 run/status/QA/merge-test 回归 50 tests passed；后续完整验证见 `progress.md`。
- **状态：** complete

### 阶段 118：解耦架构 agent run record 构造第三切片
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `build_agent_run_record()`。
- [x] 迁移：将 `CodingOrchestrator.start_run()` 中 agent run record 的纯数据构造迁出；orchestrator 仍负责 artifact append、agent_run append、merge record、session metadata 和 summary/writeback。
- [x] 兼容：helper 保留 plan-only 不写 source/target/implementation checkpoint、implementation 保留 source branch/checkpoint、merge-test 写 target branch/stale completion/diff guard 的既有字段合同。
- [x] 测试：扩展 `tests/test_run_orchestration_service.py`，覆盖 plan-only record、implementation record 和 merge-test target/stale completion record。
- [x] 文档：同步 `docs/project-map.md`、`docs/conventions.md`、`docs/component-contract.md`、`contracts/project-context.yaml`、`docs/plans/2026-06-16-decoupled-architecture-design.md`、`docs/plans/2026-06-16-decoupled-architecture-implementation.md`、`PLUGIN_TECHNICAL_SOLUTION.md` 和 `findings.md`。
- [x] 治理：`orchestrator.py` 从 5149 行降至 5143 行；`run_orchestration_service.py` 当前 195 行、测试 310 行，均低于大文件阈值。
- [x] 验证：新增 helper tests 14 tests passed；相邻 run/status/QA/merge-test 回归 53 tests passed；后续完整验证见 `progress.md`。
- **状态：** complete

### 阶段 119：解耦架构长期阶段操作模型补强
- [x] 方案：在 `PLUGIN_TECHNICAL_SOLUTION.md` 的全线阶段图后补充长期迭代操作模型，明确定域、建基线、先测、façade 迁移、旧耦合处理、文档同步和治理回流七步闭环。
- [x] 执行计划：在 `docs/plans/2026-06-16-decoupled-architecture-implementation.md` 补充长期迭代操作模型和硬性职责归属规则，确保 Task 30 以后仍按职责域推进。
- [x] 职责：明确 controller、run orchestration helper、background notifier、services、adapter、presenter/binding skill 的边界，避免后续把状态推进、subprocess、host 文案或 hard code 写回错误层。
- [x] 验证：`git diff --check` passed；文档/架构测试 17 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 5143 lines`；敏感扫描无命中。
- **状态：** complete

### 阶段 120：解耦架构 runner session update 构造第四切片
- [x] TDD：先在 `tests/test_run_orchestration_service.py` 增加 runner session update 合同测试，并确认 helper 缺失导致 3 个预期失败。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `build_runner_session_update()`，统一维护 completed/reconciled run 的 runner session update 纯数据构造。
- [x] 迁移：`CodingOrchestrator.start_run()` 和 `_reconcile_completed_active_run()` 改为消费 helper；orchestrator 继续负责 ledger update、attach command 字符串生成、summary 和 writeback。
- [x] 兼容：helper 保持 completed 时清理 active run、保留可恢复 session、runner_failed 时清空 session、still-running 时不覆盖 active run 字段的既有语义。
- [x] 文档：同步项目地图、约定、组件合同、machine-readable project context、解耦设计、实施计划和技术方案。
- [x] 验证：新增 helper tests 17 tests passed；相邻 run/status/QA/merge-test 回归 56 tests passed；完整单测 666 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 5129 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 121：解耦架构 merge-test run record 构造第五切片
- [x] TDD：先在 `tests/test_run_orchestration_service.py` 增加 merge-test run record 合同测试，并确认 helper 缺失导致 1 个预期失败。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `build_merge_test_run_record()`。
- [x] 迁移：`CodingOrchestrator.start_run()` 中 merge-test run record 的纯数据构造改为消费 helper；orchestrator 继续负责 stale completion gate、ledger append 和 created_at 时间注入。
- [x] 文档：同步项目地图、约定、组件合同、machine-readable project context、解耦设计、实施计划和技术方案。
- [x] 验证：新增 helper tests 18 tests passed；相邻 run/status/QA/merge-test 回归 57 tests passed；完整单测 667 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 5127 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 122：解耦架构 start_run result payload 构造第六切片
- [x] TDD：先在 `tests/test_run_orchestration_service.py` 增加 start_run final result payload 合同测试，并确认 helper 缺失导致 2 个预期失败。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `build_start_run_result_payload()`。
- [x] 迁移：`CodingOrchestrator.start_run()` 尾部 final return payload 改为消费 helper；orchestrator 继续负责 project writeback、summary 写入、ledger append/update、runner 启动和 report 写回副作用。
- [x] 文档：同步项目地图、约定、组件合同、machine-readable project context、解耦设计、实施计划和技术方案。
- [x] 验证：新增 helper tests 20 tests passed；相邻 run/status/QA/merge-test 回归 59 tests passed；完整单测 669 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 5126 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 123：解耦架构 project writeback payload 构造第七切片
- [x] TDD：先在 `tests/test_run_orchestration_service.py` 增加 project writeback payload 合同测试，并确认 helper 缺失导致 1 个预期失败。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `build_project_writeback_payload()`。
- [x] 迁移：`CodingOrchestrator.start_run()` 中传给 `_writeback_project_bugfix_completion()` 的 run result payload 改为消费 helper；orchestrator 继续负责 stale completion skip、实际 workitem writeback、summary 写入、ledger append/update、runner 启动和 report 写回副作用。
- [x] 文档：同步项目地图、约定、组件合同、machine-readable project context、解耦设计、实施计划和技术方案。
- [x] 验证：新增 helper tests 21 tests passed；bugfix writeback 相邻 flow 17 tests passed；相邻 run/status/QA/merge-test/bugfix 回归 61 tests passed；完整单测 670 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 5126 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 124：解耦架构 completion report payload 构造第八切片
- [x] TDD：先在 `tests/test_run_orchestration_service.py` 增加 completion report payload 合同测试，并确认 helper 缺失和 merge-test `human_required` 未标 `known_gaps` 导致 2 个预期失败。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `build_completion_report_payload()`，并让 `project_run_completion()` 统一构造写回 report payload。
- [x] 迁移：`CodingOrchestrator._reconcile_completed_active_run()` 改为复用 `project_run_completion()`，不再内联 `run_status/status/task_status` 写回和 merge-test `human_required` 特判；orchestrator 继续负责实际 `report.json` 写入、状态 transition、summary 写入、ledger update 和 runner/report 副作用。
- [x] 文档：同步项目地图、约定、组件合同、machine-readable project context、解耦设计、实施计划和技术方案。
- [x] 验证：新增 helper tests 23 tests passed；相邻 run/status/QA/merge-test/bugfix 回归 63 tests passed；完整单测 672 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 5121 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 125：解耦架构 reconciled agent run record 构造第九切片
- [x] TDD：先在 `tests/test_run_orchestration_service.py` 增加 reconciled agent run record 合同测试，并确认 helper 缺失导致 1 个预期失败。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `build_reconciled_agent_run_record()`，统一维护 active run reconcile 时的 agent run upsert payload。
- [x] 迁移：`CodingOrchestrator._reconcile_completed_active_run()` 中 `merged_run` 字典构造改为消费 helper；orchestrator 继续负责 `upsert_agent_run()`、artifact upsert、状态 transition、summary 写入和 runner session update。
- [x] 文档：同步项目地图、约定、组件合同、machine-readable project context、解耦设计、实施计划和技术方案。
- [x] 验证：新增 helper tests 24 tests passed；相邻 run/status/QA/merge-test/bugfix 回归 64 tests passed；完整单测 673 tests passed；文档/架构测试 17 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 5107 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 126：解耦架构 reconcile result payload 构造第十切片
- [x] TDD：先在 `tests/test_run_orchestration_service.py` 增加 reconcile result payload 合同测试，并确认 helper 缺失导致 1 个预期失败。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `build_reconcile_result_payload()`，统一维护 active run reconcile 返回给调用方的纯 payload。
- [x] 迁移：`CodingOrchestrator._reconcile_completed_active_run()` 尾部 return dict 改为消费 helper；orchestrator 继续负责 `report.json` 写入、状态 transition、artifact/agent_run upsert、summary 写入和 runner session update。
- [x] 验证：新增 helper tests 25 tests passed；相邻 run/status/QA/merge-test/bugfix 回归 65 tests passed；完整单测 674 tests passed；文档/架构测试 17 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 5106 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 127：解耦架构 existing run reconcile rules 第十一切片
- [x] TDD：先在 `tests/test_run_orchestration_service.py` 增加 existing run mode 和 changed files 合同测试，并确认 helper 缺失导致 2 个预期失败。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `run_mode_for_existing_run()` 和 `changed_files_for_existing_run()`，统一维护 active run reconcile 的 mode 优先级和 modified_files fallback 规则。
- [x] 迁移：`CodingOrchestrator._reconcile_completed_active_run()` 改为直接消费 service helper，并删除 orchestrator 内的 `_run_mode_for_existing_run()` / `_changed_files_for_existing_run()` 私有实现；orchestrator 继续负责 report 写回、状态 transition、artifact/agent_run upsert、summary 写入和 runner session update。
- [x] 验证：新增 helper tests 27 tests passed；相邻 run/status/QA/merge-test/bugfix 回归 67 tests passed；完整单测 676 tests passed；文档/架构测试 17 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 5076 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 128：解耦架构 start_run observation rules 第十二切片
- [x] TDD：新增 `tests/test_run_orchestration_start_rules.py`，覆盖 observed run report 观测字段构造和 stale completion 判定，并确认 helper 缺失导致 4 个预期错误。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `StaleCompletionObservation`、`build_observed_run_report()` 和 `observe_stale_completion()`。
- [x] 迁移：`CodingOrchestrator.start_run()` 改为消费 service helper 构造 `modified_files` / QA artifact / tested commit 字段，并复用 helper 判定 active run mismatch 或 cancelled task 的 stale completion；orchestrator 继续负责 diff guard、QA artifact 收集、git HEAD、report 写回、状态 transition、artifact/agent_run append、summary 和 project writeback。
- [x] 测试治理：新增 80 行小测试文件，避免继续扩写 566 行的 `tests/test_run_orchestration_service.py`。
- [x] 验证：新增 start rules tests 4 tests passed；run orchestration helper tests 31 tests passed；相邻 run/status/QA/merge-test/bugfix 回归 71 tests passed；完整单测 680 tests passed；文档/架构测试 17 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 5073 lines`；`git diff --check` passed。
- **状态：** complete

### 阶段 129：解耦架构 start_run blocked report rules 第十三切片
- [x] TDD：扩展 `tests/test_run_orchestration_start_rules.py`，覆盖 diff guard violation blocked report 和 implementation commit missing blocked report，并确认 helper 缺失导致 2 个预期错误。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `BlockedReportProjection`、`build_diff_guard_blocked_report()` 和 `build_implementation_commit_missing_report()`。
- [x] 迁移：`CodingOrchestrator.start_run()` 改为消费 service helper 拼装 diff guard 越权与 implementation 未提交的 blocked report；orchestrator 继续负责 diff guard 收集、uncommitted changes 判断、checkpoint、report 写回、状态 transition、artifact/agent_run append、summary 和 project writeback。
- [x] 测试治理：继续把 start_run 规则合同放在 131 行的 `tests/test_run_orchestration_start_rules.py`，避免扩写 566 行的 `tests/test_run_orchestration_service.py`。
- [x] 验证：新增 start rules tests 6 tests passed；run orchestration 合同 33 tests passed；相邻 run/status/QA/merge-test/bugfix 回归 73 tests passed；完整单测 682 tests passed；文档/架构测试 17 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 5056 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 130：解耦架构 plan report session fields 第十四切片
- [x] TDD：扩展 `tests/test_run_orchestration_start_rules.py`，覆盖 plan-only report 写入 `task_session.plan_report` 的白名单字段，并确认 helper 缺失导致 2 个预期错误。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `build_plan_report_session_fields()`。
- [x] 迁移：`CodingOrchestrator.start_run()` 改为消费 service helper 构造 plan report session payload；`CodingOrchestrator._plan_report_session_fields()` 保留兼容 wrapper 并委托 helper；orchestrator 继续负责 `ledger.update_task_session()`、manifest/context 消费和后续 implementation branch 策略。
- [x] 测试治理：继续把 start_run 规则合同放在 169 行的 `tests/test_run_orchestration_start_rules.py`，避免扩写 566 行的 `tests/test_run_orchestration_service.py`。
- [x] 验证：新增 start rules tests 8 tests passed；run orchestration 合同 35 tests passed；implementation/status/plan/command 相邻 flow 27 tests passed；完整单测 684 tests passed；文档/架构测试 17 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 5049 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 131：解耦架构 execution policy decision 读取第十五切片
- [x] TDD：扩展 `tests/test_run_orchestration_start_rules.py`，覆盖从 `task_session.plan_report.execution_policy_decision` 读取 Codex plan report 决策，以及 plan_report/decision 非 dict 时返回空对象，并确认 helper 缺失导致 2 个预期错误。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `latest_execution_policy_decision()`，统一维护 start_run 读取 plan report 决策的纯规则。
- [x] 迁移：`CodingOrchestrator.start_run()` 改为消费 service helper；`CodingOrchestrator._latest_execution_policy_decision()` 保留兼容 wrapper 并委托 helper；orchestrator 继续负责 `control_policy_for_mode()` 调用、timeout 选择、manifest/context 写入、ledger 更新和 runner 启动。
- [x] 测试治理：继续把 start_run 纯规则合同放在 `tests/test_run_orchestration_start_rules.py`；文件当前 208 行，仍低于大文件阈值。
- [x] 验证：新增 start rules tests 10 tests passed；run orchestration 合同 37 tests passed；status/plan/command/implementation session 相邻 flow 28 tests passed；完整单测 686 tests passed；文档/架构测试 17 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 5044 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 132：解耦架构 run diff guard violations 第十六切片
- [x] TDD：扩展 `tests/test_run_orchestration_start_rules.py`，覆盖 plan-only run 对 changed files 追加写入违规说明，且不修改原始 violations；非 plan-only mode 保持既有 violations 不变，并确认 helper 缺失导致 2 个预期错误。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `build_run_diff_guard_violations()`，统一维护 start_run 的 run-level diff guard violations 纯列表组合规则。
- [x] 迁移：`CodingOrchestrator.start_run()` 改为消费 service helper；orchestrator 继续负责 diff snapshot、changed files 收集、allowed/forbidden path 检查、diff summary 写入、blocked report 构造、状态推进和 ledger 更新。
- [x] 测试治理：继续把 start_run 纯规则合同放在 `tests/test_run_orchestration_start_rules.py`；文件当前 236 行，仍低于大文件阈值。
- [x] 验证：新增 start rules tests 12 tests passed；run orchestration 合同 39 tests passed；plan/status/command/implementation session 相邻 flow 28 tests passed；完整单测 688 tests passed；文档/架构测试 17 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 5044 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 133：解耦架构 verification limitations fallback 第十七切片
- [x] TDD：扩展 `tests/test_run_orchestration_start_rules.py`，覆盖 blocked/partial report 缺少结构化 `verification_limitations` 时追加恢复详情，且不修改原始 report；已有恢复详情时保持不覆盖，并确认 helper 缺失导致 2 个预期错误。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `ensure_verification_limitations()`，统一维护 start_run / reconcile completion report 的 verification limitations 兜底投影规则。
- [x] 迁移：`CodingOrchestrator._ensure_verification_limitations()` 改为兼容 wrapper 并委托 service helper；orchestrator 继续负责 artifact 路径提供、`report.json` 写入、状态推进、summary 和 ledger 更新。
- [x] 测试治理：继续把 start_run 纯规则合同放在 `tests/test_run_orchestration_start_rules.py`；文件当前 271 行，仍低于大文件阈值。
- [x] 验证：start rules 定向测试 14 tests passed；编译通过；run orchestration 合同 41 tests passed；plan/status/command/implementation/QA 相邻 flow 39 tests passed；完整单测 690 tests passed；文档/架构测试 17 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 5033 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 134：解耦架构 run background orchestration host helper 第十八切片
- [x] TDD：新增 `tests/test_run_background_orchestration.py`，覆盖后台 queued/running 等待完成、后台启动失败状态收敛和 merge-test `human_required` pending action 写入，并确认新模块缺失导致 1 个预期 ImportError。
- [x] 实现：新增 `coding_orchestration/run_background_orchestration.py`，把后台 host orchestration 从 `run_orchestration_service.py` 拆出。
- [x] 迁移：`CodingOrchestrator._wait_for_background_run_completion()`、`_mark_background_run_failed()` 和 `_store_pending_action_from_merge_test_result()` 改为委托 `run_background_orchestration.py`；`run_orchestration_service.py` 回到纯 run projection / payload 组合边界。
- [x] 测试治理：`tests/test_run_orchestration_service.py` 从 566 行降到 404 行，`coding_orchestration/run_orchestration_service.py` 从 589 行降到 496 行，避免新增模块进入 600 行 watch。
- [x] 验证：已完成 RED；新模块定向测试 7 tests passed；run orchestration/start/reconcile 合同 34 tests passed；相邻后台/run/status/QA/merge-test flow 53 tests passed；编译通过；完整单测 690 tests passed；文档/架构测试 17 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 5034 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 135：解耦架构 run manifest session metadata projection 第十九切片
- [x] TDD：扩展 `tests/test_run_manifest_service.py`，覆盖 Codex / non-Codex runner 的 session metadata 字段投影、既有 resume session 保留和可见性策略，并确认 helper 缺失导致 1 个预期 ImportError。
- [x] 实现：在 `coding_orchestration/run_manifest_service.py` 新增纯 session metadata projection helper `build_manifest_session_fields()`。
- [x] 迁移：`CodingOrchestrator.start_run()` 初始 resume session 和 runner 完成后的 manifest session 字段拼装改为委托 run manifest service；orchestrator 继续负责 session id 来源探测和 manifest 文件写回。
- [x] 文档：同步项目地图、约定、组件合同、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：新增 manifest tests 11 tests passed；相邻 implementation/QA/merge-test session flow 38 tests passed；文档/架构测试 17 tests passed；完整单测 693 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 5034 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 136：解耦架构 pre-run failure report payload 第二十切片
- [x] TDD：扩展 `tests/test_run_orchestration_start_rules.py`，覆盖 runner 异常和 QA/merge-test checkpoint 失败的结构化 report payload，并确认 helper 缺失导致 2 个预期 AttributeError。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `RunFailureReportProjection`、`build_runner_failed_report_payload()` 和 `build_checkpoint_failed_report_payload()`。
- [x] 迁移：`CodingOrchestrator._runner_failed_result()` 和 `_checkpoint_failed_result()` 改为消费 service helper；orchestrator 继续只负责 artifact 文件写入和 `RunResult` 包装。
- [x] 治理：`orchestrator.py` 降至 4986 行；`run_orchestration_service.py` 增至 593 行，已接近 600 行阈值，下一轮继续增长前应优先拆分或压缩。
- [x] 验证：start rules 定向测试 16 tests passed；run orchestration/start/reconcile 合同 36 tests passed；plan/run/QA/merge-test 相邻 flow 33 tests passed；文档/架构测试 17 tests passed；完整单测 695 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 4986 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 137：解耦架构 run failure report projection 模块拆分
- [x] TDD：新增 `tests/test_run_failure_report_projection.py`，要求 failure report projection 可从独立模块导入，并确认新模块缺失导致 1 个预期 ImportError。
- [x] 实现：新增 `coding_orchestration/run_failure_report_projection.py`，承接 `RunFailureReportProjection`、`build_runner_failed_report_payload()` 和 `build_checkpoint_failed_report_payload()`。
- [x] 兼容：`coding_orchestration/run_orchestration_service.py` 改为 re-export 新模块 helper，旧调用点和旧 tests 不改名。
- [x] 治理：`run_orchestration_service.py` 从 593 行降至 500 行，新增 projection 模块 104 行，避免 run service 越过 600 行阈值。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：新增/相邻 contract 38 tests passed；plan/run/QA/merge-test 相邻 flow 33 tests passed；文档/架构测试 17 tests passed；完整单测 697 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 4986 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 138：解耦架构 run report refinement projection 第二十二切片
- [x] TDD：扩展 `tests/test_run_orchestration_start_rules.py`，覆盖 diff guard blocked 优先级、implementation 成功后要求 host dirty-check、以及 host 确认未提交后生成 implementation commit missing blocked report，并确认 helper 缺失导致 3 个预期 AttributeError。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `RunReportRefinement` 和 `refine_run_report_projection()`，统一维护 start_run 的 observed report status details、diff guard blocked、implementation 状态归一和 commit-missing blocked 选择。
- [x] 迁移：`CodingOrchestrator.start_run()` 改为消费 refinement helper；orchestrator 继续负责 session metadata、workspace dirty 检查、checkpoint manifest 写入、report 写入、状态 transition、artifact/agent_run append、summary 和 project writeback。
- [x] 治理：`orchestrator.py` 从 4986 行降至 4978 行；`run_orchestration_service.py` 从 500 行增至 561 行，仍低于 600 行阈值，下一轮继续增长前需要谨慎评估是否拆出更小 projection 模块。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：新增 start rules tests 19 tests passed；run orchestration/start/reconcile 合同 41 tests passed；plan/run/QA/merge-test 相邻 flow 33 tests passed；文档/架构测试 17 tests passed；完整单测 700 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 4978 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 139：解耦架构 run report refinement projection 模块拆分
- [x] TDD：新增 `tests/test_run_report_refinement_projection.py`，要求 run report refinement projection 可从独立模块导入，并确认新模块缺失导致预期 ImportError。
- [x] 实现：新增 `coding_orchestration/run_report_refinement_projection.py`，承接 `BlockedReportProjection`、`RunReportRefinement`、`build_diff_guard_blocked_report()`、`build_implementation_commit_missing_report()` 和 `refine_run_report_projection()`。
- [x] 兼容：`coding_orchestration/run_orchestration_service.py` 改为 re-export 新模块 helper，旧调用点和旧 tests 不改名。
- [x] 治理：`run_orchestration_service.py` 从 561 行降至 438 行，新增 projection 模块 136 行，避免 run service 接近 600 行阈值并明确 projection 职责。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：新增/相邻 contract 43 tests passed；plan/run/QA/merge-test 相邻 flow 33 tests passed；文档/架构测试 17 tests passed；完整单测 702 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 4978 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 140：解耦架构 run start session update projection 第二十四切片
- [x] TDD：扩展 `tests/test_run_orchestration_start_rules.py`，覆盖 run 启动前 base session update、implementation workspace session update、QA/merge-test resume session update 和非 workspace mode 空更新，并确认 helper 缺失导致 4 个预期 AttributeError。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `build_run_start_base_session_update()` 和 `build_run_start_workspace_session_update()`，统一维护 `start_run()` 里的 `project_name`、runner provider/last mode、source branch/base、worktree 和 QA/merge-test resume session payload。
- [x] 迁移：`CodingOrchestrator.start_run()` 改为消费 run start session update helper；orchestrator 继续负责 workspace 选择/创建、source branch 计算、ledger 写入、manifest/prompt、runner 启动和状态推进。
- [x] 治理：`orchestrator.py` 从 4978 行降至 4976 行；`run_orchestration_service.py` 从 438 行增至 475 行，仍低于 600 行阈值。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：新增 start rules 23 tests passed；相邻 implementation/session/QA/merge-test/run service 46 tests passed；文档/架构测试 17 tests passed；完整单测 706 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 4976 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 141：解耦架构 active run session update projection 第二十五切片
- [x] TDD：扩展 `tests/test_run_orchestration_start_rules.py`，覆盖 runner 启动前 active run session update payload，并确认 helper 缺失导致 1 个预期 AttributeError。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `build_active_run_session_update()`，统一维护 `active_run_id` 和 `active_mode` 字段合同。
- [x] 迁移：`CodingOrchestrator.start_run()` 改为消费 active run session update helper；orchestrator 继续负责 ledger 写入、running phase、状态 transition、runner 启动和失败清理。
- [x] 治理：`orchestrator.py` 从 4976 行降至 4974 行；`run_orchestration_service.py` 从 475 行增至 488 行，仍低于 600 行阈值。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：新增 start rules 24 tests passed；run orchestration/start/reconcile contract 44 tests passed；文档/架构测试 17 tests passed；完整单测 707 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 4974 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 142：解耦架构 run context source projection 第二十六切片
- [x] TDD：扩展 `tests/test_run_orchestration_start_rules.py`，覆盖 implementation、QA、merge-test、plan-only 和 decomposition 的 run context source 选择，并确认 helper 缺失导致 1 个预期 AttributeError。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `run_context_source_for_mode()` 和 context source 常量，统一维护 `RunMode -> confirmed_plan / merge_test_context / 空` 的纯规则。
- [x] 迁移：`CodingOrchestrator.start_run()` 改为先读取 context source，再调用 `_confirmed_plan_for_task()` 或 `_merge_test_context_for_task()`；orchestrator 继续负责实际上下文读取、context artifacts、prompt 构造和 runner 启动。
- [x] 治理：`orchestrator.py` 保持 4974 行；`run_orchestration_service.py` 增至 500 行；`tests/test_run_orchestration_start_rules.py` 增至 505 行，仍低于 600 行治理阈值。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：新增 start rules 25 tests passed；run orchestration/start/reconcile contract 45 tests passed；相邻 plan/command/session/QA/merge-test flow 35 tests passed；文档/架构测试 17 tests passed；完整单测 708 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 4974 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 143：解耦架构 run checkpoint selection projection 第二十七切片
- [x] TDD：扩展 `tests/test_run_orchestration_start_rules.py`，覆盖 QA/merge-test checkpoint 选择和失败判定，并确认 helper 缺失导致 2 个预期 AttributeError。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `run_checkpoint_for_mode()` 和 `run_checkpoint_failed()`，统一维护 `RunMode -> qa_checkpoint / merge_test_checkpoint / None` 以及 failed checkpoint dict 判定。
- [x] 迁移：`CodingOrchestrator.start_run()` 改为消费 checkpoint helper；orchestrator 继续负责 checkpoint 准备、checkpoint failure result 包装、runner 启动、manifest 写入和状态推进。
- [x] 治理：`orchestrator.py` 降至 4971 行；`run_orchestration_service.py` 增至 517 行；`tests/test_run_orchestration_start_rules.py` 增至 540 行，仍低于 600 行治理阈值。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：新增 start rules 27 tests passed；run orchestration/start/reconcile contract 47 tests passed；文档/架构测试 17 tests passed；完整单测 710 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 4971 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 144：解耦架构 QA evidence observation selection projection 第二十八切片
- [x] TDD：扩展 `tests/test_run_orchestration_start_rules.py`，覆盖只有 QA mode 需要观测 QA artifacts/tested commit，并确认 helper 缺失导致 1 个预期 AttributeError。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `run_observes_qa_evidence()`，统一维护 `RunMode.QA -> True`、其他 mode 为 False 的纯规则。
- [x] 迁移：`CodingOrchestrator.start_run()` 改为先消费 QA evidence observation helper，再由 orchestrator 负责实际 `_collect_qa_artifacts()` 和 `_git_head()` 调用；helper 不读取文件、不访问 git、不写 report、不更新 ledger。
- [x] 治理：`orchestrator.py` 当前 4972 行；`run_orchestration_service.py` 增至 521 行；`tests/test_run_orchestration_start_rules.py` 增至 547 行，仍低于 600 行治理阈值。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：start rules 28 tests passed；run orchestration/start/reconcile contract 48 tests passed；文档/架构测试 17 tests passed；完整单测 711 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 4972 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 145：解耦架构 run source branch recording selection projection 第二十九切片
- [x] TDD：扩展 `tests/test_run_orchestration_start_rules.py`，覆盖只有 implementation / QA / merge-test mode 需要记录 source branch，并确认 helper 缺失导致 1 个预期 AttributeError。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `run_records_source_branch()`，统一维护 run mode 到是否记录 source branch 的纯规则。
- [x] 迁移：`CodingOrchestrator.start_run()` 改为先消费 source branch recording helper，再由 orchestrator 负责实际 `_source_branch_for_task()` 调用；helper 不计算 branch、不读取 workspace、不写 ledger。
- [x] 治理：`orchestrator.py` 当前 4972 行；`run_orchestration_service.py` 增至 525 行；`tests/test_run_orchestration_start_rules.py` 增至 554 行，仍低于 600 行治理阈值。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：start rules 29 tests passed；run orchestration/start/reconcile contract 49 tests passed；文档/架构测试 17 tests passed；完整单测 712 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 4972 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 146：解耦架构 run project path requirement selection projection 第三十切片
- [x] TDD：扩展 `tests/test_run_orchestration_start_rules.py`，覆盖只有 decomposition mode 可以在缺少 project_path 时继续，其他 run mode 必须要求 project_path。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `run_requires_project_path()`，统一维护 run mode 到 project_path gate 的纯规则。
- [x] 迁移：`CodingOrchestrator.start_run()` 改为消费 project path requirement helper；orchestrator 继续负责状态 transition、错误消息、项目路径解析和 runner 启动。
- [x] 治理：`orchestrator.py` 当前 4972 行；`run_orchestration_service.py` 增至 529 行；`tests/test_run_orchestration_start_rules.py` 增至 561 行，仍低于 600 行治理阈值。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：start rules 30 tests passed；run orchestration/start/reconcile contract 50 tests passed；delivery/command/plan 相邻 flow 37 tests passed；文档/架构测试 17 tests passed；完整单测 713 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 4972 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 147：解耦架构 run workspace selection projection 第三十一切片
- [x] TDD：新增 `tests/test_run_orchestration_workspace_rules.py`，覆盖 `RunMode -> workspace selection`、准备 phase 和缺失 workspace 错误投影，避免继续扩写 561 行的 start rules 测试文件。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `RunWorkspaceSelection`、workspace kind 常量和 `run_workspace_selection_for_mode()`；helper 只维护 mode 选择规则，不创建/查找 workspace。
- [x] 迁移：`CodingOrchestrator.start_run()` 改为消费 workspace selection helper；orchestrator 继续负责 `_implementation_workspace()`、`_merge_test_workspace()`、状态 transition、ledger 写入和 runner 启动。
- [x] 治理：`orchestrator.py` 降至 4945 行；`run_orchestration_service.py` 558 行；新增 workspace rules 测试 50 行；start rules 测试保持 561 行。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：RED 先出现 4 个预期 AttributeError；workspace rules 3 tests passed；run orchestration/start/reconcile contract 53 tests passed；implementation/session/QA/merge-test 相邻 flow 34 tests passed；文档/架构测试 17 tests passed；完整单测 716 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 4945 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 148：解耦架构 run start selection projection 模块拆分
- [x] TDD：新增 `tests/test_run_start_selection_projection.py`，要求 start-run mode selection 规则可从独立模块导入，并确认新模块缺失导致预期 ImportError。
- [x] 实现：新增 `coding_orchestration/run_start_selection_projection.py`，承接 context source、checkpoint selection、QA evidence observation、source branch recording、project path requirement 和 workspace selection 纯规则。
- [x] 兼容：`coding_orchestration/run_orchestration_service.py` 改为 re-export 新模块 helper，旧 orchestrator 调用点和旧 tests 不改名。
- [x] 治理：`run_orchestration_service.py` 从 558 行回落到 503 行，远离 600 行 watch 阈值；新增 projection 模块 76 行。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：新增 contract、run orchestration start/reconcile/service、implementation/session/QA/merge-test 相邻 flow、文档/架构测试、architecture guard、diff check、敏感扫描和完整单测。
- **状态：** complete

### 阶段 149：解耦架构 run manifest checkpoint preparation selection projection
- [x] TDD：扩展 `tests/test_run_start_selection_projection.py`，覆盖 QA / merge-test / plan-only / implementation 的 manifest checkpoint preparation 选择规则，并确认 helper 缺失导致 2 个预期 AttributeError。
- [x] 实现：扩展 `coding_orchestration/run_start_selection_projection.py`，新增 manifest target/checkpoint preparation 纯 projection；只返回目标分支、manifest 字段和 checkpoint kind，不读取 workspace、不准备 checkpoint、不写 manifest。
- [x] 迁移：`CodingOrchestrator.start_run()` 改为消费 preparation projection；实际 `_prepare_qa_checkpoint()`、`_prepare_merge_test_checkpoint()` 和 manifest 文件写入继续留在 orchestrator。
- [x] 治理：当前行数为 `orchestrator.py` 4953 行，`run_orchestration_service.py` 508 行，`run_start_selection_projection.py` 101 行，`tests/test_run_start_selection_projection.py` 149 行。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：新增 contract 6 tests passed；run orchestration/start/reconcile/service contract 59 tests passed；implementation/session/QA/merge-test 相邻 flow 34 tests passed；文档/架构测试 17 tests passed；完整单测 722 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 4953 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 150：解耦架构 plan report session writeback projection
- [x] TDD：先扩展 `tests/test_run_orchestration_start_rules.py`，覆盖只有非 stale 的 plan-only run 会生成 `{"plan_report": ...}` session update，implementation/QA/merge-test/stale completion 均不写回 plan report，并确认 helper 缺失导致 2 个预期 AttributeError。
- [x] 实现：扩展 `coding_orchestration/run_orchestration_service.py`，新增 `build_plan_report_session_update()`；helper 只返回 ledger update payload，不写 ledger、不读 artifact、不推进状态。
- [x] 迁移：`CodingOrchestrator.start_run()` 改为消费该 projection；orchestrator 继续负责实际 `ledger.update_task_session()` 和 runner session update 写入。
- [x] 治理：将 plan report session fields / writeback contract 拆到新增 `tests/test_run_orchestration_plan_report_session.py`，避免 `tests/test_run_orchestration_start_rules.py` 超过 600 行；当前 start rules 523 行，新测试 108 行。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：plan report/start/service/reconcile contract 52 tests passed；plan/command/status/source-plan 相邻 flow 26 tests passed；文档/架构测试 17 tests passed；完整单测 724 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 4956 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 151：解耦架构零耦合集成责任矩阵补强
- [x] 方案：补充工具端、MCP / WorkItem、Skill、Hermes host shell、runner、source、storage/knowledge 的横向责任矩阵，明确权威层、Hermes 只做集成的范围、禁止回流和验收信号。
- [x] 治理：把大文件和 hard code 作为跨阶段硬门禁写入同一矩阵，避免后续只按文件大小机械拆分或把 host 细节写回 core/service。
- [x] 文档：同步 `PLUGIN_TECHNICAL_SOLUTION.md`、解耦设计文档、实施计划、发现和进度日志。
- [x] 验证：文档/架构测试 17 tests passed；`architecture_guard.py` passed，仅 watch legacy `orchestrator.py`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 152：解耦架构 completion session update projection
- [x] TDD：新增 completion session update contract，覆盖 fresh plan-only 同时写 `plan_report` 与 runner、fresh non-plan 只写 runner、stale completion 不写 session，并确认 helper 缺失时先出现 3 个预期 `AttributeError`。
- [x] 实现：在 `run_orchestration_service.py` 新增 `build_completion_session_update()`，组合既有 plan report session update 与 runner session update；helper 只返回 payload。
- [x] 迁移：`CodingOrchestrator.start_run()` 收尾改为消费 completion session update；orchestrator 继续负责实际 `ledger.update_task_session()`。
- [x] 治理：当前 `orchestrator.py` 4952 行，`run_orchestration_service.py` 553 行，`tests/test_run_orchestration_plan_report_session.py` 181 行，均未新增超过 600 行的非 legacy 文件。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：plan report session contract 7 tests passed；run orchestration/start/reconcile/service contract 55 tests passed；plan/command/status/source-plan/implementation session 相邻 flow 34 tests passed；文档/架构测试 17 tests passed；完整单测 727 tests passed；`architecture_guard.py` passed，仅 watch `coding_orchestration/orchestrator.py: 4952 lines`；`git diff --check` passed；敏感扫描无命中。
- **状态：** complete

### 阶段 153：解耦架构 run session projection 模块拆分
- [x] TDD：新增 `tests/test_run_session_projection.py`，要求 session payload helper 可从独立 `coding_orchestration.run_session_projection` 导入，并确认模块缺失时先出现预期 `ModuleNotFoundError`。
- [x] 实现：新增 `coding_orchestration/run_session_projection.py`，承接 plan report session fields 白名单、plan report session update、runner session update 和 completion session update 纯 payload。
- [x] 兼容：`coding_orchestration/run_orchestration_service.py` 改为 re-export session projection helper，旧调用点和兼容测试不改名。
- [x] 治理：`run_orchestration_service.py` 从 553 行降到 465 行，新增 `run_session_projection.py` 99 行；`orchestrator.py` 仍为 4952 行 legacy watch。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：run session / plan report session / run orchestration service 聚焦 contract 28 tests passed；py_compile passed；后续收尾已运行相邻 flow、文档/架构、architecture guard、diff check、敏感扫描和完整单测。
- **状态：** complete

### 阶段 154：解耦架构 run start session projection 扩展
- [x] TDD：扩展 `tests/test_run_session_projection.py`，要求 `build_run_start_base_session_update()`、`build_run_start_workspace_session_update()` 和 `build_active_run_session_update()` 从 `run_session_projection.py` 直接导入，并确认 helper 缺失时先出现预期 ImportError。
- [x] 实现：将 run 启动前 base/workspace session update 和 active run session update 纯 payload helper 从 `run_orchestration_service.py` 迁入 `run_session_projection.py`。
- [x] 兼容：`run_orchestration_service.py` 继续 re-export 三个 helper，旧 orchestrator 调用点和 `test_run_orchestration_start_rules.py` 不改名。
- [x] 治理：`run_orchestration_service.py` 从 465 行降到 418 行，`run_session_projection.py` 增至 149 行，`tests/test_run_session_projection.py` 158 行，均低于 600 行治理阈值。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：run session/start rules contract 32 tests passed；后续收尾运行 py_compile、run orchestration contract、相邻 flow、文档/架构、architecture guard、diff check、敏感扫描和完整单测。
- **状态：** complete

### 阶段 155：解耦架构 run prompt projection 拆分
- [x] TDD：新增 `tests/test_run_prompt_projection.py`，要求 prompt 构造选择可从独立 `coding_orchestration.run_prompt_projection` 导入，并确认模块/helper 缺失时先出现预期失败。
- [x] 实现：新增 `coding_orchestration/run_prompt_projection.py`，承接 `start_run()` 中首次 prompt 与增量 prompt 的选择规则和参数合同。
- [x] 兼容：`run_orchestration_service.py` re-export prompt projection helper，`CodingOrchestrator.start_run()` 只委托 helper；prompt artifact 写文件仍留在 orchestrator。
- [x] 治理：helper 只调用传入的 prompt builder 构造字符串，不写 `input-prompt.md`、不生成 context artifacts、不写 manifest、不启动 runner、不写 ledger。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 prompt projection contract、run orchestration service/start 相关 contract、prompt/implementation/plan 相邻 flow、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 156：解耦架构 run context artifact service 拆分
- [x] TDD：新增 `tests/test_run_context_artifact_service.py`，要求 context artifact 写入可从独立 `coding_orchestration.run_context_artifact_service` 导入，并确认模块缺失时先出现预期失败。
- [x] 实现：新增 `coding_orchestration/run_context_artifact_service.py`，承接 wiki context、confirmed plan / implementation context、assembled context、run instructions、execution policy 和 context index 写入。
- [x] 兼容：`CodingOrchestrator._write_prompt_context_artifacts()` 保留 wrapper，改为委托 service；`start_run()` 调用点不改名。
- [x] 治理：service 可以写 run_dir 下的 context artifact 文件，但不得写 ledger、manifest、report、summary，不得启动 runner，不得推进 task/run 状态。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 context artifact service contract、prompt/plan/implementation/status/QA 相邻 flow、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 157：解耦架构 run manifest start update projection
- [x] TDD：扩展 `tests/test_run_manifest_service.py`，覆盖启动期 manifest update projection，包括 resume session、受控高权限字段和 merge-test target branch。
- [x] 实现：在 `coding_orchestration/run_manifest_service.py` 增加纯 helper，统一生成启动期 manifest 字段 update；helper 不写文件、不准备 checkpoint、不启动 runner、不更新 ledger。
- [x] 迁移：`CodingOrchestrator.start_run()` 改为消费该 projection；checkpoint 准备、manifest 文件写入、runner 启动和状态推进继续留在 orchestrator，并删除已无调用的 manifest permission 私有 wrapper。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 manifest service contract、run/start 相关相邻 flow、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 158：解耦架构 run start artifact service 拆分
- [x] TDD：新增 `tests/test_run_start_artifact_service.py`，覆盖 `report.schema.json`、`input-prompt.md` 和 `run-manifest.json` 启动 artifact 写入边界。
- [x] 实现：新增 `coding_orchestration/run_start_artifact_service.py`，只写 run_dir 下启动 artifact；不准备 checkpoint、不写 ledger/report/summary、不启动 runner、不推进状态。
- [x] 迁移：`CodingOrchestrator.start_run()` 改为消费 service；manifest 内容构造、checkpoint 准备、runner 启动和状态推进继续留在 orchestrator。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run start artifact service contract、plan/source/implementation/QA/merge-test 相邻 flow、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 159：解耦架构 run report artifact service 拆分
- [x] TDD：新增 `tests/test_run_report_artifact_service.py`，覆盖 `report.json` 写回边界和非 report artifact 不写入约束。
- [x] 实现：新增 `coding_orchestration/run_report_artifact_service.py`，只写指定 report artifact；不写 manifest/summary、不写 ledger、不启动 runner、不推进状态。
- [x] 迁移：`CodingOrchestrator.start_run()` 改为消费 service 写回 observed/completion report；report payload 构造、状态 transition、artifact/agent_run append、summary 和 project writeback 继续留在原边界。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run report artifact service contract、status/plan/source/implementation/QA/merge-test 相邻 flow、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 160：解耦架构 run summary artifact service 拆分
- [x] TDD：新增 `tests/test_run_summary_artifact_service.py`，覆盖 `summary.md` 写回边界和非 summary artifact 不写入约束。
- [x] 实现：新增 `coding_orchestration/run_summary_artifact_service.py`，只写指定 summary artifact；不写 report/manifest、不写 ledger、不启动 runner、不推进状态。
- [x] 迁移：`CodingOrchestrator` 中 active run reconcile、runner failed 和 checkpoint failed 的 `summary.md` 写回改为消费 service；summary 内容来源、状态 transition、artifact/agent_run append 和 project writeback 继续留在原边界。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run summary artifact service contract、status/plan/source/implementation/QA/merge-test 相邻 flow、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 161：解耦架构 run manifest artifact writeback service 拆分
- [x] TDD：新增 `tests/test_run_manifest_artifact_service.py`，覆盖 `run-manifest.json` 写回边界和非 manifest artifact 不写入约束。
- [x] 实现：新增 `coding_orchestration/run_manifest_artifact_service.py`，只写指定 manifest artifact；不写 report/summary/ledger、不启动 runner、不推进状态。
- [x] 迁移：`CodingOrchestrator.start_run()` 中 implementation dirty-check checkpoint 后的 manifest 写回改为消费 service；checkpoint 生成、状态 transition、artifact/agent_run append 和 project writeback 继续留在原边界。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run manifest artifact service contract、implementation/QA/merge-test 相邻 flow、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 162：解耦架构 run stderr artifact service 拆分
- [x] TDD：新增 `tests/test_run_stderr_artifact_service.py`，覆盖 `stderr.log` 写回边界和非 stderr artifact 不写入约束。
- [x] 实现：新增 `coding_orchestration/run_stderr_artifact_service.py`，只写指定 stderr artifact；不写 report/summary/manifest/ledger、不启动 runner、不推进状态。
- [x] 迁移：`CodingOrchestrator` 中 runner failed 和 checkpoint failed 的 `stderr.log` 写回改为消费 service；failure payload、RunResult 包装、状态 transition、artifact/agent_run append 和 project writeback 继续留在原边界。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run stderr artifact service contract、failure projection/start rules/QA/merge-test 相邻 flow、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 163：解耦架构 run ledger writeback projection 拆分
- [x] TDD：新增 `tests/test_run_ledger_projection.py`，覆盖 artifact / agent_run / merge-test record 写回 payload 聚合边界。
- [x] 实现：新增 `coding_orchestration/run_ledger_projection.py`，只构造 run ledger writeback records；不调用 ledger、不写 artifact、不启动 runner、不推进状态。
- [x] 迁移：`CodingOrchestrator.start_run()` 中 artifact record、agent_run record 和 merge-test record 的纯 payload 聚合改为消费 projection；实际 `append_artifact()`、`append_agent_run()`、`append_merge_record()` 继续留在 orchestrator host 边界。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run ledger projection contract、run orchestration service contract、implementation/QA/merge-test/status 相邻 flow、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 164：解耦架构 reconciled run ledger writeback projection 扩展
- [x] TDD：扩展 `tests/test_run_ledger_projection.py`，覆盖 active run reconcile 的 artifact / merged agent_run upsert payload 聚合边界。
- [x] 实现：扩展 `coding_orchestration/run_ledger_projection.py`，新增 reconciled run ledger writeback records projection；不调用 ledger、不写 artifact、不启动 runner、不推进状态。
- [x] 迁移：`CodingOrchestrator._reconcile_completed_active_run()` 中 artifact record 和 merged agent run payload 聚合改为消费 projection；实际 `upsert_artifact()`、`upsert_agent_run()` 继续留在 orchestrator host 边界。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run ledger projection contract、run orchestration service/reconcile contract、status/implementation/QA/merge-test 相邻 flow、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 165：解耦架构 reconciled run summary writeback projection 拆分
- [x] TDD：新增 `tests/test_run_summary_projection.py`，覆盖 active run reconcile 的 run summary writer payload 聚合边界。
- [x] 实现：新增 `coding_orchestration/run_summary_projection.py`，只构造 run summary writeback payload；不写 LLM Wiki、不调用 summary writer、不写 ledger、不推进状态。
- [x] 迁移：`CodingOrchestrator._reconcile_completed_active_run()` 中 run summary writer 参数组装改为消费 projection；实际 `summary_writer.write_run_summary()` 继续留在 orchestrator host 边界。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run summary projection contract、status reconcile/run orchestration 相邻 contract、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 166：解耦架构 completed run summary writeback projection 扩展
- [x] TDD：扩展 `tests/test_run_summary_projection.py`，覆盖 `start_run()` completed path 的 run summary writer payload 聚合边界。
- [x] 实现：扩展 `coding_orchestration/run_summary_projection.py`，新增 completed run summary writeback projection；不读取 summary artifact、不写 LLM Wiki、不调用 summary writer、不写 ledger、不推进状态。
- [x] 迁移：`CodingOrchestrator.start_run()` 中 run summary writer 参数组装改为消费 projection；summary artifact 读取和实际 `summary_writer.write_run_summary()` 继续留在 orchestrator host 边界。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run summary projection contract、plan/status/run orchestration 相邻 contract、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 167：解耦架构 run artifact path projection 拆分
- [x] TDD：新增 `tests/test_run_artifact_paths.py`，覆盖 run_dir artifact contract、existing run 记录路径优先和缺失字段 fallback，并确认模块缺失时先出现预期 `ModuleNotFoundError`。
- [x] 实现：新增 `coding_orchestration/run_artifact_paths.py`，集中构造 `ArtifactSet` 路径合同；只返回路径，不读写 artifact 文件、不写 ledger、不启动 runner、不推进状态。
- [x] 迁移：`CodingOrchestrator._artifact_set_for_run_dir()` 和 `_artifact_set_for_existing_run()` 改为委托 path projection；existing run fallback 补齐 `context_manifest`。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run artifact path contract、status/report/summary/stderr 相邻 artifact flow、plan/run orchestration 相邻 contract、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 168：解耦架构 completed run summary artifact read service 扩展
- [x] TDD：扩展 `tests/test_run_summary_artifact_service.py`，要求 summary artifact service 能读取存在的 `summary.md`，缺失时返回空字符串，并确认 helper 缺失时先出现预期 `ImportError`。
- [x] 实现：扩展 `coding_orchestration/run_summary_artifact_service.py`，新增 `read_run_summary_artifact()`；service 只读写指定 summary artifact，不生成 summary、不写 report/manifest/ledger、不启动 runner、不推进状态。
- [x] 迁移：`CodingOrchestrator.start_run()` completed path 的 `summary.md` 读取改为消费 summary artifact service；summary writer payload projection 和实际 `summary_writer.write_run_summary()` 边界不变。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run summary artifact service contract、plan/status/run summary projection 相邻 flow、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 169：解耦架构 active run report artifact read service 扩展
- [x] TDD：扩展 `tests/test_run_report_artifact_service.py`，要求 report artifact service 能读取存在的 `report.json`，缺失、无效 JSON 或非 dict 时返回空 dict，并确认 helper 缺失时先出现预期 `ImportError`。
- [x] TDD：增强 `tests/test_status_reconcile_flow.py`，在 active run reconcile 时禁用 task status presenter 的 report reader，确认 run lifecycle 不再依赖 presentation 读取 wrapper。
- [x] 实现：扩展 `coding_orchestration/run_report_artifact_service.py`，新增 `read_run_report_artifact()`；service 只读写指定 report artifact，不生成 report、不写 manifest/summary/ledger、不启动 runner、不推进状态。
- [x] 迁移：`CodingOrchestrator._reconcile_completed_active_run()` 的 `report.json` 读取改为消费 report artifact service；task status presenter 的读取 wrapper 继续保留给 presentation/status 展示路径。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run report artifact service contract、active run reconcile flow、status/plan/run summary projection 相邻 flow、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 170：解耦架构 run report summary excerpt service 扩展
- [x] TDD：扩展 `tests/test_run_report_artifact_service.py`，要求 report artifact service 能从 `report.json` 读取 `summary_markdown` 并按 limit 截断，无 summary 或无效 JSON 时返回空字符串，并确认 helper 缺失时先出现预期 `ImportError`。
- [x] TDD：覆盖 `CodingOrchestrator._report_summary_markdown()` 只委托 report artifact service，不再自行解析 `report.json`。
- [x] 实现：扩展 `coding_orchestration/run_report_artifact_service.py`，新增 `read_run_report_summary_markdown()`；该 helper 复用 report artifact reader，只返回摘要文本。
- [x] 迁移：`CodingOrchestrator._report_summary_markdown()` 改为兼容 wrapper 并委托 service；plan context / merge-test context 保留原调用名，但不再在 orchestrator 里解析 report JSON。
- [x] 文档：同步项目地图、组件合同、约定、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run report artifact service contract、plan/status 相邻 flow、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 171：解耦架构 execution policy artifact read service 扩展
- [x] TDD：扩展 `tests/test_run_context_artifact_service.py`，要求 context artifact service 能优先读取 `result["execution_policy"]`，再读取显式 `artifacts.execution_policy`，最后 fallback 到 `run_dir/execution-policy.json`，缺失、无效 JSON 或非 dict 时返回空 dict。
- [x] TDD：覆盖 `CodingOrchestrator._execution_policy_from_run_result()` 只委托 context artifact service，不再自行解析 `execution-policy.json`。
- [x] 实现：扩展 `coding_orchestration/run_context_artifact_service.py`，新增 `read_run_execution_policy_artifact()`；service 只读写 execution policy context artifact，不写 ledger、manifest、report、summary，不启动 runner、不推进状态。
- [x] 迁移：`CodingOrchestrator._execution_policy_from_run_result()` 改为兼容 wrapper 并委托 service；run orchestration helper 仍只负责 `latest_execution_policy_decision()` 的纯 plan report 决策读取。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run context artifact service contract、status/start 相邻 flow、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 172：解耦架构 run project writeback host service 拆分
- [x] TDD：新增 `tests/test_run_project_writeback_service.py`，覆盖 stale completion 跳过 Project writeback、非 stale 完成调用 callback 的 payload 合同，以及 `CodingOrchestrator.start_run()` 委托 service。
- [x] 实现：新增 `coding_orchestration/run_project_writeback_service.py`，集中处理 run 完成后的 Project/WorkItem writeback host gate；只做 stale skip、payload 构造委托和注入 callback 调用。
- [x] 迁移：`CodingOrchestrator.start_run()` 尾部不再内联 stale gate、project writeback payload 构造和 `_writeback_project_bugfix_completion()` 调用，改为消费 `write_run_project_completion()`。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run project writeback service contract、bugfix writeback/run orchestration/plan 相邻 flow、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 173：解耦架构 run summary writeback host service 拆分
- [x] TDD：新增 `tests/test_run_summary_writeback_service.py`，覆盖 completed run 和 active run reconcile 的 summary writer callback 合同，以及 `CodingOrchestrator.start_run()` / `_reconcile_completed_active_run()` 委托 service。
- [x] 实现：新增 `coding_orchestration/run_summary_writeback_service.py`，集中处理 run summary writer host callback；复用 `run_summary_projection.py` 构造 payload，只调用注入 writer callback。
- [x] 迁移：`CodingOrchestrator.start_run()` 和 `_reconcile_completed_active_run()` 不再直接构造 summary writer payload 或调用 `summary_writer.write_run_summary()`，改为消费 `write_completed_run_summary()` / `write_reconciled_run_summary()`。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run summary writeback service contract、run summary projection、plan/status 相邻 flow、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 174：解耦架构 run ledger writeback host service 拆分
- [x] TDD：新增 `tests/test_run_ledger_writeback_service.py`，覆盖 completed run append、active run reconcile upsert、merge-test record skip/append，以及 `CodingOrchestrator.start_run()` / `_reconcile_completed_active_run()` 委托 service。
- [x] 实现：新增 `coding_orchestration/run_ledger_writeback_service.py`，集中处理 run ledger host callback；只消费 `run_ledger_projection.py` 生成的 records 并调用注入 ledger callback。
- [x] 迁移：`CodingOrchestrator.start_run()` 和 `_reconcile_completed_active_run()` 不再直接调用 run lifecycle 的 `append_artifact()`、`append_agent_run()`、`append_merge_record()`、`upsert_artifact()` 或 `upsert_agent_run()`，改为消费 `write_run_ledger_completion()` / `write_reconciled_run_ledger()`。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run ledger writeback service contract、run ledger projection、plan/status/QA/merge-test 相邻 flow、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 175：解耦架构 run session writeback host service 拆分
- [x] TDD：新增 `tests/test_run_session_writeback_service.py`，覆盖非空 session update 调用注入 callback、空 update 跳过 callback，以及 `CodingOrchestrator.start_run()` / `_reconcile_completed_active_run()` 委托 service。
- [x] 实现：新增 `coding_orchestration/run_session_writeback_service.py`，集中处理 run lifecycle 的 task session host callback；只消费已由 `run_session_projection.py` 构造好的 update dict 并调用注入 callback。
- [x] 迁移：`CodingOrchestrator.start_run()` 与 `_reconcile_completed_active_run()` 的 run start base/workspace/active、transition 失败清理、runner reconcile 和 completion session update 改为委托 service；不迁 delivery/decomposition/kanban 等非本切片 session 写回。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run session writeback service contract、run session projection、plan/status/QA/merge-test 相邻 flow、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 176：解耦架构 run diff guard observation host service 拆分
- [x] TDD：新增 `tests/test_run_diff_guard_service.py`，覆盖 diff guard snapshot/observe service 合同，以及 `CodingOrchestrator.start_run()` 委托 service 后 changed files / violations 继续流入 report refinement 和 ledger records。
- [x] 实现：新增 `coding_orchestration/run_diff_guard_service.py`，集中处理 run diff guard snapshot、changed files 观测、QA artifact 过滤、policy violations 组合和 diff summary 写回。
- [x] 迁移：`CodingOrchestrator.start_run()` 不再直接调用 `self.diff_guard.snapshot()`、`changed_files()`、`find_violations()` 或 `write_diff_summary()`，改为消费 `snapshot_run_diff_guard()` / `observe_run_diff_guard()`；删除 `_diff_guard_changed_files_for_mode()` wrapper。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run diff guard service contract、diff guard/start/plan/implementation 相邻 flow、文档/架构、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 177：解耦架构 runner dispatch host service 拆分
- [x] TDD：新增 `tests/test_run_dispatch_service.py`，覆盖 checkpoint failure 不启动 runner、runner 成功时按原参数调度、runner 异常时生成 runner_failed result，以及 `CodingOrchestrator.start_run()` 委托 dispatch service。
- [x] 实现：新增 `coding_orchestration/run_dispatch_service.py`，集中处理 run 启动期 checkpoint failure、`runner.run()` 调度和 runner exception fallback。
- [x] 迁移：`CodingOrchestrator.start_run()` 不再内联 checkpoint failure / runner.run / runner exception try-except，改为消费 dispatch service；状态 transition、diff guard、QA evidence、report refinement 和 ledger/summary/project/session 写回边界保持不变。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run dispatch service contract、run orchestration start/plan/implementation 相邻 flow、文档/架构、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 178：解耦架构 run status transition host service 拆分
- [x] TDD：新增 `tests/test_run_status_transition_service.py`，覆盖 run start transition 成功/失败清理、missing project、missing workspace、fresh/stale completion 和 active run cleanup 合同。
- [x] 实现：新增 `coding_orchestration/run_status_transition_service.py`，集中处理 run lifecycle 的状态推进 host callback 和 active run 清理；只调用注入 callback，不直接持有 `TaskLedger`。
- [x] 迁移：`CodingOrchestrator.start_run()` 与 `_reconcile_completed_active_run()` 的 run lifecycle 状态推进改为委托 service；`_transition_task_status()` 自身也变为兼容 wrapper 并委托 service，非 run 命令调用路径保持现有行为。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run status transition service contract、run orchestration start/session/plan 相邻 flow、文档/架构、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 179：解耦架构 run evidence observation service 拆分
- [x] TDD：新增 `tests/test_run_evidence_observation_service.py`，覆盖 QA evidence disabled/enabled、tested commit 读取和 implementation dirty-check observation。
- [x] 实现：新增 `coding_orchestration/run_evidence_observation_service.py`，集中处理 QA artifact/tested commit 和 implementation dirty-check 观测；只调用注入 callback，不写 artifact、不创建 checkpoint。
- [x] 迁移：`CodingOrchestrator.start_run()` 的 QA evidence 收集与 implementation dirty-check 判断改为委托 service；checkpoint 创建、manifest 写回和 report refinement 保持原边界。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 run evidence observation service contract、QA/implementation/start 相邻 flow、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 180：解耦架构 run checkpoint preparation service 拆分
- [x] TDD：新增 `tests/test_run_checkpoint_preparation_service.py`，覆盖 none/QA/merge-test checkpoint preparation、空 payload 不写 manifest update 和 `start_run()` 委托。
- [x] 实现：新增 `coding_orchestration/run_checkpoint_preparation_service.py`，集中处理 QA / merge-test checkpoint preparation callback 选择和 manifest update payload；只调用注入 callback，不直接 mutate manifest、不写 artifact。
- [x] 迁移：`CodingOrchestrator.start_run()` 的 QA / merge-test checkpoint preparation 调用改为委托 service；mode 到 checkpoint kind/target branch 选择仍归 `run_start_selection_projection.py`，manifest 文件写入仍归 artifact service。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 checkpoint preparation service contract、start selection/workspace/manifest/dispatch 相邻 tests、QA/merge-test flow、文档/架构、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 181：解耦架构 implementation checkpoint writeback service 拆分
- [x] TDD：新增 `tests/test_run_implementation_checkpoint_service.py`，覆盖 dirty=false 跳过、dirty=true 生成 implementation checkpoint 并写回 manifest、dict/object manifest update 和 `start_run()` 委托。
- [x] 实现：新增 `coding_orchestration/run_implementation_checkpoint_service.py`，集中处理 implementation dirty 后置 checkpoint 与 manifest artifact writeback callback 接线；只调用注入 callback，不判断 dirty、不构造 blocked report、不推进状态。
- [x] 迁移：`CodingOrchestrator.start_run()` 的 dirty 后置 `implementation_checkpoint` 生成和 `run-manifest.json` 写回改为委托 service；dirty observation 仍归 `run_evidence_observation_service.py`，report refinement 仍归 `run_report_refinement_projection.py`。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 implementation checkpoint service contract、implementation workspace/report refinement/manifest/evidence/start 相邻 tests、文档/架构、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 182：解耦架构 run manifest session metadata writeback service 拆分
- [x] TDD：新增 `tests/test_run_manifest_session_writeback_service.py`，覆盖 session_id 缺失跳过、session_id 存在时 manifest 字段投影和 manifest metadata writer callback，以及 `start_run()` 委托。
- [x] 实现：新增 `coding_orchestration/run_manifest_session_writeback_service.py`，集中处理 runner session metadata 到 run manifest 的 host callback 接线；只消费已解析 session_id，不解析 stdout、不写 ledger/report/summary、不启动 runner、不推进状态。
- [x] 迁移：`CodingOrchestrator.start_run()` 的 session metadata manifest 字段设置和 `_update_manifest_session_metadata()` 调用改为委托 service；session id 来源、runner session ledger update 和 Codex attach/resume command 规则保持原边界。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 manifest session writeback service contract、run manifest/session/implementation session 相邻 tests、文档/架构、architecture guard、diff check 和必要完整单测。
- **状态：** complete

### 阶段 183：解耦架构 completed run writeback coordinator service 拆分
- [x] TDD：新增 `tests/test_run_completion_writeback_service.py`，覆盖 fresh completed run 写回协调、stale completion 语义和 `start_run()` 委托。
- [x] 实现：新增 `coding_orchestration/run_completion_writeback_service.py`，集中协调 fresh completed run 的 completion projection、stale observation、状态 transition、ledger/session/summary/project writeback 和 result payload。
- [x] 迁移：`CodingOrchestrator.start_run()` 的 completed tail 改为委托 service；runner dispatch、diff guard、QA evidence、implementation dirty-check、manifest session metadata 和 active-run reconcile 保持原边界。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 completion writeback service contract、writeback/start 相邻 tests、主流程、文档/架构、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 184：解耦架构 active run reconcile writeback coordinator service 拆分
- [x] TDD：新增 `tests/test_run_reconcile_writeback_service.py`，覆盖 active run reconcile 完成态写回协调和 `_reconcile_completed_active_run()` 委托。
- [x] 实现：新增 `coding_orchestration/run_reconcile_writeback_service.py`，集中协调 active run reconcile 的 completion projection、report finalization、状态 transition、ledger/session/summary writeback 和 result payload。
- [x] 迁移：`CodingOrchestrator._reconcile_completed_active_run()` 只保留 task/session/run/report 读取、mode/status/details/changed_files 观测与 artifact 前置归一化，完成态写回 tail 委托 service。
- [x] 文档：同步项目地图、组件合同、约定、machine-readable project context、解耦设计、实施计划、技术方案、发现和进度。
- [x] 验证：运行 reconcile writeback service contract、相邻 writeback/reconcile/status flow、主流程、文档/架构、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 185：Task 30 closure cleanup
- [x] 将 Task 30 当前状态收敛为关闭：fresh completed run 与 active run reconcile 两条完成态写回 coordinator 均已迁出。
- [x] 明确后续工作不再挂入 Task 30：`orchestrator.py` 降到 3000 行以内、hard code 清理、MCP Skill / Hermes 深度解耦、Gateway 执行副作用继续下沉等进入 Task 31+ / Task 18/20 长期治理。
- [x] 同步 `task_plan.md`、`progress.md`、`findings.md`、实施计划和技术方案，避免“Task 30 继续”成为开放尾巴。
- [x] 验证：文档/架构测试、architecture guard、diff check。
- **状态：** complete

### 阶段 186：Task 32 Tool operation dispatcher 第一切片
- [x] 定域：主责为 Tool contract + WorkItem adapter，不纳入 SourcePort、Skill 文案、Gateway controller 或 run orchestration。
- [x] 实现：新增 `coding_orchestration/tool_operation_dispatcher.py`，`plugin_tools.py` 注册层改为 `ToolSpec.operation_id -> ToolOperationDispatcher`，不再维护 `_OPERATION_METHODS` 或 `operation_id -> CodingOrchestrator.tool_*` 方法映射。
- [x] 迁移：`CodingOrchestrator` 装配 `tool_operation_dispatcher`，`tool_*` 保留兼容 wrapper，实际分发优先落到 `TaskService`、`WorkItemService` 和 source/run host action；`WorkItemService(create_task=...)` 从 orchestrator wrapper 改为 `TaskService.tool_task_create`。
- [x] 测试：新增 `tests/test_tool_operation_dispatcher.py`，扩展插件注册和 tool specs 测试，保护 operation_id dispatch、未知 operation 和唯一性。
- [x] 文档：同步 project map、component contract、conventions、machine-readable context、实施计划和技术方案。
- [x] 验证：聚焦回归、architecture guard、diff check 和完整单测均通过。
- **状态：** complete

### 阶段 187：Task 32 CLI tool-equivalent dispatcher 第二切片
- [x] TDD：新增 `tests/test_coding_cli.py` 覆盖 CLI `lark-preflight` 和 `source-resolve` 不再绕回 `command_coding_cli()`，而是直接调用 `dispatch_tool_operation()`。
- [x] RED：确认新增测试先失败在旧 CLI handler 调用 `command_coding_cli()` 的路径上。
- [x] 实现：`coding_orchestration/cli.py` 对 `lark-preflight`、`source-resolve` 直接执行 `source.lark_preflight` / `source.resolve` operation，并复用现有 formatter 输出。
- [x] 兼容：`doctor`、`project-mcp-preflight`、`status` 暂不纳入本切片，避免把 preflight 配置检查和状态展示混入 Tool dispatcher 改造。
- [x] 文档：同步 Task 32 进度、技术方案和发现。
- [x] 验证：CLI/dispatcher 聚焦回归、architecture guard、diff check 和完整单测均通过。
- **状态：** complete

### 阶段 188：Task 33 Skill 零耦合复查
- [x] TDD：扩展 `tests/test_plugin_registration.py`，要求 core skill 不含 Hermes、`/coding`、`rtk `、`lark-cli`、运行根、ledger、LLM Wiki、token key 等 host 细节。
- [x] RED：确认 `hermes-coding-operator` 仍复制 `## 硬规则` / `## 意图分流` / `## 项目优先流程` 等通用 playbook 时测试失败。
- [x] RED：确认 `hermes-coding-health-check` 仍复制 core readiness 输出格式、硬规则和示例时测试失败。
- [x] 实现：`hermes-coding-operator` 只保留 core 引用、core intent 到 `/coding` / native tools / 普通回复的映射和用户可见措辞边界。
- [x] 实现：`hermes-coding-health-check` 只保留 core 引用、Hermes doctor/preflight 恢复命令和插件本地配置引用映射。
- [x] 边界：Task 33 不承接 `orchestrator.py` 降载、SourcePort 消费闭环、Tool dispatcher 后续或 Gateway 执行副作用下沉；这些仍归 Task 31/32/34+。
- [x] 验证：插件注册聚焦测试、architecture guard、diff check 和完整单测均通过。
- **状态：** complete

### 阶段 189：Task 32 CLI `project-mcp-preflight` dispatcher 第三切片
- [x] TDD：新增 `tests/test_coding_cli.py` 覆盖 CLI `project-mcp-preflight` 不再绕回 `command_coding_cli()`，而是读取 host preflight config、检查 stdio command 可用性，并按条件 dispatch `project.mcp_preflight`。
- [x] RED：确认旧路径会触发 `command_coding_cli()` 断言失败。
- [x] 实现：`coding_orchestration/cli.py` 对 `project-mcp-preflight` 复用 `format_project_mcp_preflight()`，仅在 enabled、token configured、stdio command ready 时调用 dispatcher。
- [x] 兼容：`CodingOrchestrator._format_project_mcp_preflight()` 保留旧 façade，但配置读取和 command availability 检查拆成 host action，便于 CLI 直接集成。
- [x] 边界：本切片不迁 `doctor`、`status`、Gateway diagnostic，也不删除 `CodingOrchestrator.tool_*` 兼容 wrapper；这些继续归 Task 32 后续或 presentation/Gateway 专项。
- [x] 修复：review 发现 direct dispatcher path 失败时 CLI 仍返回 0；新增缺 token、stdio command 不可用、dispatcher 返回失败三个负向测试并恢复失败退出码 1。
- [x] 文档：同步 Task 32 第三切片进度、技术方案、实施计划、项目地图、约定和发现。
- [x] 验证：运行 CLI/dispatcher 聚焦回归、architecture guard、diff check、文档/架构测试和完整单测。
- **状态：** complete

### 阶段 190：Task 32 Gateway `project-mcp-preflight` diagnostic 第四切片
- [x] 定域：只补 Gateway `/coding project-mcp-preflight` diagnostic route，不迁 `doctor` 聚合、不迁 `status` presentation、不实装 future MCP host。
- [x] TDD：扩展 `tests/test_gateway_command_controller.py`，要求 `/coding project-mcp-preflight` 标记为 diagnostic immediate reply。
- [x] TDD：扩展 `tests/test_gateway_command_group_flow.py`，要求 Gateway 事件被 coding plugin 拦截，并输出 `format_project_mcp_preflight()` 文案。
- [x] RED：确认旧 route table 将 `project-mcp-preflight` 落到 help，Gateway flow 不调用 project MCP preflight。
- [x] 实现：`gateway_command_controller.py` 增加 `coding-project-mcp-preflight` route 和 normalize map；`orchestrator.py` immediate route 与直接 `command_coding()` 入口复用 `_format_project_mcp_preflight()`；`command_catalog.py` 补齐 `/coding project-mcp-preflight` 帮助和 rewrite 上下文。
- [x] 文档：同步 Task 32 第四切片进度、技术方案和发现。
- [x] 验证：运行 Gateway diagnostic 聚焦回归、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 191：Task 32 CLI `status <task_id>` dispatcher 第五切片
- [x] 定域：只让 CLI 普通 `status <task_id>` 读取 `task.status` payload；无 task id、Gateway status、`--tree` / `--delivery` 和 active run reconcile 继续保留在 command façade。
- [x] TDD：扩展 `tests/test_coding_cli.py`，要求只有 dispatcher 的 CLI host 处理 `status task_123`，并禁止回落到 `command_coding_cli()`。
- [x] RED：确认旧 CLI status 路径会触发 `command_coding_cli()` 断言失败。
- [x] 实现：`coding_orchestration/cli.py` 对 `status <task_id>` 直接 dispatch `task.status`；`task_status_presenter.py` 新增 tool payload 的用户可见渲染函数。
- [x] 文档：同步 Task 32 第五切片进度、技术方案和发现。
- [x] 验证：运行 CLI/status/dispatcher 聚焦回归、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 192：Task 34 本地项目解析 helper 第一切片
- [x] 定域：只迁出项目文件夹候选抽取、候选去重、本地项目搜索根、路径解析和人工别名抽取；不迁 project list/status 文案、不迁 project profile 写入、不碰 Gateway 回复、source reader 或 runner。
- [x] TDD：新增 `tests/test_gateway_project_context.py`，要求 helper 支持反引号/项目路径标签抽取、显式 search roots 注入、registry parent + extra roots 去重和人工别名抽取。
- [x] RED：确认新模块缺失时测试失败。
- [x] 实现：新增 `coding_orchestration/gateway_project_context.py`；`CodingOrchestrator` 对应函数改为薄 wrapper，并新增可注入 `local_project_search_roots`。
- [x] 文档：同步 Task 34 第一切片进度、技术方案和发现。
- [x] 验证：运行项目上下文聚焦回归、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 193：Task 34 blocked merge-test readiness service 第二切片
- [x] 定域：只迁出 blocked task 是否允许继续 merge-test 的纯评估规则；不迁状态 transition、merge record/human decision 写入、Gateway pending action、runner 启动或 presenter 文案。
- [x] TDD：新增 `tests/test_merge_test_readiness_service.py`，覆盖缺 implementation run、Codex ready report、diff guard 优先级和 implementation not landed。
- [x] RED：确认新模块缺失时测试失败。
- [x] 实现：新增 `coding_orchestration/merge_test_readiness_service.py`；`CodingOrchestrator._blocked_task_merge_test_assessment()` 改为只收集 implementation run、workspace、source branch、resume session 和 report，再委托 service。
- [x] 文档：同步 Task 34 第二切片进度、技术方案、项目地图、组件合同、约定和发现。
- [x] 验证：运行 merge-test readiness/blocked/QA gate/basic 聚焦回归、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 194：Task 34 project profile catalog 第三切片
- [x] 定域：只迁出 project profile 读取、registry fallback、别名查找、动态来源计数和 project list/status 格式化；不迁 project init/upsert、active project binding、Gateway 回复副作用、rewrite 执行或 source reader。
- [x] TDD：新增 `tests/test_project_profile_catalog.py`，覆盖 wiki + registry 合并去重、name/alias/project/path basename 查找、project list 当前标记和 project status 初始化质量。
- [x] RED：确认新模块缺失时测试失败。
- [x] 实现：新增 `coding_orchestration/project_profile_catalog.py`；`CodingOrchestrator` 对应 profile 函数改为薄 wrapper，通过 catalog 消费 wiki 与 registry projects。
- [x] 文档：同步 Task 34 第三切片进度、技术方案、项目地图、组件合同、约定和发现。
- [x] 验证：运行 project profile catalog、Gateway project/rewrite/binding 相邻回归、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 195：Task 34 rewrite context projection 第四切片
- [x] 定域：只迁出 Coding Mode rewrite context 白名单投影和 task next-step hint 纯规则；不迁 command_rewriter 调用、pending rewrite 存取、确认/取消 gate、Gateway reply、active binding、ledger 读取或 project catalog 读取。
- [x] TDD：新增 `tests/test_gateway_rewrite_context.py`，覆盖 active/known task 投影、media type 投影、command catalog / allowed commands 转发和 next-step hint 状态规则。
- [x] RED：确认新模块缺失时测试失败。
- [x] 实现：新增 `coding_orchestration/gateway_rewrite_context.py`；`CodingOrchestrator._coding_rewrite_context()` 只采集 event/ledger/project/catalog 事实后委托 helper，`_task_next_step_hint()` 改为兼容 wrapper。
- [x] 文档：同步 Task 34 第四切片进度、技术方案、项目地图、组件合同、约定、machine-readable context 和发现。
- [x] 验证：运行 rewrite context contract、Gateway rewrite/natural language/presenter 相邻回归、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 202：Task 34 delivery materialize executor 第五切片
- [x] 定域：只迁 `/coding materialize` command-level host shell 和 ledger callback 绑定；不迁 breakdown/analyze、approve-breakdown、`run --next`、delivery/tree status、rollup、runner、Gateway route 或 DeliveryService 纯规则。
- [x] TDD：新增 `tests/test_delivery_command_executor.py`，直接覆盖 materialize 成功、空参数、未找到、未确认、未允许、plan error、空 children 和 existing children 幂等分支。
- [x] RED：确认 `coding_orchestration.delivery_command_executor` 模块缺失时测试失败。
- [x] 实现：新增 `delivery_command_executor.py`，承接 `command_coding_materialize()` 和 `materialize_execution_tasks()`；`CodingOrchestrator.command_coding_materialize()` / `_materialize_execution_tasks()` 保留薄 wrapper。
- [x] 文档：同步 Task 34 第五切片进度、技术方案、项目地图、组件合同、约定、machine-readable context 和发现。
- [x] 验证：运行 delivery command executor、delivery flow/service、command run、Gateway command executor 聚焦回归、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 203：Task 34 delivery approve-breakdown executor 第六切片
- [x] 定域：只迁 `/coding approve-breakdown` command-level host shell 和 human decision 写入；不迁 breakdown/analyze、materialize、`run --next`、delivery/tree status、rollup、runner、Gateway route 或 DeliveryService 纯规则。
- [x] TDD：扩展 `tests/test_delivery_command_executor.py`，直接覆盖 approve-breakdown 空参数、未找到、未拆解、open questions、成功 append human decision 和不启动 runner/implementation。
- [x] RED：确认 `delivery_command_executor.command_coding_approve_breakdown()` 缺失时测试失败。
- [x] 实现：`delivery_command_executor.py` 新增 `command_coding_approve_breakdown()`；`CodingOrchestrator.command_coding_approve_breakdown()` 保留薄 wrapper。
- [x] 文档：同步 Task 34 第六切片进度、技术方案、项目地图、组件合同、machine-readable context 和发现。
- [x] 验证：运行 delivery command executor、delivery flow/service、command run、Gateway command executor 聚焦回归、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 204：Task 34 delivery run-next executor 第七切片
- [x] 定域：只迁 `/coding run <parent> --next` command-level host shell、next child 选择调用、parent rollup callback 和 implementation command 委托；不迁普通 `/coding run <task_id>`、start_run、breakdown/analyze、delivery/tree status、runner、workspace/git、Gateway route 或 DeliveryService 纯规则。
- [x] TDD：扩展 `tests/test_delivery_command_executor.py`，直接覆盖 run-next 空参数、缺父任务、非 requirement、无可运行子任务 rollup、成功选择子任务并调用 implement 后 rollup。
- [x] RED：确认 `delivery_command_executor.command_coding_run_next()` 缺失时测试失败。
- [x] 实现：`delivery_command_executor.py` 新增 `command_coding_run_next()`；`CodingOrchestrator.command_coding_run()` 的 `--next` 分支保留薄 wrapper，普通 run 仍留原边界。
- [x] 文档：同步 Task 34 第七切片进度、技术方案、项目地图、组件合同、machine-readable context 和发现。
- [x] 验证：运行 delivery command executor、delivery flow/service、command run、Gateway command executor 聚焦回归、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 205：Task 34 delivery status executor 第八切片
- [x] 定域：只迁 `/coding status <parent> --delivery/--tree` 在通用 task 校验和 active run reconcile 之后的 children 读取、delivery projection/render 和 tree render；不迁普通 status、active run reconcile、Gateway status、TaskStatus presenter、breakdown/analyze、runner、workspace/git 或 DeliveryService 纯规则。
- [x] TDD：扩展 `tests/test_delivery_command_executor.py`，直接覆盖 delivery status progress/next child、tree status children/dependencies，并断言不启动 runner、不调用 implement、不写 rollup。
- [x] RED：确认 `delivery_command_executor.command_coding_delivery_status()` 缺失时测试失败。
- [x] 实现：`delivery_command_executor.py` 新增 `command_coding_delivery_status()`；`CodingOrchestrator.command_coding_status()` 保留缺 task、未找到和 active run reconcile 分支，delivery/tree 分支委托 executor。
- [x] 文档：同步 Task 34 第八切片进度、技术方案、项目地图、组件合同、machine-readable context 和发现。
- [x] 验证：运行 delivery command executor、delivery flow/service、status reconcile、command run、Gateway command executor 聚焦回归、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 206：Task 34 delivery breakdown executor 第九切片
- [x] 定域：只迁 `/coding breakdown` 和 `/coding analyze` command-level host shell、decomposition run 调用、decomposition session 写回、requirement hierarchy 写回和拆解成功/失败文案委托；不迁 `start_run()` 实现、runner/workspace/git、Gateway route、普通 run/status、active run reconcile、DeliveryService 纯规则或 decomposition blocked presenter。
- [x] TDD：扩展 `tests/test_delivery_command_executor.py`，直接覆盖 breakdown/analyze 空参数、未找到、`start_run(DECOMPOSITION)` 错误、blocked result 不写 session/hierarchy、成功写 decomposition 和 requirement hierarchy、analyze alias。
- [x] RED：确认 `delivery_command_executor.command_coding_breakdown()` / `command_coding_analyze()` 缺失时测试失败。
- [x] 实现：`delivery_command_executor.py` 新增 `command_coding_breakdown()` 和 `command_coding_analyze()`；`CodingOrchestrator.command_coding_breakdown()` / `command_coding_analyze()` 保留薄 wrapper。
- [x] 文档：同步 Task 34 第九切片进度、技术方案、项目地图、组件合同、machine-readable context 和发现。
- [x] 验证：运行 delivery command executor、delivery flow/service、Gateway command executor、command catalog、command run 聚焦回归、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 207：Task 34 project command executor 第十切片
- [x] 定域：只迁 `/coding project list/init/use/status/clear` 命令模式提示和 Gateway immediate project context host shell；不迁 Gateway route、project profile catalog 纯规则、项目路径候选/别名规则、任务创建、runner/workspace/git、状态推进或 run lifecycle。
- [x] TDD：新增 `tests/test_project_command_executor.py`，覆盖命令模式不写 Gateway binding、project init 参数/项目缺失、project init 成功 profile upsert + active binding、project use/status/list/clear 共享 active project binding，以及无 binding 的 status/clear 文案。
- [x] RED：确认 `project_command_executor` 缺失时测试失败。
- [x] 实现：新增 `coding_orchestration/project_command_executor.py`；`CodingOrchestrator.command_coding_project_*()` 和 Gateway immediate project 分支改为薄 wrapper；删除 orchestrator 中已迁出的 project command 私有 helper。
- [x] hard code：新 executor 中项目路径示例改为通用 `/absolute/path/to/repo`，避免继续扩散本机路径示例。
- [x] 文档：同步 Task 34 第十切片进度、技术方案、项目地图、组件合同、machine-readable context 和发现。
- [x] 验证：运行 project command executor、Gateway project task / command group / rewrite / controller 聚焦回归、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 208：Task 34 diagnostics command executor 第十一切片
- [x] 定域：只迁 `doctor`、`lark-preflight`、`project-mcp-preflight`、`source-resolve` 的 command-level diagnostic host shell、Project MCP config/stdio readiness gate、Hermes runtime availability probe 和 Gateway immediate diagnostic 分支；不迁 Gateway route/controller、CLI direct dispatcher、普通 status/list presentation、runner/workspace/git、source enrichment 或 run lifecycle。
- [x] TDD：新增 `tests/test_coding_diagnostics_command_executor.py`，覆盖 doctor 在 runner router decision 异常时仍输出诊断、CLI status 继续委托 host façade、Project MCP 只有 enabled + token + command ready 才 dispatch、source-resolve 空输入不 dispatch、runtime availability 读取 runner runtime port。
- [x] RED：确认 `coding_diagnostics_command_executor` 缺失时测试失败。
- [x] 实现：新增 `coding_orchestration/coding_diagnostics_command_executor.py`；`CodingOrchestrator.command_coding_cli()`、`command_coding_doctor()`、`_format_lark_preflight()`、`_format_project_mcp_preflight()`、`_format_source_resolve()`、`_hermes_runtime_available()` 和 Gateway immediate diagnostic 分支改为薄 wrapper。
- [x] 文档：同步 Task 34 第十一切片进度、技术方案、项目地图、组件合同、machine-readable context 和发现。
- [x] 验证：运行 diagnostics command executor、coding CLI、Gateway command group/controller、py_compile、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 209：Task 34 status command executor 第十二切片
- [x] 定域：只迁普通 `/coding status <task_id>` 和 Gateway status immediate host shell 的参数解析、active task fallback、缺 task/未找到文案、active run reconcile callback 调用、delivery/tree status 委托和 status presenter 调用；不迁 active run reconcile 实现、delivery status executor、TaskStatus presenter、Gateway route/controller、CLI direct dispatcher、runner/workspace/git 或 run lifecycle。
- [x] TDD：新增 `tests/test_coding_status_command_executor.py`，覆盖缺 task、未找到、active run reconcile 后不展示 branch、delivery/tree flag 复用既有 delivery executor、Gateway active task fallback 和 Gateway status 展示 branch。
- [x] RED：确认 `coding_status_command_executor` 缺失时测试失败。
- [x] 实现：新增 `coding_orchestration/coding_status_command_executor.py`；`CodingOrchestrator.command_coding_status()` 和 `_status_for_event()` 改为薄 wrapper。
- [x] 文档：同步 Task 34 第十二切片进度、技术方案、项目地图、组件合同、machine-readable context 和发现。
- [x] 验证：运行 status command executor、status/delivery/Gateway 聚焦回归、py_compile、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 210：Task 34 list command executor 第十三切片
- [x] 定域：只迁普通 `/coding list` 和 Gateway list immediate host shell 的 active status 查询、active task 标记、空列表文案和切换提示；不迁 task list presenter、Gateway route/controller、CLI direct dispatcher、status reconcile、delivery/project/diagnostics、runner/workspace/git 或 run lifecycle。
- [x] TDD：新增 `tests/test_coding_task_list_command_executor.py`，直接覆盖命令模式列表、空列表、Gateway active task tip 和无 binding tip。
- [x] RED：确认新 executor 缺失或未接线时测试失败。
- [x] 实现：新增 `coding_task_list_command_executor.py`；`CodingOrchestrator.command_coding_list()`、`_format_task_list_for_event()` 和 `_format_task_list()` 改为薄 wrapper。
- [x] 文档：同步 Task 34 第十三切片进度、技术方案、项目地图、组件合同、约定、machine-readable context 和发现。
- [x] 验证：运行 list command executor、task list presenter、completion/list/Gateway 聚焦回归、py_compile、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 211：Task 34 run command executor 第十四切片
- [x] 定域：只迁普通 `/coding run <task_id>`、`/coding implement <task_id>` 和 `/coding qa <task_id>` 的同步 command-mode host shell；不迁 `/coding run <parent> --next`、Gateway 异步启动、`start_run()`、active run reconcile、workspace/checkpoint/git、merge-test gates、delete/cancel/restore 或 run lifecycle 实现。
- [x] TDD：新增 `tests/test_coding_run_command_executor.py`，覆盖 run 缺 task、未找到、`start_run()` ValueError、plan-only mode 调用、implementation plan-ready gate、plan-not-ready human decision、cancelled gate 和 QA blocker。
- [x] RED：确认新 executor 缺失或未接线时测试失败。
- [x] 实现：新增 `coding_run_command_executor.py`；`CodingOrchestrator.command_coding_run()` 普通分支、`command_coding_implement()` 和 `command_coding_qa()` 改为薄 wrapper，`--next` 继续委托 delivery executor。
- [x] 文档：同步 Task 34 第十四切片进度、技术方案、项目地图、组件合同、约定、machine-readable context 和发现。
- [x] 验证：运行 run command executor、command run / QA / cancel restore 聚焦回归、py_compile、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 196：Task 31 SourceProjection prompt source block 第一切片
- [x] 定域：只新增 SourceProjection 纯投影层，并让 prompt source block 消费投影；不改 ledger schema、不改 legacy `source_context` 持久化、不改 reader、不改 TaskService 创建逻辑、不改 run manifest 权限判断或 orchestrator enrichment。
- [x] TDD：新增 `tests/test_source_projection.py`，覆盖 `SourceResult` / legacy `source_context` 到稳定字段、legacy 兼容白名单和空来源 missing 状态。
- [x] RED：确认新模块缺失时测试失败。
- [x] 实现：新增 `coding_orchestration/source_projection.py`；`coding_orchestration/prompts/source_block.py` 改为通过 projection 渲染 `source_status`、`lark_cli_command`、`recovery_action`、raw_fields 和 deferred/Codex note。
- [x] 文档：同步 Task 31 第一切片进度、技术方案、项目地图、组件合同、约定、machine-readable context 和发现。
- [x] 验证：运行 source projection / prompt templates、source/source-plan/task-service/context artifact 相邻回归、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 197：Task 31 SourceProjection context-index 第二切片
- [x] 定域：只让 `run_context_artifact_service.py` 写入 `context-index.json` 时追加稳定 `source_projection`；不改 legacy `source_context`、TaskService、ledger、manifest 权限判断或 run 前 source enrichment。
- [x] TDD：扩展 `tests/test_run_context_artifact_service.py`，要求 context-index 同时保留 `source_context` 并新增 `source_projection`。
- [x] RED：确认旧实现缺少 `source_projection` 时测试失败。
- [x] 实现：`source_projection.py` 新增 `source_projection_to_dict()`；`write_run_context_artifacts()` 复用 `source_projection_from_source()` 写入稳定投影字段。
- [x] 文档：同步 Task 31 第二切片进度、技术方案、实施计划、组件合同和发现。
- [x] 验证：运行 context artifact 聚焦回归、source projection 回归、source/source-plan/task-service/context assembler 相邻回归、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 198：Task 31 ContextAssembler source summary 第三切片
- [x] 定域：只让 `ContextAssembler._current_task_block()` 通过 `SourceProjection.raw_fields_summary` 输出 `source_summary`；不输出完整 raw_fields、不改 TaskService status payload、不改 run manifest 权限判断、不改 orchestrator enrichment。
- [x] TDD：扩展 `tests/test_context_assembler.py`，patch `source_projection_from_source()` 并确认 assembled context 使用 projection summary，不直接读 legacy `source_context.raw_fields_summary`。
- [x] RED：确认旧实现仍读 legacy summary 时测试失败。
- [x] 实现：`context_assembler.py` 引入 `source_projection_from_source()`，当前任务块只消费 projection 的 `raw_fields_summary`。
- [x] 文档：同步 Task 31 第三切片进度、技术方案、实施计划、组件合同和发现。
- [x] 验证：运行 context assembler/source projection 聚焦回归、source/source-plan/task-service/run context artifact 相邻回归、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 199：Task 31 TaskService status payload 第四切片
- [x] 定域：只让 `TaskService.task_status_payload()` 和 `next_actions_for_task_payload()` 消费 `SourceProjection`；不改 task 创建、ledger schema、manifest 权限判断、orchestrator deferred enrichment 或 source reader。
- [x] TDD：扩展 `tests/test_task_service.py`，patch `task_utils.source_projection_from_source()` 并确认 status payload 的 source 字段和 next_actions 来自 projection。
- [x] RED：确认旧实现继续读取 legacy `source_context` 时测试失败。
- [x] 实现：`task_utils.py` 新增 `source_projection_for_task_payload()`，`next_actions_for_task_payload()` 基于 projection 状态和 Codex 可读性判断；`TaskService.task_status_payload()` 通过 projection 输出 `source_status`、`source_type`、`source_url` 和 `source_recovery_action`。
- [x] 文档：同步 Task 31 第四切片进度、技术方案、实施计划、组件合同和发现。
- [x] 验证：运行 task service/status payload/source projection 聚焦回归、source/source-plan/context artifact/context assembler 相邻回归、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 200：Task 31 manifest source permission 第五切片
- [x] 定域：只让 `run_manifest_service.source_requires_codex_plan_permissions()` 消费 `SourceProjection`；不改 Codex command builder、runner、source reader、task 创建、ledger schema 或 orchestrator deferred enrichment。
- [x] TDD：扩展 `tests/test_run_manifest_service.py`，patch `source_projection_from_source()` 并确认 plan-only source elevation 由 projection 决定，同时无 `source_context` 的手动来源保持 read-only。
- [x] RED：确认旧实现继续读取 legacy success context 时不会触发 projection 要求的 source elevation。
- [x] 实现：`run_manifest_service.py` 通过 `source_projection_from_source()` 判断 missing/ok/Codex 可读性/飞书来源类型。
- [x] 文档：同步 Task 31 第五切片进度、技术方案、实施计划、组件合同和发现。
- [x] 验证：运行 run manifest/source plan/Codex command/status reconcile 聚焦回归、source/task/context 相邻回归、architecture guard、diff check 和完整单测。
- **状态：** complete

### 阶段 201：Task 31 deferred source enrichment 第六切片
- [x] 定域：只让 `CodingOrchestrator._enrich_deferred_source_context_before_run()` 和 `_is_deferred_feishu_source_context()` 的 run 前判定消费 `SourceProjection`；不改 reader、ledger schema、TaskService 创建逻辑、run manifest 权限或 context artifact。
- [x] TDD：扩展 `tests/test_source_plan_flow.py`，patch `source_projection_from_context()`，确认 legacy `source_context` 字段与 projection 不一致时，以 projection 决定是否刷新 deferred Feishu source。
- [x] RED：确认旧实现直接读取 legacy `read_status=success` 时不会调用 resolver。
- [x] 实现：orchestrator enrichment 使用 `projection.ok`、`codex_resolvable`、`resolution_owner`、`source_type`、`url` 和 `status` 判定；ledger 写回仍保持 legacy `source_context` dict 兼容。
- [x] 文档：同步 Task 31 第六切片进度、技术方案、实施计划、项目地图、组件合同、约定、machine-readable context 和发现。
- [x] 验证：运行 source plan/source flow/source projection/run manifest/task service 聚焦回归、architecture guard、diff check 和完整单测。
- **状态：** complete

## 关键问题
1. Coding Mode 是否默认只在当前会话生效，还是可跨会话保持？建议先做当前会话级。
2. Codex 可见 session 的具体 attach/resume 命令需要以当前 Codex CLI 实际支持为准。
3. API refresh、依赖安装、端口监听等恢复动作哪些可以自动执行，哪些需要人工批准？建议按风险分级。
4. 当前 `codex exec` 是否有官方可见 session/attach 命令，需要以本机 CLI 能力验证；若不可见，只能先写入可恢复的 `resume session_id` 和明确 attach/replay 命令。

## 已做决策
| 决策 | 理由 |
|------|------|
| 分支名采用 `codex/<semantic-slug>-<task-short-id>` | 仓库上下文已隐含项目名，不需要 `bps-admin` 前缀 |
| `进入coding` 开启会话级 Coding Mode | 降低重复输入 `/coding` 的交互成本 |
| prepare merge test 独立成阶段 | 避免人工说“可 merge test”后仍走 implementation |
| 验证受限必须带恢复动作 | 不能把 blocked 原因只抛给用户 |
| 人工任务默认使用可见 Codex session | 便于 CLI 观察、接管、恢复 |
| 一个 task 只维护一个 Codex session | 减少重复注入大上下文；后续 run 只发送本轮增量反馈和阶段指令 |
| Codex prompt 自然语言统一中文 | 便于中文需求上下文一致；机器契约字段和值保持英文以免破坏 report schema |
| implementation 完成后默认等待手动 merge test | 正常开发完成且验证成功后进入 `ready_for_merge_test`；Hermes 提示人工执行 `/coding merge-test <task_id>`，仅越权 diff、runner 崩溃或真正缺人工输入才阻断 |
| 首次 Codex prompt 只保留极简任务指令 | Codex session 已在目标目录打开，项目规则在仓库内可见；大上下文写入 run artifact 后引用，避免首轮 token 负担过重 |
| Hermes 不实现测试执行器，QA 由 Codex + `$qa` skill 执行 | `$qa` 已覆盖 diff-aware 浏览器 QA、问题修复、复验、报告和截图；Hermes 只做调度、session 复用、artifact 回收、状态归一和可选 QA 证据提示 |
| implementation/QA 使用受控高权限 | 依赖安装、私有源访问、dev server、浏览器 QA、`.git/worktrees` 和 `.gstack` 写入超出 `workspace-write` 能力；Codex runner 使用 bypass，但子进程 cwd 仍限定在 task worktree，manifest/prompt 明确源码修改边界，Hermes diff guard 继续兜底 |
| 可见 Codex session 只放必要 prompt | 插件规范、report schema 字段、状态机细节和权限清单写入 run artifacts；visible session 只放本轮动作、delta 和必要上下文引用，方便人工进入 session 查看真实交互 |
| QA 前需要 checkpoint commit | `$qa` 要求 clean working tree，并会按问题产生 atomic fix commit；implementation 改动需要先被保存在 source branch 上 |
| blocked 只允许有证据地人工放行 merge-test | blocked 不是绝对不能合 test，但必须能证明实现已落地且只是验证受限；Hermes 会先归一为 `ready_for_merge_test_with_known_gaps` 并记录放行原因，越权 diff、runner_failed、failed、缺 report 或未落地代码仍不允许 |
| blocked 风险可由人工显式接受 | 缺 report、缺 session、diff guard 越权、runner_failed/failed、结构化字段不完整或未落地代码证据默认不直接合 test，但会返回确认提示；用户 `--accept-risk` 或回复确认后，Hermes 记录 `accepted_risk` 并继续 |
| merge-test 成功不代表 task 完成 | 成功合入 test 后进入 `merged_test`，继续出现在 `/coding list`；只有用户发送 `/coding complete <task_id>` 才进入 `done` |
| 需求变更使用 `/coding change` | 区分 bugfix 与需求变更；change 先回到 plan-only 做影响分析和短计划，不直接修实现 |
| Coding Mode 高置信度 rewrite 直接执行 | 用户进入 Coding Mode 后表达明确意图时降低二次确认成本；低置信度、缺信息和 destructive 候选仍不自动执行 |
| 不大范围重构 | 现有入口已经集中在 orchestrator/runner/model/schema，P0 可通过局部扩展完成 |

## 遇到的错误
| 错误 | 尝试次数 | 解决方案 |
|------|---------|---------|
| 初始无规划文件 | 1 | 已创建 `task_plan.md`、`findings.md`、`progress.md` |
| session catchup 未实现 Codex 原生解析 | 1 | 记录为无阻断；继续基于规划文件和 git 状态恢复 |
| `rtk python3 -m unittest` 未发现测试 | 1 | 改用 `rtk python3 -m unittest discover -s tests`，94 tests passed |
| status presenter 测试误用 `AgentRunStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS.value` | 1 | 该 enum value 会归一为 `succeeded`；测试改用原始 status 字符串 `ready_for_merge_test_with_known_gaps` 保护用户可见展示 |

## 备注
- 当前仓库结构很小，优先补测试和局部实现，避免重排模块。
- 现有相关入口：`coding_orchestration/orchestrator.py`、`models.py`、`state_machine.py`、`runners/codex_cli.py`、`prompt_builder.py`、`ledger.py`。
