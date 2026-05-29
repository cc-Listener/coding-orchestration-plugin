# Hermes/Codex Coding Plugin Demo Logic

更新时间：2026-05-27

这份文档记录本轮对话中沉淀出来的 Hermes/Codex coding plugin 逻辑，用于后续分享和 demo。它不是完整技术方案，而是面向讲解的产品流程、关键设计、演示脚本和风险说明。

## 1. Demo 目标

这套流程要解决的问题是：

- 用户不用手动在多个项目、Codex session、飞书上下文之间来回切换。
- Hermes 负责识别需求、维护 task 状态、沉淀上下文、调度 Codex。
- Codex 负责真实编码、测试、QA 修复和 merge-test 辅助。
- 人保留关键判断权：确认计划、触发实现、触发 merge-test、最终标记完成。

Demo 要展示的核心价值：

- 自然语言可以被 rewrite 成标准 coding 命令。
- 一个业务 task 可以跨 plan、implementation、QA、bugfix、merge-test 复用同一个 Codex session。
- 每一次执行都有独立 run artifact，便于审计和复盘。
- 自动测试链路交给 Codex + `$qa` skill，而不是 Hermes 自己写测试执行器。
- 可见 Codex session 只保留必要 prompt，不再被插件规范刷屏。

## 2. 总体角色分工

### Hermes

Hermes 是主控，不直接写业务代码。

负责：

- 接收飞书消息和 `/coding <action>` 命令。
- 维护 Task Ledger。
- 识别项目、补全项目路径、维护 active task binding。
- 调用 LLM rewrite，把 Coding Mode 自然语言改写为标准命令。
- 生成 run artifact、manifest、schema、prompt。
- 调度 Codex CLI runner。
- 回收 stdout、stderr、report、summary、diff、QA artifact。
- 根据 report 和 diff guard 更新 task 状态。
- 将长期经验写入 LLM Wiki。

### Codex

Codex 是执行 runner，不直接决定业务流程。

负责：

- 阅读当前 task 的必要上下文。
- 产出 plan。
- 按已确认 plan 实现代码。
- 使用 `$qa` skill 进行测试、浏览器 QA、修复和复验。
- 使用 `merge-to-test` skill 辅助合并到 test。
- 输出结构化 report。

### 人

人负责关键确认：

- 确认 plan 是否可以进入 implementation。
- 对需求变更使用 `/coding change`。
- 对实现或 QA 反馈使用 `/coding bugfix`。
- 手动触发 `/coding merge-test`。
- 合入 test 后手动 `/coding complete`。

## 3. 标准命令体系

新流程只保留一种命令入口：

```text
/coding <action>
```

已经移除旧兼容命令：

```text
/coding-*
/codex-*
```

常用动作：

```text
/coding task <需求>
/coding run <task_id>
/coding continue <反馈>
/coding change <需求变更>
/coding bugfix <实现或 QA 反馈>
/coding implement <task_id>
/coding prepare-merge-test <task_id>
/coding merge-test <task_id>
/coding complete <task_id>
/coding list
/coding status <task_id>
/coding use <task_id>
/coding exit
/coding cancel <task_id>
/coding delete <task_id>
```

当前尚未单独暴露纯 QA 命令：

```text
/coding qa <task_id>
```

现有 QA 触发方式是：

- implementation 成功后自动追加 QA run。
- 如果只是想重跑测试，当前需要通过 implementation/bugfix 链路间接触发。
- 后续建议新增 `/coding qa <task_id>` 或 `/coding test <task_id>`，直接复用 task workspace 和 Codex session 运行 `RunMode.QA`。

## 4. Coding Mode 自然语言 rewrite

默认情况下，普通自然语言不会进入 plugin，仍交给 Hermes 主 agent。

用户显式发送：

```text
进入coding
```

后，同会话进入 Coding Mode。此时自然语言会先交给 LLM rewrite，生成一个标准 `/coding <action>` 候选。

退出：

```text
退出coding
```

### Rewrite 原则

- LLM 只负责改写，不负责执行。
- Hermes 校验 LLM 输出是否合法。
- 高置信度且信息完整时直接执行。
- 低置信度、缺信息或高风险操作要人工确认。
- destructive 动作，例如 delete/cancel，即使置信度高也要确认。
- 不明确的自然语言不能创建 task。

### 典型例子

查询类：

```text
用户：现在有多少个 task
rewrite：/coding list
结果：只展示列表，不创建 task
```

当前 task 的修复反馈：

```text
用户：截图里的样式不对，按图修一下
rewrite：/coding bugfix 截图里的样式不对，按图修一下
结果：写入 implementation_feedback，复用当前 task 进入 implementation/QA
```

需求变更：

```text
用户：这个需求改一下，先只做列表，弹窗先不做
rewrite：/coding change 先只做列表，弹窗先不做
结果：回到 plan-only 做变更影响分析，不直接实现
```

## 5. Task、Run、Session 的关系

这是 demo 中最容易解释清楚的核心概念。

### Task

Task 是一个业务需求。

例如：

```text
task_41c786eddf54
```

Task 记录：

- 需求摘要
- 项目路径
- 当前状态
- 人工反馈
- source branch
- worktree path
- runner session id
- 所有 run 记录

### Run

Run 是一次执行记录。

一个 task 可以有多个 run，这是正常的：

- plan-only run
- implementation run
- retry implementation run
- QA run
- bugfix run
- merge-test run

每个 run 都有独立 artifact，方便审计：

```text
runs/<task_id>/<run_id>/
```

### Codex Session

Codex session 是给同一个 task 复用的长期对话上下文。

目标：

- 一个 task 尽量只维护一个 Codex session。
- 多个 run 复用同一个 session。
- 后续 run 只给增量内容，不重复塞大上下文。

进入 session：

```bash
rtk codex resume <session_id>
```

`session_id` 可以从 task status、ledger 或 run manifest 里找到。

## 6. Run Artifact 设计

每次 run 都会生成独立 artifact：

```text
input-prompt.md
run-instructions.md
run-manifest.json
report.schema.json
stdout.log
stderr.log
events.jsonl
report.json
summary.md
diff.patch
context-index.json
wiki-context.md
confirmed-plan.md
implementation-context.md
```

核心文件含义：

| 文件 | 作用 |
| --- | --- |
| `input-prompt.md` | 给 Codex visible session 的最小 prompt |
| `run-instructions.md` | 详细执行契约、状态返回规则、report 输出要求 |
| `run-manifest.json` | run 元数据、workspace、branch、session、权限信息 |
| `report.schema.json` | Codex 输出结构化 report 的 schema |
| `report.json` | 本次 run 的结构化结果 |
| `summary.md` | 给人看的摘要 |
| `diff.patch` | diff guard 和审计依据 |
| `context-index.json` | 本次 run 的上下文索引 |
| `wiki-context.md` | LLM Wiki 相关上下文 |
| `confirmed-plan.md` | implementation 需要引用的已确认计划 |
| `implementation-context.md` | QA / merge-test 需要引用的实现上下文 |

## 7. Prompt 策略

本轮对话中最重要的优化之一：不要把插件规范一股脑塞进 Codex visible session。

### 旧问题

用户进入 Codex session 后，会看到大量机器化输入：

- 插件状态机说明
- report JSON 字段说明
- verification limitations 结构
- 权限边界
- QA 规则
- merge-test 规则

这对机器编排有用，但对人查看 session 很吵。

### 新策略

`input-prompt.md` 只保留：

- task id
- 当前 Codex session id
- 本轮新增人工反馈
- 本轮动作
- 必要上下文 artifact 路径

详细规范移入：

```text
run-instructions.md
```

### 增量 prompt 示例

```markdown
# 编码任务增量

## 复用任务 Session 的本轮增量
- Task：`task_xxx`
- 既有 Codex session：`019e...`

## 本轮新增信息
- 人工反馈 implementation_feedback：截图里的 grouped_items 样式不对

## 本轮动作
- 按已确认计划实现；缺少依赖时先安装并继续验证；不要发布、部署或 merge。

## 相关上下文
- 上下文索引：`.../context-index.json`
- 已确认计划：`.../confirmed-plan.md`
- 运行说明：`.../run-instructions.md`
```

## 8. 状态机

用户侧只看 `TaskStatus`，中文展示格式为：

```text
中文标识(英文 code)
```

主要状态：

| 状态 | 中文标识 | 含义 |
| --- | --- | --- |
| `new` | 新建 | task 已创建 |
| `needs_human` | 待人工确认 | 缺项目、需求或权限信息 |
| `planned` | 已规划 | plan-only 完成，等待人工确认实现 |
| `queued` | 排队中 | run 已排队 |
| `running` | 运行中 | run 正在执行 |
| `ready_for_merge_test` | 等待手动执行 merge test | 开发和验证通过，等待人工 merge-test |
| `ready_for_merge_test_with_known_gaps` | 待合并测试（有已知缺口） | 开发完成，但测试/环境存在已知缺口 |
| `merged_test` | 已合并 test，待人工完成 | 已合入 test，但 task 还未人工完成 |
| `done` | 已完成 | 人工确认完成 |
| `blocked` | 受阻 | 缺关键人工输入或无法安全继续 |
| `runner_failed` | Runner 失败 | runner 启动或执行失败 |
| `failed` | 失败 | 执行失败 |
| `cancelled` | 已取消 | 被取消 |

关键口径：

- 开发完成并验证成功后进入 `ready_for_merge_test`。
- 开发完成但验证受限进入 `ready_for_merge_test_with_known_gaps`。
- merge-test 成功后进入 `merged_test`，不直接 done。
- 只有用户显式 `/coding complete <task_id>` 后才进入 `done`。

## 9. 自动 QA 链路

Hermes 不自研测试执行器。

自动测试交给：

```text
Codex + $qa skill
```

Hermes 负责：

- 启动 QA run。
- 复用 task Codex session。
- QA 前创建 checkpoint commit。
- 回收 `.gstack/qa-reports`、baseline、screenshots。
- 记录 tested commit。
- 根据 QA report 更新 task 状态。
- 在 merge-test 前展示 QA 证据。

Codex 负责：

- 安装缺失依赖。
- 运行项目测试、typecheck、build。
- 启动 dev server。
- 执行浏览器 QA。
- 截图留证。
- 修复 QA 发现的问题。
- 复验。

QA 证据不是 merge-test 的硬前置：

- 没有 QA run 时允许继续，但提示缺少自动 QA 证据。
- QA failed、blocked、known gaps、证据过期时，要求人工显式确认风险后继续。

## 10. 权限模型

### plan-only

只读：

```text
read-only sandbox
```

只做计划，不写文件。

### implementation / QA

使用受控高权限：

```text
--dangerously-bypass-approvals-and-sandbox
```

原因：

- 依赖安装可能写全局 pnpm/npm cache。
- 私有源访问需要网络。
- dev server 和浏览器 QA 需要端口和临时文件。
- QA 报告写 `.gstack`。
- git worktree commit 需要写 `.git/worktrees/...`。

边界：

- Codex 子进程 cwd 固定为 task worktree。
- 源码修改只允许落在当前 workspace。
- 项目外写入只允许依赖缓存、git metadata、dev server/browser 临时文件、QA artifact。
- Hermes diff guard 继续审计 workspace 内 diff。

## 11. Project 补充逻辑

如果 Hermes 无法从需求里识别项目，会进入：

```text
needs_human
```

用户补充：

```text
项目为 oms 后台，文件夹名称为 `oms_operation_web`
```

Hermes 会：

- 定位本地项目目录。
- 回填 `project_path`。
- 更新 `source.project_name`。
- 更新 `task_session.project_name`。
- 写入 LLM Wiki `project_profile`。
- 自动继续 plan-only。

这是 demo 中非常适合展示的能力：项目补充不是只写一段文本，而是结构化回填。

## 12. Figma / 图片 / 附件逻辑

### Figma

需求里有 Figma 链接时，Codex 可以通过已安装的 Figma plugin 获取设计上下文。

前提：

- Codex 环境里已安装 Figma plugin。
- Prompt 或上下文中包含 Figma URL。
- 必要时 Codex 使用 Figma MCP 获取截图、节点、设计上下文。

### 图片反馈

如果用户发 bugfix/change 并带图片：

- Hermes 保存 `media_urls` 和 `media_types`。
- 写入 human decision。
- 写入 LLM Wiki draft。
- 增量 prompt 中转成自然语言附件说明。

如果只有 `[Image]` 占位但 Hermes 没拿到 media：

- 不启动 Codex。
- 提示用户重发图片、图片链接或文字描述。

## 13. List 输出格式

`/coding list` 输出当前未结束 task。

格式：

```text
当前未结束 coding task：

id: task_xxx
状态: 等待手动执行 merge test(ready_for_merge_test)
项目: bps-admin
任务描述: 一句话总结

tip: 当前会话绑定：无;使用 /coding use <task_id> 切换当前任务。
```

设计原则：

- 不输出长路径作为主信息。
- 不展示大段需求。
- 任务描述必须一句话总结。
- `merged_test` 也属于未结束 task，直到人工 `/coding complete`。

## 14. Reset 清理逻辑

为了 demo 可以从零开始，已封装 `hermes-coding-reset` skill。

清理范围：

- `ledger.db`
- `runs/`
- `workspaces/`
- `llm-wiki/`

保留：

- `project-registry.json`

命令：

```bash
rtk python3 ~/.codex/skills/hermes-coding-reset/scripts/reset_hermes_coding_records.py
rtk python3 ~/.codex/skills/hermes-coding-reset/scripts/reset_hermes_coding_records.py --yes
rtk hermes gateway restart
```

验证：

```bash
rtk proxy curl -sS http://127.0.0.1:8642/health
rtk sqlite3 ~/.hermes/coding-orchestration/ledger.db "select count(*) from tasks; select count(*) from active_task_bindings;"
```

预期：

```text
0
0
```

## 15. 推荐 Demo 脚本

### 15.1 从零开始

```text
清除历史 coding 记录
重启 Hermes
确认 /coding list 为空
```

### 15.2 进入 Coding Mode

```text
进入coding
```

展示：

- Hermes 回复已进入 coding。
- 后续自然语言会先 rewrite。

### 15.3 查询 task 数量

```text
现在有多少个 task
```

预期：

- rewrite 为 `/coding list`。
- 不创建 task。

### 15.4 创建新任务

自然语言描述需求，例如：

```text
OMS 后台订单 2.0 改版，按照 Figma 设计实现订单管理新列表，先只做列表主链路，弹窗后续再做。
Figma: https://www.figma.com/design/...
```

预期：

- 高置信度 rewrite 为 `/coding task <需求>`。
- 创建 task。
- 如果项目不明确，进入 `needs_human`。

### 15.5 补充项目

```text
项目为 oms 后台，文件夹名称为 `oms_operation_web`
```

预期：

- 回填项目路径。
- 写入 LLM Wiki project_profile。
- 自动进入 plan-only。

### 15.6 查看计划

等待 plan-only run 完成。

展示：

- task id
- 状态
- plan 摘要
- artifact 路径
- Codex session id / attach command

### 15.7 进入 Codex session

```bash
rtk codex resume <session_id>
```

展示：

- session 里看到的是干净的最小 prompt。
- 不再有大段插件规范。
- 详细规则在 `run-instructions.md`。

### 15.8 人工确认实现

```text
/coding implement <task_id>
```

预期：

- 复用同一个 Codex session。
- 创建 implementation run。
- 使用 task worktree。
- 缺依赖时 Codex 会尝试安装。
- 实现完成后自动进入 QA run。

### 15.9 QA run

预期：

- Codex 使用 `$qa`。
- 运行测试、typecheck、build、浏览器 QA。
- 发现问题可修复并复验。
- 回收 QA report、baseline、screenshots。

### 15.10 手动 merge-test

```text
/coding merge-test <task_id>
```

预期：

- 展示 QA 证据。
- 续接同一个 Codex session。
- 使用 `merge-to-test` skill。
- 成功后进入 `merged_test`。

### 15.11 人工完成

```text
/coding complete <task_id>
```

预期：

- task 进入 `done`。
- `/coding list` 不再显示该 task。

## 16. 分享时的关键讲解点

### 为什么一个 task 有多个 run

因为 task 是业务需求，run 是每次执行记录。

多个 run 是审计能力，不是重复 task：

- 每次执行都有独立 report。
- 每次失败和重试都能追踪。
- 每次 QA 和 merge-test 都能复盘。

### 为什么一个 task 只维护一个 Codex session

因为 Codex session 是上下文记忆。

复用 session 可以：

- 减少重复塞上下文。
- 保持实现、QA、bugfix 连贯。
- 用户可以进入同一个 session 查看过程。

### 为什么 prompt 要瘦身

因为 visible Codex session 是人会看的。

机器规范应该进入 artifact：

- `run-instructions.md`
- `report.schema.json`
- `run-manifest.json`

visible prompt 只保留：

- 本轮要干什么
- 本轮新增信息
- 必要上下文路径

### 为什么 implementation/QA 要高权限

真实自动测试不是只改代码。

它需要：

- 安装依赖
- 写缓存
- 启动 dev server
- 打开浏览器
- 写 QA 报告
- 写 git worktree metadata

所以使用 bypass，但通过 worktree、manifest、prompt、diff guard 收口风险。

## 17. 当前已知缺口

- 还没有单独 `/coding qa <task_id>` 入口。
- run timeline 和 command duration 还未完整落地。
- merge-test preflight 还可继续增强。
- bypass 是能力放开，不是 OS 级强隔离；仍依赖工作目录和 diff guard 兜底。
- 真实端到端 demo 需要确认项目依赖源、登录态、Figma 权限和浏览器 QA 环境。

## 18. Demo 一句话总结

Hermes 不是替 Codex 写代码，而是把飞书里的自然语言需求变成一个可追踪、可恢复、可审计的 coding workflow；Codex 专注执行，人保留关键决策，所有过程都沉淀为 task、run、session 和 artifact。
