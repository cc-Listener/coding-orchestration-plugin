def plan_semantic_fields():
    return {
        "user_facing_summary": "计划已整理好，可以确认后进入实现。",
        "technical_summary": "已识别实现范围和验证方式。",
        "execution_policy_decision": {
            "route": "standard_change",
            "planning": "plan_only",
            "verification": "targeted",
            "reasoning_summary": "需要先规划再实现。",
        },
        "branch_slug_candidate": "status-filter",
    }


def implementation_semantic_fields():
    return {
        "user_facing_summary": "订单筛选已实现。",
        "technical_summary": "更新订单列表查询参数和单测。",
        "implementation_landed": True,
        "commit_sha": "abc1234",
        "changed_files_summary": ["src/orders.py: 增加状态筛选"],
        "branch_slug_candidate": "order-status-filter",
        "execution_policy_decision": {"route": "standard_change", "verification": "targeted"},
    }


def merge_semantic_fields():
    return {
        "user_facing_summary": "测试环境合入已完成。",
        "technical_summary": "已合入 test 分支并完成验证。",
        "merge_readiness": {"ready": True, "risk_level": "low", "risk_note": ""},
    }
