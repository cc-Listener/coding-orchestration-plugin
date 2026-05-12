# Hermes Coding Orchestration Plugin — PLAN.md 可行性评估报告

> 审阅时间：2026-05-12
> 文件：`PLAN.md`（24 个章节，581 行）

---

## 一、整体评价

这份方案的**设计质量很高**，是一份成熟的插件架构设计文档。几个核心亮点：

- ✅ **抽象层次正确**：`CodingAgentRunner` 接口把编码工具降维成可替换执行器，Task Ledger / LLM Wiki / Project Resolver / Workspace Manager 都不绑定具体工具
- ✅ **MVP 边界清晰**：Section 22「第一版不做什么」列出了 11 条明确红线，避免过度工程
- ✅ **关注点分离干净**：Task Ledger（运行事实）vs LLM Wiki（可复用知识）的边界划分是本方案最有价值的设计决策
- ✅ **Section 0 痛点分析到位**：新增的「开发初衷与要解决的痛点」让方案有了清晰的问题导向，每个模块都能追溯到具体痛点
- ✅ **Prompt 分层策略务实**：Base Task Prompt + Runner Adapter Prompt 的分层避免了跨工具时 prompt 重写

但作为一份要落地实现的方案，**存在若干逻辑漏洞和实际应用中会遇到的边界问题**。

---

## 二、🔴 高优先级问题（4 个）

### 2.1 Task Ledger 状态机缺少转换规则和异常路径

**位置**：[Section 18, L497](file:///Users/xiaojing/Desktop/tools/hermes-codex-tools/PLAN.md#L497)

状态定义了 8 个值：`new → needs_human → planned → running → blocked → ready_for_review → done → cancelled`

**问题**：
- **没有定义合法的状态转换规则**。哪些状态之间可以互相转换？`running` 能直接到 `cancelled` 吗？`blocked` 能回到 `running` 吗？
- **缺少 `failed` 状态**。`running` 的 run 超时或崩溃后，任务应该进入什么状态？当前只有 `blocked`，但 `blocked` 语义是「等待外部条件」而不是「执行失败」
- **没有回退路径**。`ready_for_review` 如果人工审查不通过，应该回到哪？重新 `running`？还是回到 `planned` 修改方案？
- **`agent_runs[].status` 是 `string` 类型**，没有枚举约束。和 `report.json` 的 `status` 枚举（`success | failed | blocked | cancelled`）不一致

**建议**：
1. 补充状态转换矩阵（哪些 `from → to` 是合法的）
2. 增加 `failed` 状态，区分「执行失败」和「外部阻塞」
3. `agent_runs[].status` 改为和 `report.json` 一致的枚举类型
4. 定义 `ready_for_review → planned` 的回退路径

### 2.2 runner 超时和进程管理完全缺失

**位置**：[Section 10, L280-L287](file:///Users/xiaojing/Desktop/tools/hermes-codex-tools/PLAN.md#L280-L287) + [Section 6 配置, L158](file:///Users/xiaojing/Desktop/tools/hermes-codex-tools/PLAN.md#L158)

配置里有 `default_timeout_seconds: 3600`，`run-manifest.json` 里也有 `timeout_seconds`，但：

**问题**：
- **谁负责超时检测和强制终止？** `CodingAgentRunner` 接口有 `cancel()` 方法，但没有说 Hermes 何时调用它
- **runner 进程异常退出（OOM、信号中断、SSH 断连）怎么处理？** 当前没有健康检查或心跳机制
- **超时后 Task Ledger 进入什么状态？** 没有对应的状态转换规则
- **`codex_cli` 作为子进程运行时**，如果 Hermes 自身重启，正在运行的 CLI 进程怎么办？是重新拉起还是标记为 orphan？

**建议**：
1. 明确超时检测责任归属（Hermes 调度层 or runner wrapper）
2. 补充 `timeout` 后的状态转换：`running → failed (reason: timeout)`
3. 定义 Hermes 重启后的 orphan run 恢复策略（扫描 `running` 状态 + 检查进程是否存活）
4. 在 `report.json` 的 `status` 枚举中补充 `timeout`，或约定 timeout 归入 `failed`

### 2.3 Project Resolver 的匹配逻辑未定义

**位置**：[Section 7, L220-L235](file:///Users/xiaojing/Desktop/tools/hermes-codex-tools/PLAN.md#L220-L235)

`project-registry.json` 定义了 `name`、`aliases`、`keywords`，但：

**问题**：
- **匹配算法完全没定义**。飞书用户说「帮我修一下订单系统的发货模块」，Project Resolver 怎么从这句话定位到 `order-system`？是关键词精确匹配？模糊匹配？LLM 辅助判断？
- **多项目命中时怎么办？** 如果 keywords 有交集（「订单」同时出现在 order-system 和 billing-system），选哪个？
- **匹配置信度的输出和使用规则不清**。Section 19 提到「低置信度项目…回写确认卡」，但 Project Resolver 没有 confidence 输出的数据结构
- **新项目（不在 registry 里的）怎么办？** 是直接 `needs_human` 还是有别的降级策略？

**建议**：
1. 定义 `ProjectResolveResult` 结构，包含 `project_path`、`confidence`、`match_evidence`
2. 明确匹配优先级：`/coding-task --project xxx` 显式指定 > aliases 精确匹配 > keywords 匹配 > LLM 推断
3. 定义 confidence 阈值（如 <0.7 → 回写确认卡，≥0.7 → 自动路由）
4. 定义 0 匹配 / 多匹配的处理策略

### 2.4 `report.json` 的生成依赖不切实际的假设

**位置**：[Section 13, L360-L376](file:///Users/xiaojing/Desktop/tools/hermes-codex-tools/PLAN.md#L360-L376)

> 如果某个工具不能原生输出结构化结果，Runner 负责后处理 stdout/stderr，并生成标准 `report.json`。

**问题**：
- **这是整个方案最大的工程难点，但只用一句话带过了**。Codex CLI、Claude Code CLI、Gemini CLI 的 stdout 格式完全不同，都是自由文本夹杂代码块，从中可靠地提取 `modified_files`、`test_results`、`risks` 需要：
  - 要么每个 runner 写一套高质量的输出解析器（正则 / LLM 提取）
  - 要么要求 runner 以结构化模式运行（Codex 的 `--json` flag，如果有的话）
- **`test_results` 的采集尤其困难**。runner 可能运行了测试也可能没运行，测试输出混在 stdout 里，需要可靠分段
- **如果解析失败，`report.json` 的 fallback 策略是什么？** 是产出一个 `status: "unknown"` 的降级 report，还是整个 run 标记为 failed？

**建议**：
1. 为 Phase 1 的 `codex_cli` runner 明确定义 stdout 解析策略（建议优先使用 Codex 的结构化输出模式，如果没有则用 LLM 后处理）
2. 定义 `report.json` 的 fallback 结构：解析失败时产出 `{ status: "completed_unstructured", raw_stdout_ref: "stdout.log" }`
3. 在 `RunnerCapabilities` 中增加 `output_format: "structured" | "freetext"`，让 Hermes 知道是否需要后处理

---

## 三、🟡 中优先级问题（5 个）

### 3.1 并发和去重完全未覆盖

**问题**：
- 同一用户重复提交同一个需求（飞书消息重发）怎么去重？
- 两个不同任务同时修改同一个项目的同一个模块怎么处理？
- Phase 1 的 plan-only 在项目目录只读运行——如果两个 plan-only 同时跑，会不会互相干扰？（理论上只读不会，但某些工具可能写临时文件）
- Phase 2 的 workspace 隔离解决了写入冲突，但 git worktree 在同一个 repo 上并发创建也需要加锁

**建议**：
- 增加任务级去重（基于 `source.url` + `source.raw_text` 的 content hash）
- 增加项目级并发策略（同一项目同时只允许 N 个 running task，超出排队）

### 3.2 `pre_gateway_dispatch` hook 的识别逻辑是一个隐含的分类器

**位置**：[Section 4, L109](file:///Users/xiaojing/Desktop/tools/hermes-codex-tools/PLAN.md#L109)

> 插件注册 `pre_gateway_dispatch`，在普通 Hermes Agent 接手前识别编码任务。

**问题**：
- 怎么判断一条飞书消息是「编码任务」还是「普通聊天」？这本质上是一个意图分类问题
- 显式命令（`/coding-task`）好判断，但 Section 19 还提到支持「飞书需求链接、bug 链接」——这些是链接内容识别，不是命令解析
- 如果误判（把聊天当成编码任务 / 把编码任务当成聊天），后果是什么？前者会创建不必要的 Task Ledger；后者会丢失需求
- **误判的回退机制没定义**

**建议**：
1. 明确 Phase 1 只支持显式命令（`/coding-task`、飞书需求链接），不做自然语言意图识别
2. 或者定义一个两阶段识别：先 LLM 粗判 → 低置信度时回写确认卡 → 用户确认后才创建 Task

### 3.3 `codex_cli` runner 的实际调用方式未定义

**位置**：[Section 10](file:///Users/xiaojing/Desktop/tools/hermes-codex-tools/PLAN.md#L275) + [runners/codex_cli.py](file:///Users/xiaojing/Desktop/tools/hermes-codex-tools/PLAN.md#L88)

`CodingAgentRunner` 接口定义了 `prepare → run → collect_artifacts`，但 `codex_cli` 具体怎么调 Codex 没说：

- Codex CLI 的调用方式是什么？`codex --prompt "xxx"` ？`codex exec --file input-prompt.md` ？
- plan-only 模式对应 Codex 的哪个 flag？
- Codex CLI 是同步阻塞的还是后台运行？如果是阻塞的，一个 1 小时的 run 会占住 Hermes 的一个线程
- Codex CLI 运行时需要什么环境变量（API key、配置文件）？这些从哪来？

**建议**：
- 为 `codex_cli` runner 补充一个具体的「调用规范」小节，包含命令模板、环境要求、输出捕获方式
- 明确 Hermes 是同步等待还是异步轮询 runner 状态

### 3.4 Workspace Manager 的 git worktree 方案有隐含前提

**位置**：[Section 9, L266-L273](file:///Users/xiaojing/Desktop/tools/hermes-codex-tools/PLAN.md#L266-L273)

**问题**：
- git worktree 要求项目是 git 仓库——如果不是呢？fallback 到 `cp -r`？
- worktree 基于哪个分支创建？`main`？`develop`？当前活跃分支？**基分支选择策略缺失**
- worktree 创建时如果有未提交的更改，`git worktree add` 会报错
- **workspace 清理策略完全没有**。run 完成后 workspace 保留多久？磁盘空间怎么管理？谁负责清理？

**建议**：
1. 定义 workspace 创建的 fallback 链：git worktree → git clone --depth 1 → cp -r
2. 定义基分支选择策略（项目画像里增加 `base_branch` 字段）
3. 定义清理策略：`done` 后保留 N 天，`cancelled/failed` 后保留 M 天，定时清理

### 3.5 飞书交互的消息格式和错误回写未定义

**位置**：[Section 19, L513-L535](file:///Users/xiaojing/Desktop/tools/hermes-codex-tools/PLAN.md#L513-L535)

Section 19 描述了飞书交互的主流程，但：

- 「回写确认卡」的卡片格式没定义。包含什么信息？有哪些操作按钮？
- 「计划摘要和风险」的回写格式没定义
- 各类异常的飞书回写策略没定义（runner 超时、runner 崩溃、项目目录不存在、workspace 创建失败）
- `/coding-status` 返回什么格式的信息？
- `/coding-cancel` 的确认机制？直接取消还是需要二次确认？

**建议**：
- 为 Phase 1 定义 3-4 个核心飞书消息模板（任务创建确认、plan 完成报告、implementation 完成报告、错误通知）
- 异常回写可以有一个通用模板：`[任务ID] ⚠️ 异常：{reason}，当前状态：{status}`

---

## 四、🔵 低优先级问题（4 个）

### 4.1 LLM Wiki `search` 的检索质量直接影响 prompt 质量

`search(query, filters) -> WikiRef[]` 的 query 是什么？是需求原文？还是结构化后的关键词？filters 支持哪些字段过滤？检索结果的排序策略？MVP 的本地 Markdown/SQLite 实现，全文检索的质量可能很差，这会导致 LLM Wiki 虽然有知识但检索不到。

**建议**：定义 MVP 的最小检索策略（如 SQLite FTS5 全文索引 + project/module 精确过滤）

### 4.2 `WORKFLOW.md` 的解析鲁棒性

WORKFLOW.md 是 Markdown 自由格式，Workflow Loader 需要从中提取结构化的 `WorkflowSpec`。如果项目维护者写了不标准的 Markdown（如 section 名字不一致、缺失某些 section），解析器怎么降级？

**建议**：定义 WORKFLOW.md 的 schema 校验规则和部分缺失时的 fallback 默认值

### 4.3 `symphony_compat` 的命名可能造成混淆

当前团队和未来的维护者可能不熟悉 Symphony 协议。`symphony_compat` 作为子模块名称，可能让人以为需要了解 Symphony 才能理解代码。实际上这个模块做的是 Workflow + Workspace + Tracker 管理。

**建议**：考虑更直白的命名如 `workflow_engine` 或 `task_runtime`

### 4.4 项目内建议文件中 `.codex/config.toml` 绑定了 Codex

**位置**：[Section 7, L187](file:///Users/xiaojing/Desktop/tools/hermes-codex-tools/PLAN.md#L187)

```
project/
  WORKFLOW.md
  AGENTS.md
  .codex/config.toml    ← 这个目录名绑定了 Codex
```

既然方案的核心理念是不绑定 Codex，项目内的配置文件也应该保持中性。

**建议**：改为 `.coding-agent/config.toml` 或直接让 `WORKFLOW.md` 覆盖所有配置，不另加配置文件

---

## 五、逻辑一致性检查

| 检查项 | 状态 | 说明 |
|---|---|---|
| Section 0 痛点 → 模块映射 | ✅ | 7 个痛点都有对应模块解决 |
| `WorkflowSpec` 字段 ↔ `WORKFLOW.md` 字段 | ✅ | 对齐，一一对应 |
| `run-manifest.json` ↔ `report.json` 字段 | ⚠️ | manifest 有 `mode`，report 有 `mode`，一致；但 manifest 没有 `runner`，report 有 — 实际上 manifest 也有 `runner`，OK |
| Task Ledger `status` ↔ `report.json` `status` | ❌ | Task 有 8 个状态，report 有 4 个。缺少映射规则（report `success` → task `ready_for_review`？`done`？） |
| `agent_runs[].status` 类型 | ❌ | 定义为 `string`，不是枚举。和 `report.json` 的 `status` 枚举不一致 |
| Runner capabilities ↔ runner 选择策略 | ⚠️ | Section 11 说「能力不足时 needs_human」，但没说 **哪些任务需要哪些能力** |
| LLM Wiki `kind` 枚举 ↔ 写入内容命名 | ⚠️ | `WikiDoc.kind` 有 4 个值，但写入内容有 5 个名称（`coding_plan_summary` 等），两套命名体系不统一 |
| 配置中 `runners.*.command` | ⚠️ | 只有 `command` 字段太简单。Codex、Claude、Gemini 的调用方式差异很大（有的需要 flag、有的需要 stdin、有的需要 API key） |

---

## 六、实际落地风险评估

| 风险 | 影响 | 概率 | 建议 |
|---|---|---|---|
| Codex CLI stdout 解析不稳定 → report.json 不可靠 | 高 | 高 | 优先确认 Codex 是否有结构化输出模式 |
| 长时间 run 阻塞 Hermes 线程 | 高 | 中 | 明确异步执行模型 |
| Project Resolver 误路由 | 中 | 中 | Phase 1 强制显式指定项目 |
| LLM Wiki 检索质量差 → prompt 无效上下文 | 中 | 中 | MVP 用 SQLite FTS5 + 精确过滤 |
| WORKFLOW.md 格式不标准 → 解析失败 | 低 | 中 | 定义 schema + fallback 默认值 |
| workspace worktree 并发创建冲突 | 中 | 低 | 加项目级文件锁 |

---

## 七、总结

### 方案整体可行性：✅ 可行，核心架构设计正确

这份方案最大的优点是**抽象层次恰到好处**——不过度工程（不做多 runner 并发、不做自动 fallback、不做自动发布），但接口足够中性（未来扩展不需要改核心模块）。Section 0 的痛点分析和 Section 22 的「不做什么」形成了良好的问题边界。

### 需要优先补充的内容

按紧急程度排序：

| 优先级 | 问题 | 一句话描述 |
|---|---|---|
| 🔴 P0 | 2.1 状态机 | 补充合法转换矩阵 + `failed` 状态 + 回退路径 |
| 🔴 P0 | 2.2 超时管理 | 定义谁负责超时检测、超时后状态转换、orphan run 恢复 |
| 🔴 P0 | 2.4 report.json 生成 | 定义 codex_cli 的 stdout 解析策略和解析失败的 fallback |
| 🔴 P1 | 2.3 Project Resolver | 定义匹配算法、confidence 输出、多匹配/零匹配策略 |
| 🟡 P1 | 3.3 codex_cli 调用规范 | 补充具体命令模板、环境要求、同步/异步模型 |
| 🟡 P2 | 3.1 并发去重 | 定义任务去重和项目级并发控制 |
| 🟡 P2 | 3.4 workspace 清理 | 定义 worktree 创建 fallback 和清理策略 |

### 一句话结论

> **架构设计扎实，扩展思路正确，MVP 边界合理。主要风险不在架构层，而在「运行期异常处理」和「CLI 工具集成的脏活细节」——这些需要在开始编码前补充到方案中，否则 Phase 1 会在实现 codex_cli runner 时频繁遇到方案未覆盖的边界。**
