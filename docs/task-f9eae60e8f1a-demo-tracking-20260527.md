# task_f9eae60e8f1a Demo 跟踪文档

更新时间：2026-05-27

这份文档用于基于 `task_f9eae60e8f1a` 做 demo。重点不是复述需求，而是把一个 coding task 从飞书输入、Task Ledger、LLM Wiki、Codex plan-only run 到 blocked 结论的每一步讲清楚。

时间以 artifact 原始记录为准，主要是 UTC 时间；北京时间需要加 8 小时。

## 1. 当前结论

- Task ID：`task_f9eae60e8f1a`
- 项目：`fulfill-ui`
- 项目路径：`/Users/xiaojing/Desktop/project/fulfill-ui`
- 当前状态：`blocked`
- 当前阶段：`blocked`
- 最近一次 run：`run_5d00c49e9a1e`
- Runner：`codex_cli`
- Run 模式：`plan-only`
- Codex session/thread：`019e68c1-b8c7-74f1-aa5a-c07ffc3d03b1`
- 进入 Codex 可见 session：`codex resume 019e68c1-b8c7-74f1-aa5a-c07ffc3d03b1`
- 阻塞原因：飞书 Wiki 接口文档没有被成功读取，缺少保存店铺联系方式的接口契约。

这个 demo 的核心价值点：系统没有在接口不明确时强行实现，而是把需求、人工补充、项目画像、Codex 调研结果、blocked 原因和下一步动作都沉淀成可审计材料。

## 2. 原始需求

来源：飞书私聊。

需求摘要：

```text
fulfill-ui 的嵌入式界面新增弹出引导 tips 需求：
文案为「Please share your contact information, so we can offer you the most competitive quotation and other better fulfillment service.」；
输入框占位符为「Enter Whatsapp number or phone number」，支持用户写入；
弹出机制为：店铺所属商户没有任何一个店铺存在店铺联系方式信息时，一直弹出；
用户写入后将信息存储到店铺中。
接口文档：https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe
```

人工补充：

```text
项目文件夹名称为`fulfill-ui`
```

## 3. Demo 主线

| 步骤 | 用户/系统表象 | Hermes / Task Ledger 动作 | LLM Wiki 动作 | Codex 动作 |
| --- | --- | --- | --- | --- |
| 1 | 用户提交需求 | 创建 `task_f9eae60e8f1a`，记录飞书来源、需求正文、gateway source | 写入 `task_f9eae60e8f1a:draft_knowledge` | 未启动 |
| 2 | 用户补充项目文件夹 | 将项目识别为 `fulfill-ui`，项目置信度变为 1.0，项目路径为 `/Users/xiaojing/Desktop/project/fulfill-ui` | 写入人工补充；写入 `project:fulfill-ui` 项目画像 | 未启动 |
| 3 | 进入 plan-only run | 创建 `run_5d00c49e9a1e`，生成 manifest、prompt、schema、context index、wiki context、run instructions | 读取 `project:fulfill-ui`，把 Wiki 内容物化到 `wiki-context.md` | 启动 Codex CLI，创建 thread `019e68c1-b8c7-74f1-aa5a-c07ffc3d03b1` |
| 4 | Codex 读上下文 | 保持 run 只读，等待结构化 report | 无新增写入 | 读取 `writing-plans` skill、`context-index.json`、`wiki-context.md`、`run-instructions.md` |
| 5 | Codex 调研代码 | Hermes 只收集 stdout/stderr，不干预代码判断 | 无新增写入 | 扫描 `fulfill-ui` 代码，定位 Layout、Zustand 店铺状态、`/store/list` service、已有弹窗组件 |
| 6 | Codex 尝试读取接口文档 | 记录命令 stdout/stderr | 没有拿到接口文档，因此没有新增接口知识 | 调用 `rtk lark-cli docs +fetch ...` 失败，错误为 `lark-cli is not bound to it` |
| 7 | Codex 输出 blocked report | 保存 `report.json`、`summary.md`、`diff.patch`，Task Ledger 状态更新为 `blocked` | 写入 `run_summary` 到 `wiki/synthesis` | 返回 `status=blocked`、`human_required=true` 和下一步待确认项 |

## 4. LLM Wiki 动作明细

LLM Wiki 本轮不是运行期事实源，运行状态仍以 Task Ledger 为准；Wiki 负责沉淀可复用知识、草稿和 run summary。

已写入记录：

| 时间 | 类型 | Wiki ID | 路径 | 说明 |
| --- | --- | --- | --- | --- |
| 2026-05-27T09:25:04Z | `draft_knowledge` | `task_f9eae60e8f1a:draft_knowledge` | `wiki/sources/task_f9eae60e8f1a-draft_knowledge.md` | 保存原始需求草稿 |
| 2026-05-27T09:25:57Z | `draft_knowledge` | `task_f9eae60e8f1a:human_clarification:1` | `wiki/sources/task_f9eae60e8f1a-human_clarification-1.md` | 保存人工补充：项目文件夹为 `fulfill-ui` |
| 2026-05-27T09:25:57Z | `project_profile` | `project:fulfill-ui` | `wiki/entities/project-fulfill-ui.md` | 建立 `fulfill-ui` 项目画像，包含本地路径和别名 |
| 2026-05-27T09:33:35Z | `run_summary` | `task_f9eae60e8f1a:run_5d00c49e9a1e:run_summary` | `wiki/synthesis/task_f9eae60e8f1a-run_5d00c49e9a1e-run_summary.md` | 保存 Codex 的计划、风险、blocked 原因和下一步 |

本轮 Wiki 读取动作：

- Hermes 在创建 run 时读取 `project:fulfill-ui`，生成 `wiki-context.md`。
- Codex 读取 `wiki-context.md` 后判断：本地 Wiki 只重复了需求摘要，没有展开接口字段。
- 因接口文档读取失败，Wiki 没有新增接口契约类知识。

## 5. Run Artifact

Run 目录：

```text
/Users/xiaojing/.hermes/coding-orchestration/runs/task_f9eae60e8f1a/run_5d00c49e9a1e
```

关键文件：

| 文件 | 用途 |
| --- | --- |
| `run-manifest.json` | 本次 run 的事实清单：task、runner、mode、project path、deadline、权限边界 |
| `input-prompt.md` | 给 Codex 可见 session 的极简 prompt |
| `context-index.json` | 汇总 task、项目、Wiki refs 和 artifact 路径 |
| `wiki-context.md` | 从 LLM Wiki 物化出来的项目上下文 |
| `run-instructions.md` | 详细执行要求和 report schema 约束 |
| `report.schema.json` | Codex 输出 report 的结构约束 |
| `stdout.log` | Codex 事件流，包括 agent_message 和命令执行记录 |
| `stderr.log` | Codex 运行错误流；本轮有模型列表刷新错误，但不影响最终 blocked 结论 |
| `report.json` | Codex 最终结构化结果 |
| `summary.md` | 给人看的计划和 blocked 摘要 |
| `diff.patch` | 本轮无代码修改，内容为 `No file changes detected.` |

## 6. Codex 实际动作

Codex 本轮以 `plan-only` 模式执行，没有修改文件。

核心动作顺序：

1. 启动 thread：`019e68c1-b8c7-74f1-aa5a-c07ffc3d03b1`。
2. 使用 `writing-plans` skill，目标是产出只读实施计划。
3. 读取 Hermes 生成的上下文文件：
   - `context-index.json`
   - `wiki-context.md`
   - `run-instructions.md`
4. 扫描 `fulfill-ui` 项目结构，识别 Next.js App Router、React、Zustand。
5. 定位可能涉及的代码：
   - `components/layouts/Layout.tsx`
   - `lib/store/app.ts`
   - `server/authService.ts`
   - `types/service/auth.d.ts`
   - `components/ui/dialog.tsx`
   - `components/ui/input.tsx`
   - `components/ui/button.tsx`
6. 搜索店铺、联系方式、Shopify embedded、whatsapp、phone 等关键词。
7. 尝试读取飞书 Wiki 接口文档：

```bash
rtk lark-cli docs +fetch --api-version v2 --doc "https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe" --doc-format markdown --scope keyword --keyword "store\\|contact\\|phone\\|whatsapp\\|联系方式\\|店铺" --format json
```

结果失败：

```text
hermes context detected but lark-cli is not bound to it
```

8. 读取已有测试和历史计划样例，确认测试风格：
   - `tests/auth-redirect-decision.test.mts`
   - `tests/shopify-title-bar-actions.test.mts`
   - `docs/plans/2026-04-14-shopify-title-bar-features-plan.md`
9. 生成 `blocked` report，要求人工补充接口契约后再继续。

## 7. Codex 计划结论

Codex 已确认的实现方向：

- 只在 Shopify embedded runtime 下生效。
- 判断条件应基于店铺列表：同一商户下没有任何店铺存在联系方式时弹出。
- 弹窗不应允许关闭，用户提交成功后才消失。
- 提交成功后要更新本地 Zustand 店铺状态，最好再重新拉取 `/store/list`。

建议涉及模块：

- `types/service/auth.d.ts`：扩展店铺联系方式字段和保存接口类型。
- `lib/store/app.ts`：扩展 `StoreItem`，让联系方式进入店铺状态。
- `server/authService.ts`：新增保存联系方式的 service wrapper。
- `lib/storeContactGuide.ts`：新增纯逻辑，便于 `node:test` 覆盖。
- `components/shopify/StoreContactGuide.client.tsx`：新增弹窗 UI。
- `components/layouts/Layout.tsx`：挂载引导组件。

建议测试命令：

```bash
rtk node --test tests/store-contact-guide.test.mts
rtk pnpm exec tsc --noEmit
rtk pnpm run build:test
```

## 8. 当前阻塞项

必须补充或确认：

1. 保存店铺联系方式的接口 path、method、请求体字段和响应结构。
2. `/store/list` 是否返回店铺联系方式字段，以及字段名是什么。
3. 空联系方式的形态：`null`、空字符串、字段缺失，还是其他值。
4. 用户输入后保存到当前选中店铺、第一家店铺，还是后端按商户自动选择店铺。
5. 是否真的不允许关闭弹窗。当前按需求“一直弹出”理解为不可关闭，只能提交成功后消失。

## 9. 继续 Demo 的推荐路线

如果要继续演示“补充信息后恢复推进”，推荐这样走：

1. 先补接口契约，例如：

```text
/coding continue task_f9eae60e8f1a 保存接口为 POST /store/contact，body 为 { store_id, contact_info }；/store/list 返回 contact_info，空值为 null；保存到当前选中店铺。
```

2. Hermes 将这段补充写入 Task Ledger 和 LLM Wiki draft。
3. Hermes 复用 Codex session `019e68c1-b8c7-74f1-aa5a-c07ffc3d03b1` 重新做 plan-only。
4. 如果 Codex 计划通过，Task 进入 `plan_ready`。
5. 人工触发：

```text
/coding implement task_f9eae60e8f1a
```

6. Hermes 创建 implementation workspace，复用同一个 Codex session，把确认后的 plan、Wiki 上下文、实现规则交给 Codex。
7. Codex 执行 TDD、实现、测试、QA，并输出新的结构化 report。

## 10. Demo 讲解口径

可以按下面三个层次讲：

1. 用户视角：只看到一个 task 从需求、补充项目、等待计划，到系统明确告诉你“缺接口文档，不能盲做”。
2. Hermes 视角：它负责状态机、artifact、上下文裁剪、session 复用和安全边界，不直接写业务代码。
3. Codex + LLM Wiki 视角：Codex 负责读代码和产出计划；LLM Wiki 负责把需求草稿、项目画像、人工补充和 run summary 沉淀下来，下一轮可以复用。

这个 task 很适合用来演示“自动化不是无脑执行”：当上下文不足时，系统能把风险停在 plan 阶段，并留下完整证据链。
