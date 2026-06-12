# Coding Requirement Delivery Flow

## 目标

插件支持从需求到交付的完整编排：先审查需求，判断单任务、多任务或多项目，再生成可确认的交付拆解，用户确认后物化执行任务，最后按依赖执行和汇总验收。

这套链路的重点不是让 Python 代替 Codex 做业务判断，而是把“语义判断”和“确定性编排”分开：Codex 负责分析，Hermes 负责校验、记录、调度和展示。

## 核心边界

- Codex 负责语义判断：需求分类、交付拆解、依赖、风险、验收建议。
- Hermes 负责确定性编排：校验、拒绝、落库、状态汇总、上下文裁剪、飞书展示。
- Report Admission Gate 是信任边界。Codex 输出未通过 admission gate 时，Hermes 不推进状态、不生成子任务、不进入 merge-test。
- 上下文是证据包，不是资料包。每轮只给当前决策需要的摘要、直接依赖和引用。

## 任务层级

| 层级 | task kind | 说明 |
| --- | --- | --- |
| 父级需求 | `requirement` | 承载用户原始需求、拆解报告、总体进度和验收口径。 |
| 交付单元 | `delivery_unit` | 表示业务或责任边界，用于组织执行任务。 |
| 执行任务 | `execution` | 单项目、单 repo、单 worktree，可提交、可验证。 |
| 集成验收 | `integration` | 预留给跨任务集成检查和最终验收。 |

父级需求不直接运行 implementation。实现只能发生在 execution task 上。

## 命令链路

```text
/coding task <需求>
/coding breakdown <task_id>
/coding approve-breakdown <task_id>
/coding materialize <task_id>
/coding status <task_id> --delivery
/coding status <task_id> --tree
/coding run <task_id> --next
```

典型顺序：

1. `/coding task <需求>` 创建父级需求或普通执行任务。
2. `/coding breakdown <task_id>` 让 Codex 以 decomposition RunMode 生成交付拆解。
3. `/coding approve-breakdown <task_id>` 由人确认拆解方案。
4. `/coding materialize <task_id>` 把拆解结果生成 execution 子任务。
5. `/coding run <task_id> --next` 让 Hermes 选择下一个依赖满足的子任务执行。
6. `/coding status <task_id> --delivery` 查看总体进度、阻塞点和下一步。
7. `/coding status <task_id> --tree` 查看父子任务和依赖关系。

## 单任务

单任务必须能落到一个明确项目和一个 worktree，目标、边界、依赖、验收都清楚。单任务继续复用现有链路：

```text
plan-only -> implementation -> QA -> merge-test
```

如果 Codex 在结构化 report 中判断任务适合 inline planning，Hermes 会给 implementation 轻量策略提示，而不是伪造 confirmed plan。

## 多任务和多项目

复杂需求先拆交付单元，再物化执行任务。多项目需求先按交付责任边界拆，不按 repo 直接拆。每个 execution task 必须单项目、单 repo、可提交、可验收。

拆解 report 必须说明：

- 分类结果：单任务、多任务、多项目或需要补充信息。
- 交付单元：每个单元的目标、项目边界和验收口径。
- 执行任务：每个任务的项目路径、依赖、风险和验收项。
- 依赖关系：只允许引用 report 中已经声明的执行任务。
- 风险和开放问题：不能用缺失信息创建可执行任务。

## RunMode 与状态

RunMode 表示单次 runner 执行模式，task status 表示任务下一步能否继续：

| RunMode | 作用 | 成功后的 task status |
| --- | --- | --- |
| `decomposition` | 生成需求拆解报告，不改项目文件。 | 保持父级需求可确认状态。 |
| `plan-only` | 生成计划、影响分析和执行策略。 | `planned` / `plan_ready` |
| `implementation` | 在 execution task 的 worktree 中实现。 | `ready_for_merge_test` |
| `qa` | 复用实现 worktree 做验证和证据记录。 | 保持 `ready_for_merge_test` |
| `merge-test` | 人工触发合入 test 分支。 | `merged_test` |

`run status` 不能直接等同于业务完成。Hermes 会结合 RunMode、report schema、admission gate、diff guard 和人工确认决定 task status。

## Report Admission Gate

Report Admission Gate 只做确定性校验：

- JSON 必须可解析，字段必须符合当前 RunMode 的结构化契约。
- decomposition report 必须包含交付单元、执行任务、依赖、风险、验收计划和开放问题。
- `materialization_allowed=false` 时不能创建子任务。
- 依赖引用不存在或形成环时不能创建子任务。
- 缺少 Codex 负责的语义字段时，Hermes 不推断、不兜底。

被拒绝的 report 会进入可恢复状态：用户补充信息或让 Codex 重跑 breakdown，而不是把失败结果当作成功。

## 上下文控制

`context-manifest.json` 记录每块上下文的来源、用途和估算大小。没有明确用途的上下文不能进入 prompt。

上下文裁剪规则：

- 父级需求只带需求摘要、来源索引、已确认拆解和整体状态。
- 子任务只带自身目标、直接依赖、父级验收口径和必要项目画像。
- 多项目需求不把所有 repo 全量上下文塞给 Codex。
- Codex 如果需要更多信息，必须在结构化 report 中列出开放问题或 source recovery action。

## 飞书展示

父级需求优先展示交付视图：整体进度、交付单元、阻塞点和下一步。子任务继续展示执行链路状态：计划、实现、QA、merge-test 和完成情况。

Kanban 只投影 task status，不取代 Task Ledger。层级元数据会随卡片创建同步，便于外部看板聚合父需求和子任务。
