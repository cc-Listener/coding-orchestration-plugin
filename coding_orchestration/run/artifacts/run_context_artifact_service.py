from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...models import RunMode
from ...source.source_projection import source_projection_from_source, source_projection_to_dict


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def read_run_execution_policy_artifact(*, result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    policy = result.get("execution_policy")
    if isinstance(policy, dict):
        return dict(policy)

    artifacts = result.get("artifacts")
    artifact = artifacts if isinstance(artifacts, dict) else {}
    path_value = artifact.get("execution_policy")
    if not path_value:
        run_dir = artifact.get("run_dir")
        if run_dir:
            path_value = Path(str(run_dir)) / "execution-policy.json"
    if not path_value:
        return {}

    policy_path = Path(str(path_value))
    if not policy_path.exists():
        return {}
    try:
        loaded = json.loads(policy_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def write_run_context_artifacts(
    *,
    run_dir: Path,
    task: dict[str, Any],
    mode: RunMode,
    source: dict[str, Any],
    project_name: str,
    wiki_docs: list[dict[str, Any]],
    wiki_refs: list[dict[str, Any]],
    confirmed_context: str,
    execution_policy: dict[str, Any],
    context_assembler: Any,
    prompt_builder: Any,
    dependency_tasks: list[dict[str, Any]],
    sibling_tasks: list[dict[str, Any]],
) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    if wiki_docs:
        wiki_path = run_dir / "wiki-context.md"
        wiki_sections = []
        for doc in wiki_docs:
            title = str(doc.get("title") or "未命名")
            ref_id = str(doc.get("id") or "unknown")
            body = str(doc.get("body") or "").strip() or "无正文"
            wiki_sections.append(f"## {ref_id}：{title}\n\n{body}")
        wiki_path.write_text("\n\n".join(wiki_sections), encoding="utf-8")
        artifacts["wiki_context"] = str(wiki_path)

    if mode == RunMode.IMPLEMENTATION:
        plan_text = confirmed_context.strip()
        if plan_text:
            plan_path = run_dir / "confirmed-plan.md"
            plan_path.write_text(plan_text, encoding="utf-8")
            artifacts["confirmed_plan"] = str(plan_path)
        elif str((execution_policy or {}).get("planning") or "") != "inline":
            plan_path = run_dir / "confirmed-plan.md"
            plan_path.write_text(
                "未找到已确认 plan-only 摘要；如果无法安全实现，请返回 `status=blocked` 并说明需要人工补充什么。",
                encoding="utf-8",
            )
            artifacts["confirmed_plan"] = str(plan_path)
    elif mode in {RunMode.QA, RunMode.MERGE_TEST}:
        implementation_path = run_dir / "implementation-context.md"
        implementation_text = confirmed_context.strip() or (
            "未找到上一次 implementation 上下文；如果无法安全继续，请返回 `status=blocked`。"
        )
        implementation_path.write_text(implementation_text, encoding="utf-8")
        artifacts["implementation_context"] = str(implementation_path)

    context_package = context_assembler.assemble(
        run_mode=mode,
        task=task,
        run_dir=run_dir,
        dependency_tasks=dependency_tasks,
        sibling_tasks=sibling_tasks,
    )
    if context_package.prompt_context.strip():
        assembled_context_path = run_dir / "assembled-context.md"
        assembled_context_path.write_text(context_package.prompt_context, encoding="utf-8")
        artifacts["assembled_context"] = str(assembled_context_path)
    artifacts["context_manifest"] = str(context_package.manifest_path)

    instructions_path = run_dir / "run-instructions.md"
    instructions_path.write_text(
        prompt_builder.build_run_instructions(mode=mode, execution_policy=execution_policy),
        encoding="utf-8",
    )
    artifacts["run_instructions"] = str(instructions_path)

    execution_policy_path = run_dir / "execution-policy.json"
    execution_policy_path.write_text(json_dumps(execution_policy), encoding="utf-8")
    artifacts["execution_policy"] = str(execution_policy_path)

    context_index_path = run_dir / "context-index.json"
    artifacts["context_index"] = str(context_index_path)
    index = {
        "task_id": task.get("task_id"),
        "project_name": project_name,
        "requirement_summary": task.get("requirement_summary"),
        "source": {
            key: source[key]
            for key in ("type", "title", "url", "project_name", "message_summary", "related_task_id")
            if source.get(key)
        },
        "wiki_refs": [
            {"id": ref.get("id"), "title": ref.get("title")}
            for ref in wiki_refs
        ],
        "execution_policy": execution_policy,
        "artifacts": dict(artifacts),
    }
    source_context = source.get("source_context")
    if isinstance(source_context, dict) and source_context:
        index["source"]["source_context"] = source_context
    source_projection = source_projection_from_source(source)
    if (
        source_projection.status != "missing"
        or source_projection.source_type
        or source_projection.url
        or source_projection.title
        or source_projection.legacy_context
    ):
        index["source"]["source_projection"] = source_projection_to_dict(source_projection)
    context_index_path.write_text(json_dumps(index), encoding="utf-8")
    return artifacts
