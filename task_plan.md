# 任务计划：Coding Plugin P0 实现

## 目标
实现 Hermes/Codex coding plugin P0 优化，优先用最小改动补齐自然语言 Coding Mode、语义化分支名、可见 Codex session 元数据、prepare merge test 独立阶段、report.json 兜底、细化状态机，以及验证受限结构化恢复信息。

## 当前阶段
阶段 71：runner status / task status 边界统一归一化（complete）

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
- [x] 测试：文档读取失败时 task 进入 `needs_human`，不会启动 Codex plan-only 后再 blocked。
- [x] 实现：在现有 source reader 中增加 Feishu Wiki/Doc reader，优先 Gateway adapter，兜底 `lark-cli docs +fetch --api-version v2`。
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
- [x] 实现：plan-only manifest 写入 `permission_profile=plan_read_only` 且 `dangerous_bypass=false`；外部飞书/Swagger 等上下文由 Hermes source reader 读取后注入 artifact。
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

## 备注
- 当前仓库结构很小，优先补测试和局部实现，避免重排模块。
- 现有相关入口：`coding_orchestration/orchestrator.py`、`models.py`、`state_machine.py`、`runners/codex_cli.py`、`prompt_builder.py`、`ledger.py`。
