# coding_orchestration 插件工作场景与复刻案例

本文用于复刻 `coding_orchestration` plugin 覆盖的主要工作流。案例默认在飞书或 Hermes Gateway 对话中执行；Hermes 主 agent 也可以直接调用同名 native tool。

## 复刻前置条件

- Hermes 已通过本仓库软链接加载 `coding_orchestration`，并已重启 Gateway。
- `/commands` 能看到 `/coding help`、`/coding task`、`/coding project list`、`/coding status`、`/coding delete`。
- `CODEX_CLI_COMMAND` 指向可用 Codex CLI 绝对路径。
- `lark-cli` 默认 appId 与 Hermes `FEISHU_APP_ID` 一致，并已授权 Docx/Wiki 读取 scope。
- 飞书项目 MCP 如需启用，只配置插件运行根下的 `mcp.json`，不改 Hermes 全局环境：

```json
{
  "mcpServers": {
    "feishu-project": {
      "enabled": true,
      "command": "npx",
      "args": ["-y", "@lark-project/mcp"],
      "domain": "https://project.feishu.cn",
      "env": {
        "MCP_USER_TOKEN": "<MCP_USER_TOKEN_VALUE>"
      }
    }
  }
}
```

文件路径固定为 `~/.hermes/coding-orchestration/mcp.json`。配置后执行：

```bash
rtk chmod 600 ~/.hermes/coding-orchestration/mcp.json
rtk hermes gateway restart
rtk hermes coding project-mcp-preflight
```

不要把真实 token 写入仓库、`.env`、prompt、测试 fixture、日志或 LLM Wiki。

## 任务分级

分级用于安排演示顺序和验收门槛。推荐从 L0 到 L5 逐级复刻，不要直接从生产空间跑 L4/L5 写操作。

| 级别 | 名称 | 典型场景 | 允许写入 | 人工门禁 | 达标后可进入 |
| --- | --- | --- | --- | --- | --- |
| L0 | 环境与权限预检 | 插件加载、Codex、Lark、飞书项目 MCP preflight | 无 | 无 | L1 |
| L1 | 只读来源解析 | 飞书 Wiki/Docx/Project URL 解析、工作项查询 | 无 | 无 | L2 |
| L2 | Hermes 本地任务编排 | 项目画像、创建 task、plan-only、状态查询、Coding Mode rewrite | Task Ledger / LLM Wiki / run artifacts | plan 进入实现前需人工确认 | L3 |
| L3 | 受控编码闭环 | implementation、QA、merge-test、complete、bugfix 反馈 | task workspace、git metadata、QA artifacts | implementation、merge-test、complete 均需人工触发 | L4 |
| L4 | 飞书项目受控写入 | 创建需求、WBS 草稿/发布、状态流转、评论回写 | 飞书项目 MCP 写操作 | 必须 `confirm_write=true` | L5 |
| L5 | 跨系统交付闭环 | Story intake -> Hermes root task -> WBS/child task -> bugfix intake -> merge-test | L2-L4 全部范围 | 每个写入边界独立确认 | 团队试运行 |

## 场景总览

| 级别 | 场景 | 入口 | 主要结果 | 写入风险 |
| --- | --- | --- | --- | --- |
| L0 | 插件安装与健康检查 | `/coding doctor`、`coding_lark_preflight`、`coding_project_mcp_preflight` | 检查 Hermes、Codex、Lark、飞书项目 MCP 可用性 | 只读 |
| L2 | 项目画像接入 | `/coding project init/use/list/status/clear` | 建立 active_project 和 LLM Wiki `project_profile` | 写 LLM Wiki |
| L2 | 普通需求建单 | `/coding task`、`coding_task_create` | 创建 Hermes task，进入 plan-only | 写 Task Ledger / LLM Wiki |
| L1/L2 | 飞书 Wiki/Docx/Project 来源索引 | `/coding task <url>`、`coding_source_resolve` | 记录来源 URL、token、恢复动作 | 写 Task Ledger |
| L2 | Coding Mode 自然语言 | `进入coding` 后自然语言 | rewrite 成标准 `/coding <action>` | 视命令而定 |
| L2 | 计划补充与需求变更 | `/coding continue`、`/coding change` | 重跑 plan-only 或变更影响分析 | 写 Task Ledger / run artifacts |
| L3 | 实现、QA、合 test | `/coding implement/qa/merge-test/complete` | Codex 在 workspace 开发、QA、合入 test、人工完成 | 改项目 workspace / git |
| L2/L3 | 复杂需求拆解 | `/coding breakdown/approve-breakdown/materialize/run --next` | 父需求拆成 execution 子任务并按依赖推进 | 写 Task Ledger |
| L1 | 飞书项目查询 | `coding_project_workitem_search` | 用 MCP 查询 Story / Issue / Task | 只读 |
| L4 | 飞书项目创建需求 | `coding_project_workitem_create` | 显式确认后创建飞书项目工作项 | 需要 `confirm_write=true` |
| L2/L4 | 特定状态需求同步 | `coding_project_intake_sync` | 拉取特定状态 Story 并创建 Hermes task | 可只 dry-run |
| L4 | WBS 拆解与工时回写 | `coding_project_wbs_update` | 创建/编辑/发布 WBS 草稿，记录估时/实际工时 | 需要 `confirm_write=true` |
| L4 | 状态流转 | `coding_project_state_transition` | 检查必填字段和可流转状态后推进状态 | 需要 `confirm_write=true` |
| L3/L4 | Bugfix intake | `coding_project_bugfix_intake` | 拉取 Issue，创建 bugfix task，关联主需求或标记待补链 | 状态流转需要确认 |
| L2/L3 | 取消、恢复、删除 | `/coding cancel/restore/delete` | 停止 run、恢复 cancelled task、清理 task | delete 是 destructive |

## Demo 套件与验收标准

### Demo 0：L0 环境预检

输入：

```text
/coding doctor
```

```json
{
  "tool": "coding_project_mcp_preflight",
  "arguments": {
    "include_tools": true
  }
}
```

预期输出：

- `/coding doctor` 展示 Hermes Gateway、Codex CLI、Lark 文档 scope 和恢复动作。
- MCP preflight 返回 `ok=true`、`transport`、`domain`、`allowed_tools`。

达标标准：

- `/coding help` 可用，Gateway 不报插件加载错误。
- Codex CLI 路径是绝对路径且可执行。
- Lark appId 与 Hermes `FEISHU_APP_ID` 一致。
- 输出中不出现真实 token、auth 文件内容、`.env` 内容或 `MCP_USER_TOKEN` 值。

不达标判定：

- 任一 preflight 缺少明确恢复动作。
- MCP preflight 把 token 或 token-like 字符串返回给用户。

### Demo 1：L1 飞书项目只读查询

输入：

```json
{
  "tool": "coding_project_workitem_search",
  "arguments": {
    "space": "BPS空间",
    "workitem_type": "需求",
    "query": "状态 = 待开发",
    "limit": 3
  }
}
```

预期输出：

```json
{
  "ok": true,
  "items": [
    {
      "title": "订单列表新增店铺筛选",
      "workitem_type": "story",
      "status": "待开发",
      "url": "https://project.feishu.cn/z9b9t3/story/detail/..."
    }
  ]
}
```

达标标准：

- 只调用 MCP `search_by_mql`。
- 返回结果数量不超过 `limit`。
- 每条结果至少包含标题、类型、状态或 URL 中的三项。
- 不创建 Hermes task，不新增 `project_workitem_bindings`。

不达标判定：

- 查询触发任何写操作。
- 查询失败但没有给出空间、权限、MQL 或 MCP 可用性的具体排障方向。

### Demo 2：L2 普通需求进入 Hermes plan-only

输入：

```text
/coding project use bps-admin
/coding task 订单列表新增店铺筛选，支持店铺名模糊搜索
```

预期输出：

```text
[task_xxx] 已记录新任务：订单列表新增店铺筛选...
状态：已规划(planned) 或 计划已就绪(plan_ready)
下一步：确认计划后发送 /coding implement task_xxx
```

达标标准：

- 创建唯一 `task_id`。
- Task Ledger 记录 requirement、project、runner、active binding。
- plan-only 不修改项目源码。
- run artifacts 至少包含 `input-prompt.md`、`run-instructions.md`、`run-manifest.json`。
- plan 完成后必须给出下一步命令，不自动进入 implementation。

不达标判定：

- 无项目上下文时静默猜项目并启动任务。
- plan-only 改动项目文件。
- 未经人工确认直接开始实现。

### Demo 3：L2 飞书项目 Story 建 root task

输入：

```text
/coding task BPS运营后台 https://project.feishu.cn/z9b9t3/story/detail/6983769492
```

预期输出：

```text
[task_xxx] 已记录飞书项目需求来源
来源：story/detail/6983769492
下一步：等待 plan 或发送 /coding breakdown task_xxx
```

达标标准：

- Story URL 被解析为 domain、space key、workitem type、workitem id。
- `project_workitem_bindings` 中写入 `relation_kind=source_requirement`。
- root task 的 `root_task_id` 指向自身。
- 无法读取 Story 正文时，仍保留 URL 和恢复动作，不把正文内容猜进 prompt。

不达标判定：

- Story 和 Hermes task 没有关联记录。
- 读取失败直接丢失来源 URL。

### Demo 4：L3 受控实现、QA 与合 test

输入：

```text
/coding implement task_xxx
/coding qa task_xxx
/coding merge-test task_xxx
/coding complete task_xxx
```

预期输出：

```text
[task_xxx] implementation run 已完成
状态：待合测试(ready_for_merge_test)
[task_xxx] merge-test 已完成
状态：已合测试(merged_test)
[task_xxx] 已完成(done)
```

达标标准：

- `implement` 只允许在 `plan_ready` 后启动。
- Codex cwd 固定为 task workspace。
- implementation report 包含实现摘要、测试命令、变更是否落地、已知缺口。
- QA 失败时不直接放行 merge-test。
- merge-test 后只标记 `merged_test`，必须人工 `/coding complete` 才是 `done`。

不达标判定：

- Codex 在主 checkout 直接改代码。
- 缺 report 或 diff guard 失败仍自动推进。
- 自动发布生产环境。

### Demo 5：L4 创建飞书项目需求

输入一：未确认写入。

```json
{
  "tool": "coding_project_workitem_create",
  "arguments": {
    "space": "BPS空间",
    "workitem_type": "需求",
    "title": "订单列表新增店铺筛选",
    "fields": {
      "优先级": "P1"
    }
  }
}
```

预期输出：

```json
{
  "ok": false,
  "status": "confirmation_required"
}
```

输入二：确认写入。

```json
{
  "tool": "coding_project_workitem_create",
  "arguments": {
    "space": "BPS空间",
    "workitem_type": "需求",
    "title": "订单列表新增店铺筛选",
    "fields": {
      "优先级": "P1"
    },
    "confirm_write": true,
    "idempotency_key": "bps-admin-order-shop-filter-20260615"
  }
}
```

达标标准：

- 未传 `confirm_write=true` 时不调用 MCP 写工具。
- 确认后只调用 `create_workitem`，并返回工作项 URL 或可追踪 id。
- 同一个 `idempotency_key` 的重试不应造成不可控重复创建。
- 审计输出不包含 token。

不达标判定：

- 无确认即创建飞书项目工作项。
- 写入失败没有明确字段、权限或状态原因。

### Demo 6：L4 WBS 拆解与工时回写

输入：

```json
{
  "tool": "coding_project_wbs_update",
  "arguments": {
    "workitem_url": "https://project.feishu.cn/z9b9t3/story/detail/6983769492",
    "rows": [
      {
        "name": "后端接口开发",
        "owner": "张三",
        "schedule": "2026-06-15~2026-06-16",
        "estimate": 2,
        "actual_hours": 0
      },
      {
        "name": "前端筛选联调",
        "owner": "李四",
        "schedule": "2026-06-16~2026-06-17",
        "estimate": 1.5,
        "actual_hours": 0
      }
    ],
    "publish": true,
    "confirm_write": true
  }
}
```

达标标准：

- 调用顺序为 `create_wbs_draft`、`edit_wbs_draft`、`publish_wbs_draft`。
- 每个 row 至少有名称、负责人、排期、估时。
- 返回每个 row 的 row id 或可追踪结果。
- WBS row 可通过 `project_workitem_bindings` 与 Hermes child task 对应。

不达标判定：

- 未确认写入就创建或发布 WBS。
- 估时字段丢失，或 publish 失败后仍报告成功。

### Demo 7：L4 状态流转

输入：

```json
{
  "tool": "coding_project_state_transition",
  "arguments": {
    "workitem_url": "https://project.feishu.cn/z9b9t3/story/detail/6983769492",
    "target_state": "开发中",
    "fields": {
      "负责人": "张三"
    },
    "confirm_write": true
  }
}
```

达标标准：

- 先调用 `get_transition_required`。
- 再调用 `get_transitable_states`。
- 目标状态存在且必填字段齐全后才调用 `transition_state`。
- 缺字段时返回 `missing` 和恢复动作，不做状态写入。

不达标判定：

- 未检查必填字段直接流转。
- 目标状态不可达仍调用写操作。

### Demo 8：L5 Story -> 子任务 -> Bugfix 闭环

输入：

```text
/coding task BPS运营后台 https://project.feishu.cn/z9b9t3/story/detail/6983769492
/coding breakdown task_root
/coding approve-breakdown task_root
/coding materialize task_root
/coding run task_root --next
```

随后拉取 Bug：

```json
{
  "tool": "coding_project_bugfix_intake",
  "arguments": {
    "space": "BPS空间",
    "workitem_type": "issue",
    "query": "状态 = 待处理",
    "transition_to": "处理中",
    "max_items": 3,
    "dry_run": false,
    "confirm_write": true
  }
}
```

达标标准：

- Story 绑定 root requirement task。
- breakdown 先生成报告，只有 approve 后才能 materialize。
- child task 有依赖关系，`run --next` 只运行依赖满足的任务。
- 已关联 Story 的 Issue 创建 bugfix task 时继承 root task 的 `source_branch`，`branch_policy=inherit_root_branch`。
- 未关联 Story 的 Issue 创建独立 root bugfix task，`branch_policy=own_branch`，binding metadata 写入 `needs_story_link=true`。
- bugfix 完成评论回写必须脱敏，不暴露 token 或敏感 env。

不达标判定：

- 父需求直接进入 implementation。
- 每个 bugfix 都无条件开独立主分支。
- 未关联 Story 的 bugfix 没有人工补链标记。

## 总体验收达标标准

一轮 Demo 验收通过需要同时满足：

- L0-L2 全部通过，且至少一条 L3 编码闭环通过。
- 如果启用飞书项目 MCP，至少完成一个 L1 查询 Demo；写操作只在测试空间完成。
- L4 写操作全部证明 `confirm_write=true` 门禁有效。
- Task Ledger 能查到 task、run、artifact、active binding 和 project workitem binding。
- 飞书项目 Story、WBS、Issue 与 Hermes task 的对应关系可解释、可追踪。
- 所有用户可见回复都给出下一步动作或失败恢复动作。
- 全流程不泄露 token、auth、`.env*`、本地运行根私密内容。
- 失败场景不会静默成功，也不会把 source/auth/permission 问题误标成普通实现完成。

## 详细复刻脚本

### 1. 安装后健康检查

目标：确认插件、Lark 文档权限和飞书项目 MCP 可用。

```text
/coding doctor
```

Hermes native tool 复刻：

```json
{
  "tool": "coding_lark_preflight",
  "arguments": {}
}
```

```json
{
  "tool": "coding_project_mcp_preflight",
  "arguments": {
    "include_tools": true
  }
}
```

预期检查点：

- 返回 Codex CLI、Hermes Gateway、Lark 文档读取状态。
- MCP preflight 返回 `transport`、`domain` 和允许工具列表。
- 输出中不出现 token、`MCP_USER_TOKEN` 或 token 值。

### 2. 接入一个本地项目画像

目标：让后续需求不必每次重复说明本地 repo 路径。

```text
/coding project init /Users/xiaojing/Desktop/project/bps-admin
/coding project status
```

或使用已有画像：

```text
/coding project list
/coding project use bps-admin
```

预期检查点：

- `project status` 显示 active_project。
- LLM Wiki 中出现或刷新 `project_profile`。
- 后续 `/coding task` 未显式写 `--project` 时，会优先使用 active_project。

### 3. 普通需求创建与 plan-only

目标：从飞书消息创建 Hermes coding task，并自动生成 plan。

```text
/coding task BPS运营后台订单列表新增店铺筛选，支持按店铺名模糊搜索
```

Hermes native tool 复刻：

```json
{
  "tool": "coding_task_create",
  "arguments": {
    "requirement": "BPS运营后台订单列表新增店铺筛选，支持按店铺名模糊搜索",
    "project": "bps-admin",
    "runner": "codex_cli"
  }
}
```

预期检查点：

- 返回 `task_id`，状态通常为 `planned` 或 plan run 后的 `plan_ready`。
- Task Ledger 记录 requirement、project、runner、active binding。
- run artifacts 中出现 `input-prompt.md`、`run-instructions.md`、`run-manifest.json`。

### 4. 飞书 Wiki / Docx 来源需求

目标：需求正文在飞书文档里，Hermes 只索引来源，Codex 在 plan-only 中读取。

```text
/coding task fulfill-ui 嵌入式界面新增引导 https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe
```

只解析来源：

```json
{
  "tool": "coding_source_resolve",
  "arguments": {
    "url": "https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe"
  }
}
```

预期检查点：

- source context 记录 URL、document token、document kind。
- 如果 Hermes 层读不到正文，不直接把任务打成 blocked；会记录 `deferred_source_resolution` 和恢复动作。
- Codex plan-only prompt 中包含 `lark_cli_command`，要求 Codex 自行读取。

### 5. 飞书项目 Story 创建 Hermes 需求

目标：从飞书项目需求链接创建 root task，并建立 Story 到 Hermes task 的绑定。

```text
/coding task BPS运营后台 https://project.feishu.cn/z9b9t3/story/detail/6983769492
```

预期检查点：

- Task source 标记为飞书项目工作项来源。
- `project_workitem_bindings` 中 Story 以 `source_requirement` 关联 root task。
- 后续 WBS 行和 bugfix 可以通过该绑定找到 root task、source branch 和父子关系。

### 6. Coding Mode 自然语言复刻

目标：在同一飞书会话中用自然语言触发标准命令。

```text
进入coding
```

随后发送：

```text
订单列表筛选这里实现不对，后端字段是 shop_name，按这个修一下
```

预期检查点：

- 高置信度时 rewrite 为 `/coding bugfix 订单列表筛选这里实现不对...` 并直接执行。
- 低置信度时不会创建 task，不会启动 Codex，会把上下文交给 Hermes 主 agent。
- `cancel`、`delete` 等高风险动作即使高置信度也需要确认。

### 7. Plan 反馈与需求变更

目标：在进入实现前补充计划，或需求变更后重新分析影响。

```text
/coding continue task_xxx 只处理订单列表页，不改导出接口
```

```text
/coding change task_xxx 需求改成同时支持订单标签和商品标签，需要评估 API 和前端影响
```

预期检查点：

- `continue` 适合补充 plan 约束。
- `change` 适合需求范围变化，会进入变更影响分析和短计划。
- 两者都不直接绕过 plan gate 进入 implementation。

### 8. 人工确认后进入实现

目标：确认 plan 后让 Codex 在隔离 workspace / source branch 中开发。

```text
/coding implement task_xxx
```

Hermes native tool 复刻：

```json
{
  "tool": "coding_task_run",
  "arguments": {
    "task_id": "task_xxx",
    "mode": "implementation"
  }
}
```

预期检查点：

- 只有 task 已经 `plan_ready` 才能进入实现。
- Codex cwd 是该 task 的 workspace，不是仓库主 checkout。
- run-manifest 记录权限 profile、workspace、source branch 和修改边界。
- 完成后 diff guard 检查路径边界，report 必须说明实现是否落地。

### 9. QA 与合入 test

目标：实现完成后进行 QA，再人工触发 merge-to-test。

```text
/coding qa task_xxx
/coding prepare-merge-test task_xxx
/coding merge-test task_xxx
```

如果存在风险但人工接受：

```text
/coding merge-test task_xxx --accept-risk
```

测试环境确认后：

```text
/coding complete task_xxx
```

预期检查点：

- QA run 可复用 task session 和 workspace。
- `merge-test` 续接 Codex session 执行 merge-to-test，不自动发布生产。
- 合入 test 后状态是 `merged_test`，人工确认后才 `/coding complete` 到 `done`。

### 10. 复杂需求拆解为多个执行任务

目标：一个飞书需求包含多个交付单元时，先审查拆解，再物化子任务。

```text
/coding breakdown task_root
/coding approve-breakdown task_root
/coding materialize task_root
/coding status task_root --tree
/coding run task_root --next
```

预期检查点：

- `breakdown` 只生成拆解报告，不创建 execution task。
- `approve-breakdown` 是人工准入门。
- `materialize` 后创建 child execution task，并保留依赖关系。
- `run --next` 只选择依赖满足的下一个子任务。

### 11. 飞书项目只读查询

目标：从飞书项目空间查询特定状态的 Story / Issue。

```json
{
  "tool": "coding_project_workitem_search",
  "arguments": {
    "space": "BPS空间",
    "workitem_type": "需求",
    "query": "状态 = 待开发",
    "limit": 3
  }
}
```

预期检查点：

- 只调用 MCP `search_by_mql`。
- 返回标题、状态、类型、URL 等可展示字段。
- 不创建 Hermes task，也不写飞书项目。

### 12. 飞书项目创建需求

目标：由 Hermes 主控在飞书项目中创建一个新需求。

未确认写入时：

```json
{
  "tool": "coding_project_workitem_create",
  "arguments": {
    "space": "BPS空间",
    "workitem_type": "需求",
    "title": "订单列表新增店铺筛选",
    "fields": {
      "优先级": "P1"
    }
  }
}
```

预期返回 `confirmation_required`，不发生写入。

确认后：

```json
{
  "tool": "coding_project_workitem_create",
  "arguments": {
    "space": "BPS空间",
    "workitem_type": "需求",
    "title": "订单列表新增店铺筛选",
    "fields": {
      "优先级": "P1"
    },
    "confirm_write": true,
    "idempotency_key": "bps-admin-order-shop-filter-20260615"
  }
}
```

预期检查点：

- 只在 `confirm_write=true` 后调用 MCP `create_workitem`。
- 返回飞书项目工作项 URL。
- 审计信息中不包含 token。

### 13. 自动拉取特定状态需求并创建 Hermes task

目标：把飞书项目里满足规则的需求同步成 Hermes task。

先 dry-run：

```json
{
  "tool": "coding_project_intake_sync",
  "arguments": {
    "rule": {
      "name": "待开发需求同步",
      "space": "BPS空间",
      "workitem_type": "需求",
      "mql": "状态 = 待开发",
      "create_coding_task": true
    },
    "dry_run": true,
    "max_items": 3
  }
}
```

确认执行：

```json
{
  "tool": "coding_project_intake_sync",
  "arguments": {
    "rule": {
      "name": "待开发需求同步",
      "space": "BPS空间",
      "workitem_type": "需求",
      "mql": "状态 = 待开发",
      "create_coding_task": true
    },
    "dry_run": false,
    "max_items": 3
  }
}
```

预期检查点：

- 已存在 `project_workitem_bindings` 的 Story 不重复创建 task。
- 新 Story 创建 root task，并绑定为 `source_requirement`。
- 如未来开启状态回写，仍应通过独立显式确认控制写操作。

### 14. 需求拆解后回写 WBS 与工时

目标：把 Hermes 拆解结果写入飞书项目 WBS，包含估时和实际工时字段。

```json
{
  "tool": "coding_project_wbs_update",
  "arguments": {
    "workitem_url": "https://project.feishu.cn/z9b9t3/story/detail/6983769492",
    "rows": [
      {
        "name": "后端接口开发",
        "owner": "张三",
        "schedule": "2026-06-15~2026-06-16",
        "estimate": 2,
        "actual_hours": 0
      },
      {
        "name": "前端筛选联调",
        "owner": "李四",
        "schedule": "2026-06-16~2026-06-17",
        "estimate": 1.5,
        "actual_hours": 0
      }
    ],
    "publish": true,
    "confirm_write": true
  }
}
```

预期检查点：

- 调用顺序为 `create_wbs_draft`、`edit_wbs_draft`、必要时 `publish_wbs_draft`。
- 每个 WBS 行可绑定到 Hermes child task。
- 估时、实际工时字段跟随 row 进入 MCP 参数，不由 Codex 自行写飞书。

### 15. 飞书项目状态流转

目标：任务完成某阶段后，自动推进飞书项目工作项状态。

```json
{
  "tool": "coding_project_state_transition",
  "arguments": {
    "workitem_url": "https://project.feishu.cn/z9b9t3/story/detail/6983769492",
    "target_state": "开发中",
    "fields": {
      "负责人": "张三"
    },
    "confirm_write": true
  }
}
```

预期检查点：

- 先查询 `get_transition_required`，确认必填字段齐全。
- 再查询 `get_transitable_states`，确认目标状态可流转。
- 最后调用 `transition_state`。
- 缺字段或目标状态不可达时，不执行写入。

### 16. 已关联 Story 的 Bugfix intake

目标：从飞书项目拉取 Bug，创建关联主需求的 bugfix task，避免每个 bugfix 开独立主线。

```json
{
  "tool": "coding_project_bugfix_intake",
  "arguments": {
    "space": "BPS空间",
    "workitem_type": "issue",
    "query": "状态 = 待处理",
    "transition_to": "处理中",
    "max_items": 3,
    "dry_run": false,
    "confirm_write": true
  }
}
```

预期检查点：

- Issue 有 `related_story_url`，且 Story 已绑定 root task 时，bugfix task 设置：
  - `root_task_id = story root task`
  - `parent_task_id = story root task`
  - `source_branch = root task source_branch`
  - `branch_policy = inherit_root_branch`
- 若配置了 `transition_to`，状态流转仍必须 `confirm_write=true`。
- 实现完成后可向 Issue 写回脱敏评论，不暴露 token 或敏感 env。

### 17. 未关联 Story 的 Bugfix intake

目标：Bug 没有关联需求时仍可进入 Hermes，但标记待人工补链。

```json
{
  "tool": "coding_project_bugfix_intake",
  "arguments": {
    "space": "BPS空间",
    "query": "状态 = 待处理 AND 标题 ~ 导出按钮",
    "dry_run": false,
    "max_items": 1
  }
}
```

预期检查点：

- 创建独立 root bugfix task。
- `branch_policy = own_branch`。
- binding metadata 写入 `needs_story_link=true`。
- 后续人工补充 Story 关系后，再决定是否并入主需求分支。

### 18. 取消、恢复和删除任务

目标：处理误触发、运行中断和历史清理。

```text
/coding cancel task_xxx
/coding restore task_xxx
/coding delete task_xxx
```

保留材料删除：

```text
/coding delete task_xxx --keep-artifacts --keep-wiki
```

预期检查点：

- `cancel` 保留 artifacts、LLM Wiki 和 Task Ledger 历史。
- `restore` 只恢复 cancelled task 到最近可行动状态。
- `delete` 会清理 task、active binding、相关 draft/run summary 和本地 run/workspace；属于 destructive 动作，应人工确认。

## 端到端复刻路径

### A. 普通需求闭环

```text
/coding project use bps-admin
/coding task 订单列表新增店铺筛选，支持店铺名模糊搜索
/coding continue task_xxx 只改订单列表页，不改导出
/coding implement task_xxx
/coding qa task_xxx
/coding merge-test task_xxx
/coding complete task_xxx
```

验收：Task Ledger 从 `planned/plan_ready` 推进到 `ready_for_merge_test`、`merged_test`、`done`；run summary 写入 LLM Wiki；飞书消息能看到下一步建议。

### B. 飞书项目 Story 到 WBS 到子任务

```text
/coding task BPS运营后台 https://project.feishu.cn/z9b9t3/story/detail/6983769492
/coding breakdown task_root
/coding approve-breakdown task_root
/coding materialize task_root
/coding status task_root --tree
/coding run task_root --next
```

随后用 `coding_project_wbs_update` 把拆解行、负责人和工时写回飞书项目。

验收：Story 绑定 root task；WBS 行可映射 child task；父任务只做交付编排，具体实现落到 execution task。

### C. 飞书项目 Bugfix 闭环

```json
{
  "tool": "coding_project_bugfix_intake",
  "arguments": {
    "space": "BPS空间",
    "query": "状态 = 待处理",
    "transition_to": "处理中",
    "confirm_write": true,
    "max_items": 3
  }
}
```

然后执行：

```text
/coding implement task_bugfix
/coding qa task_bugfix
/coding merge-test task_bugfix
```

验收：已关联 Story 的 bugfix 继承 root source branch；未关联 Story 的 bugfix 标记 `needs_story_link=true`；完成后 Issue 可收到脱敏评论。

## 不覆盖的边界

- 不自动发布生产环境。
- 不允许 Codex、Claude Code 或 Gemini 直接操作飞书项目。
- 不允许无 `confirm_write=true` 的 MCP 写操作。
- 不把 token、Hermes auth、Codex auth、`.env*`、运行根内容写入文档、fixture、prompt、日志或 LLM Wiki。
- 不把父级需求直接当作 implementation task；复杂需求必须拆解到 execution task 后再执行。
