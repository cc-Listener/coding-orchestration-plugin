from __future__ import annotations

import json
import re
from typing import Any


class HermesCommandRewriter:
    """Rewrite Coding Mode natural language into a candidate `/coding` command."""

    def rewrite(self, context: dict[str, Any]) -> dict[str, Any]:
        try:
            client, model = self._resolve_client()
            if client is None or not model:
                return self._fallback("llm_unavailable", "Hermes 未找到可用的辅助 LLM provider。")
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": self._system_prompt()},
                    {
                        "role": "user",
                        "content": "请根据以下上下文输出 JSON，不要输出 Markdown：\n"
                        + json.dumps(context, ensure_ascii=False, indent=2),
                    },
                ],
            )
            content = self._response_text(response)
            parsed = self._parse_json_object(content)
            return parsed if isinstance(parsed, dict) else self._fallback("invalid_json", "LLM 未返回 JSON object。")
        except Exception as exc:
            return self._fallback("llm_error", f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _resolve_client() -> tuple[Any | None, str | None]:
        try:
            from agent.auxiliary_client import resolve_provider_client

            return resolve_provider_client("auto")
        except Exception:
            return None, None

    @staticmethod
    def _response_text(response: Any) -> str:
        try:
            choice = response.choices[0]
            message = getattr(choice, "message", None)
            content = getattr(message, "content", None)
            if isinstance(content, str):
                return content
        except Exception:
            pass
        return str(response)

    @staticmethod
    def _parse_json_object(text: str) -> Any:
        text = text.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _fallback(intent: str, reason: str) -> dict[str, Any]:
        return {
            "intent": intent,
            "canonical_command": None,
            "confidence": 0.0,
            "risk_level": "unknown",
            "needs_confirmation": True,
            "needs_human_review": True,
            "task_id": None,
            "uses_active_task": False,
            "missing": ["canonical_command"],
            "reason": reason,
        }

    @staticmethod
    def _system_prompt() -> str:
        return """
你是 Hermes Coding Orchestration 的自然语言命令改写器。

你的唯一职责：把用户在 Coding Mode 中发来的自然语言，改写成一个候选标准命令 `/coding <action>`。
你不能执行命令，不能创建 task，不能启动 Codex，不能修改状态，不能假装已经完成操作。

只有这些 action 可以输出：
- `/coding task <需求>`：创建新的 coding task。仅当用户明确提出新的开发、修复、实现、优化需求时使用。
- `/coding list`：列出未结束 task。用于“现在有多少 task”“有哪些任务”“列一下任务”等查询。
- `/coding use <task_id>`：切换当前 active task。用户明确说切换、使用、绑定某个 task 时使用。
- `/coding exit`：退出当前飞书会话绑定的 active task/coding mode。用户明确说退出当前 coding 任务绑定时使用；“退出coding”会由 Hermes 直接处理。
- `/coding status <task_id>`：查看某个 task 的详细状态。
- `/coding continue <反馈>`：补充 plan 反馈，让任务回到 plan-only。
- `/coding change <反馈>`：需求变更。用户改变范围、追加新功能、改验收口径时使用。
- `/coding bugfix <反馈>`：对当前 active task 的实现、QA 或插件行为提出修复反馈时使用。
- `/coding run <task_id>`：对已有任务启动 plan-only。
- `/coding implement <task_id>`：人工确认计划后启动 implementation。
- `/coding prepare-merge-test <task_id>`：只标记等待人工执行 merge test，不运行 merge。
- `/coding merge-test <task_id>`：人工触发 merge-to-test run。
- `/coding complete <task_id>`：merge-test 后人工标记完成。
- `/coding cancel <task_id|run_id>`：取消任务或 run。
- `/coding delete <task_id>`：删除 task。
- `/coding help`：查看帮助。

规则：
1. 只输出 JSON object，不要 Markdown，不要解释段落。
2. `canonical_command` 必须是完整 `/coding <action>` 命令，不能输出 `/coding-*`、`/codex-*` 或其他旧别名。
3. 如果无法确定 action、task_id、active task 或用户意图，输出 `canonical_command=null`，并设置 `needs_human_review=true`。
4. 高置信度且信息完整时，设置 `needs_confirmation=false`；Hermes 会直接执行合法候选命令。
5. 低置信度、缺少 task_id、缺 active task、缺项目、缺图片上下文时，不要编造，写入 `missing`。
6. 用户没有进入 Coding Mode 的情况不会调用你；如果被调用，默认 `coding_mode_enabled=true`。
7. 如果用户只是和 Hermes 主 agent 闲聊、讨论方案、问普通知识，且没有要求操作 coding task，输出 `intent=unknown`。
8. 如果存在 active task，用户说“这个不符合预期”“查看最近对话记录，rewrite 表现不符合预期”“按截图改一下”等，通常是 `/coding bugfix <原文>`。
9. 如果存在 active task，用户说“需求改成…”“再加一个能力…”“范围调整为…”，通常是 `/coding change <原文>`。
10. `/coding delete` 和 `/coding cancel` 是 destructive 风险，必须设置 `needs_confirmation=true`。
11. 图片或附件只作为上下文线索；如果用户依赖图片但上下文没有 media，输出缺口，不要猜图片内容。

输出 JSON schema：
{
  "intent": "create_task|list_tasks|select_task|exit_task|status_task|plan_feedback|requirement_change|bugfix_feedback|run_plan|implement|prepare_merge_test|merge_test|complete_task|cancel|delete|help|unknown",
  "canonical_command": "/coding ... 或 null",
  "confidence": 0.0,
  "risk_level": "read|write|destructive|unknown",
  "needs_confirmation": false,
  "needs_human_review": false,
  "task_id": "task_xxx 或 null",
  "uses_active_task": false,
  "missing": [],
  "reason": "一句中文理由"
}
""".strip()
