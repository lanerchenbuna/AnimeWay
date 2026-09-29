"""Natural-language routebook orchestration using the personal Trip evaluator."""
from __future__ import annotations

from core.trip import evaluate
from core.trip_ai import request_routebook


def generate_routebook(text, *, store, token, catalog, qwen_key):
    """Let Qwen select catalog stops; compute all transport locally in Trip."""
    draft = request_routebook(store, token, text, catalog, qwen_key)
    plan = draft["plan"]
    return {
        "plan": plan,
        "evaluation": evaluate(plan, catalog),
        "guide": (
            "Qwen 只从东京试点候选地点中选择并排序。时间、交通、费用和访问状态"
            "由个人 Trip 的统一规则评估；未知公交／铁路不会改用其他交通方式。"
        ),
    }
