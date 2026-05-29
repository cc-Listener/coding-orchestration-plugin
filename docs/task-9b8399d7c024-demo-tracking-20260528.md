# task_9b8399d7c024 Demo 跟踪文档

更新时间：2026-05-28

这份文档用于基于 `task_9b8399d7c024` 做 demo。它记录一个 BPS 后台需求从飞书输入、计划、实现、人工反馈、二次验证，到手动合入 test 并补录 merge-test 的完整链路。

时间以 Hermes artifact 原始记录为准，主要是 UTC 时间；北京时间需要加 8 小时。

## 1. 当前结论

- Task ID：`task_9b8399d7c024`
- 项目：`bps-admin`
- 项目路径：`/Users/xiaojing/Desktop/project/bps-admin`
- 当前状态：`merged_test`
- 当前阶段：`merged_test`
- Source branch：`codex/bps-contact-info-add-9b8399d7c024`
- Test branch：`test`
- Source commit：`f5a7ed5cfc02255c36bf3779e0815347c58d0ee4`
- Test branch head：`9a15ba1a8d3355fb2a79a2ae486cd38f133272e8`
- Codex session/thread：`019e6da3-b04d-7eb0-9d02-c2edb12637a2`
- 进入 Codex 可见 session：`codex resume 019e6da3-b04d-7eb0-9d02-c2edb12637a2`
- 下一步：测试环境确认无误后，人工发送 `/coding complete task_9b8399d7c024` 标记完成。

这个 task 的 demo 重点：Codex 完成了真实代码修改和验证；Hermes diff guard 因 `build:test` 生成 `dist/` 产物而阻止自动通过；用户手动合入 test 后，Hermes 用 manual merge-test run 补齐 Ledger、artifact 和状态。

## 2. 原始需求

来源：飞书私聊。

```text
bps运营后台店铺管理界面需要新增一个联系方式，
后端接口字段新增了contact_info，
如果为空要兼容为“-”，
补充到自定义店铺后面
```

人工计划反馈：

```text
这个任务的风险都可以忽略，后端不会再去更新.api-spec.json，
contact_info是非敏感字段，
pnpm build:test只要能打包成功即可，
sourcemap上传不了不是风险
```

## 3. 最终代码变化

最终实现落在 `bps-admin` 功能分支：

- `src/types/store.ts`
  - `Store` 接口新增 `contact_info?: string | null`。
- `src/components/store/StoreTable.tsx`
  - 在“自定义店铺名”列后新增“联系方式”列。
  - `dataIndex/key` 使用 `contact_info`。
  - 展示逻辑为：字符串先 `trim()`；空字符串、空白字符串、`null`、`undefined` 统一显示 `-`。
  - `contact_info` 已由人工确认为非敏感字段，因此没有接入 `renderSensitiveCell`。

关键代码位置：

- `/Users/xiaojing/.hermes/coding-orchestration/workspaces/task_9b8399d7c024/run_e1eeb9a96e79/src/types/store.ts`
- `/Users/xiaojing/.hermes/coding-orchestration/workspaces/task_9b8399d7c024/run_e1eeb9a96e79/src/components/store/StoreTable.tsx`

## 4. Demo 主线

| 步骤 | 用户/系统表象 | Hermes / Task Ledger 动作 | LLM Wiki 动作 | Codex 动作 |
| --- | --- | --- | --- | --- |
| 1 | 用户提交店铺联系方式需求 | 创建 `task_9b8399d7c024`，项目通过 LLM Wiki 识别为 `bps-admin`，项目置信度 0.9 | 写入 `task_9b8399d7c024:draft_knowledge`；读取 `project:bps-admin` | 未启动 |
| 2 | 自动进入计划 | 创建 `run_b9c7e6ca0243`，mode=`plan-only` | 读取 `project:bps-admin`，物化 `wiki-context.md`；结束后写入 run summary | Codex 读项目、读 `.api-spec.json`，产出只读计划 |
| 3 | 人工确认实现 | 记录 `implementation_confirmed` | 无新增 task draft | 复用同一个 Codex session |
| 4 | 第一次实现 | 创建 `run_e1eeb9a96e79`，mode=`implementation`，创建 workspace 和 source branch | 写入 implementation run summary | Codex 修改 `StoreTable.tsx` 和 `store.ts`，安装依赖并运行验证 |
| 5 | Diff guard 拦截 | Task 未自动进入 merge-test | run summary 沉淀验证结果和风险 | `build:test` 成功，但生成大量 `dist/` 产物，违反 allowed/forbidden paths，run 标为 `blocked` |
| 6 | 用户补充验收口径 | 记录 `plan_feedback`：API 快照不更新、非敏感、build 成功即可 | 写入 `task_9b8399d7c024:plan_feedback:2` | 未实现代码变更 |
| 7 | 更新计划 | 创建 `run_8de0bdcfd3d6`，mode=`plan-only` | 写入 plan revision run summary | Codex 确认不再等待 `.api-spec.json`，不处理敏感字段，不把 sourcemap 当风险 |
| 8 | 二次实现验证 | 创建 `run_dda24b89dc0a`，复用原 workspace 和 branch | 写入 implementation run summary | Codex 重新验证：定点 lint、`build:test`、`git diff --check` 通过 |
| 9 | 再次被 diff guard 拦截 | Run 仍是 `blocked`，原因是 `dist/` 构建产物仍在 diff 中 | 保留 run summary | Hermes 保护源码边界，未自动 merge-test |
| 10 | 用户手动合入 test | 创建 `run_aea8a0a8b022`，runner=`manual`，mode=`merge-test` | Ledger 记录 merge record；本轮不调用 Codex | 不调用 Codex；Hermes 用 `git merge-base --is-ancestor` 确认 source branch 已被 test 包含 |
| 11 | 当前状态 | Task 状态更新为 `merged_test` | Wiki 保留需求、反馈和 run summaries | 等人工最终 `/coding complete` |

## 5. Run 明细

| Run | Mode | Runner | 状态 | 关键结果 |
| --- | --- | --- | --- | --- |
| `run_b9c7e6ca0243` | `plan-only` | `codex_cli` | `success` | 计划确认只改 `src/types/store.ts` 和 `src/components/store/StoreTable.tsx` |
| `run_e1eeb9a96e79` | `implementation` | `codex_cli` | `blocked` | 实现完成；定点 lint、`build:test`、`git diff --check` 通过；仓库级 lint 被既有无关问题阻断；diff guard 发现 `dist/` 产物 |
| `run_8de0bdcfd3d6` | `plan-only` | `codex_cli` | `success` | 根据人工反馈更新计划：`contact_info` 非敏感、不等待 `.api-spec.json`、build 成功即可 |
| `run_dda24b89dc0a` | `implementation` | `codex_cli` | `blocked` | 重新验证通过，但 `build:test` 仍生成 `dist/` 产物，继续被 diff guard 拦截 |
| `run_aea8a0a8b022` | `merge-test` | `manual` | `success` | 用户已手动合入 test；Hermes 补录 merge-test 并确认 source branch 已被 test 包含 |

## 6. 验证结果

Codex 在实现 run 中记录的验证：

```text
rtk pnpm install
rtk pnpm exec eslint src/types/store.ts src/components/store/StoreTable.tsx --ext .ts,.tsx
rtk pnpm build:test
rtk git diff --check
```

结果摘要：

- `rtk pnpm install`：通过，workspace 缺少 `node_modules` 后安装依赖。
- 定点 lint：通过，本次触达文件无 lint 问题。
- `rtk pnpm build:test`：通过，Vite test mode 打包成功。
- `rtk git diff --check`：通过，无空白符问题。
- 仓库级 `rtk pnpm lint`：失败，但失败来自既有无关文件，不是本次触达文件。

需要特别解释的点：

- `build:test` 会生成 `dist/` 产物。
- Hermes 的 allowed paths 是 `src/`、`docs/`、`tests/`、`contracts/`、`package.json`、`pnpm-lock.yaml`。
- `dist/` 在 forbidden paths 中，所以实现 run 即使功能已完成，也被 diff guard 标为 `blocked`。
- 后续通过人工 merge-test 记录把真实合入动作回填到 Hermes 状态机。

## 7. LLM Wiki 动作明细

LLM Wiki 记录本轮可复用信息，不替代 Task Ledger 的运行期事实。

| 时间 | 类型 | Wiki ID | 路径 | 说明 |
| --- | --- | --- | --- | --- |
| 2026-05-28T08:11:39Z | `draft_knowledge` | `task_9b8399d7c024:draft_knowledge` | `wiki/sources/task_9b8399d7c024-draft_knowledge.md` | 保存原始需求 |
| 2026-05-28T08:15:07Z | `run_summary` | `task_9b8399d7c024:run_b9c7e6ca0243:run_summary` | `wiki/synthesis/task_9b8399d7c024-run_b9c7e6ca0243-run_summary.md` | 保存首轮计划 |
| 2026-05-28T08:22:21Z | `run_summary` | `task_9b8399d7c024:run_e1eeb9a96e79:run_summary` | `wiki/synthesis/task_9b8399d7c024-run_e1eeb9a96e79-run_summary.md` | 保存第一次实现结果和 diff guard 风险 |
| 2026-05-28T08:44:18Z | `draft_knowledge` | `task_9b8399d7c024:plan_feedback:2` | `wiki/sources/task_9b8399d7c024-plan_feedback-2.md` | 保存人工计划反馈和验收口径 |
| 2026-05-28T08:45:18Z | `run_summary` | `task_9b8399d7c024:run_8de0bdcfd3d6:run_summary` | `wiki/synthesis/task_9b8399d7c024-run_8de0bdcfd3d6-run_summary.md` | 保存计划更新结果 |
| 2026-05-28T08:49:35Z | `run_summary` | `task_9b8399d7c024:run_dda24b89dc0a:run_summary` | `wiki/synthesis/task_9b8399d7c024-run_dda24b89dc0a-run_summary.md` | 保存二次实现验证结果 |

本轮 Wiki 读取动作：

- Project Resolver 读取 `project:bps-admin`，把“BPS运营后台”匹配到 `bps-admin`。
- 每个 Codex run 都通过 Hermes 生成的 `wiki-context.md` 获取项目画像和 task 相关上下文。
- 人工反馈进入 LLM Wiki 后，后续 plan revision 能直接读取新口径，不需要重新解释历史。

## 8. Artifact 索引

Run 根目录：

```text
/Users/xiaojing/.hermes/coding-orchestration/runs/task_9b8399d7c024
```

Workspace：

```text
/Users/xiaojing/.hermes/coding-orchestration/workspaces/task_9b8399d7c024/run_e1eeb9a96e79
```

关键 artifact：

| 文件 | 用途 |
| --- | --- |
| `run-manifest.json` | run 的事实清单：mode、runner、权限、workspace、source branch |
| `input-prompt.md` | 给 Codex session 的可见 prompt |
| `confirmed-plan.md` | implementation run 使用的已确认计划 |
| `run-instructions.md` | 执行要求和 report 输出契约 |
| `report.json` | Codex 或 manual runner 的结构化结果 |
| `summary.md` | 给人看的计划、实现或 merge-test 摘要 |
| `diff.patch` | Diff guard 摘要，包括 changed files 和 policy violations |
| `stdout.log` / `stderr.log` | Codex 事件流和错误流 |

## 9. Codex 实际动作摘要

Codex 在这个 task 中做了几类动作：

1. 计划阶段：
   - 读取项目规则和 `WORKFLOW.md`。
   - 搜索店铺管理页面和表格组件。
   - 检查 `.api-spec.json` 中 `GET /api/bps_ops/v1/store` / `dto.OpsListStoreData`。
   - 判断 `.api-spec.json` 尚未包含 `contact_info`，但需求明确后端新增该字段。
   - 形成只改类型和表格列的最小计划。

2. 实现阶段：
   - 在 task workspace 中修改源码。
   - 新增 `Store.contact_info?: string | null`。
   - 在 `StoreTable` 的“自定义店铺名”后新增“联系方式”列。
   - 使用 `trim()` 兼容空白字符串，最终空值展示 `-`。

3. 验证阶段：
   - 安装依赖。
   - 运行定点 lint。
   - 运行 `build:test`。
   - 运行 `git diff --check`。
   - 记录仓库级 lint 的既有无关错误。

4. 反馈处理阶段：
   - 读取人工反馈。
   - 更新计划，移除 `.api-spec.json`、敏感字段和 sourcemap 相关阻塞。
   - 按新口径再次验证。

Codex 没有执行发布、部署或直接操作飞书。

## 10. Demo 讲解口径

建议这样讲：

1. 用户视角：
   - 用户只提出业务需求：店铺列表新增联系方式，空值显示 `-`。
   - 用户后来补充验收口径：`contact_info` 非敏感，API 快照不用等，build 成功即可。
   - 最终状态已经合入 test，等待人工 complete。

2. Hermes 视角：
   - Hermes 负责 project resolve、Task Ledger、状态机、workspace、artifact、diff guard 和 merge-test 补录。
   - Hermes 不直接写业务代码，也不会因为用户说“风险忽略”就放弃源码边界。
   - `dist/` 产物触发 diff guard，是系统按边界保护任务输出。

3. Codex 视角：
   - Codex 负责真实读代码、改代码、跑验证。
   - Codex 复用同一个 session，后续 run 不需要从零解释上下文。
   - Codex 按人工反馈调整计划和验证口径。

4. LLM Wiki 视角：
   - Wiki 保存需求草稿、计划反馈和 run summary。
   - 后续 run 能复用这些知识，减少重复上下文。
   - 运行期事实仍以 Task Ledger 为准，Wiki 是可复用知识层。

这个 task 很适合演示“自动化闭环里的人工控制点”：Codex 完成实现，Hermes 守住合规边界，用户手动处理 merge-test，系统再把人工动作补录回可审计状态机。
