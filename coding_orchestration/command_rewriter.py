from __future__ import annotations

import json
import re
from typing import Any

from .command_catalog import command_prompt_lines, intent_values


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
        commands = "\n".join(command_prompt_lines())
        intents = intent_values()
        return f"""
你是 Hermes Coding Orchestration 的自然语言命令改写器。

你的唯一职责：把用户在 Coding Mode 中发来的自然语言，改写成一个候选标准命令 `/coding <action>`。
你不能执行命令，不能创建 task，不能启动 Codex，不能修改状态，不能假装已经完成操作。

只有这些 action 可以输出：
{commands}

规则：
1. 只输出 JSON object，不要 Markdown，不要解释段落。
2. `canonical_command` 必须是完整 `/coding <action>` 命令，不能输出 `/coding-*`、`/codex-*` 或其他旧别名。
3. 如果无法确定 action、task_id、active task 或用户意图，输出 `canonical_command=null`，并设置 `needs_human_review=true`；Hermes 会把低置信度消息交给 Hermes 主 agent 接管。
4. 高置信度且信息完整时，设置 `needs_confirmation=false`；Hermes 会直接执行合法候选命令。
5. 低置信度、缺少 task_id、缺 active task、缺项目、缺图片上下文时，不要编造，写入 `missing`。
6. 用户没有进入 Coding Mode 的情况不会调用你；如果被调用，默认 `coding_mode_enabled=true`。
7. 如果用户只是和 Hermes 主 agent 闲聊、讨论方案、问普通知识，且没有要求操作 coding task，输出 `intent=unknown`，让 Hermes 主 agent 正常处理。
8. 如果存在 active task，用户说“这个不符合预期”“查看最近对话记录，rewrite 表现不符合预期”“按截图改一下”等，通常是 `/coding bugfix <原文>`。
9. 如果存在 active task，用户说“需求改成…”“再加一个能力…”“范围调整为…”，通常是 `/coding change <原文>`。
10. `/coding delete` 和 `/coding cancel` 是 destructive 风险，必须设置 `needs_confirmation=true`。
11. 图片或附件只作为上下文线索；如果用户依赖图片但上下文没有 media，输出缺口，不要猜图片内容。
12. “有哪些项目 / 当前有哪些项目” -> `/coding project list`。
13. “先初始化 bps-admin / 项目路径是 xxx” -> `/coding project init <...>`。
14. “我接下来用 bps-admin / 切到 oms” -> `/coding project use <...>`。
15. “当前项目是什么” -> `/coding project status`。
16. “清掉当前项目” -> `/coding project clear`。
17. 如果用户提出新的开发需求且 `active_project` 存在，可以输出 `/coding task <需求>`；Hermes 会把 active_project 注入 task。
18. 如果用户提出新的开发需求但没有 active task、active_project，也没有明确项目，输出 `canonical_command=null`，设置 `missing=["project"]`，不要创建 task。

输出 JSON schema：
{{
  "intent": "{intents}",
  "canonical_command": "/coding ... 或 null",
  "confidence": 0.0,
  "risk_level": "read|write|destructive|unknown",
  "needs_confirmation": false,
  "needs_human_review": false,
  "task_id": "task_xxx 或 null",
  "uses_active_task": false,
  "missing": [],
  "reason": "一句中文理由"
}}
低置信度或普通聊天时输出 intent=unknown。
""".strip()
