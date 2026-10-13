"""An extractive, cumulative overview of the complete research transcript.

This deliberately uses recorded text and state rather than making an extra paid
model call or presenting a newly invented interpretation as a research finding.
"""

from __future__ import annotations

from collections import OrderedDict
import json
from pathlib import Path
import re


PROVIDERS = ("gpt", "claude", "gemini", "grok")
LABELS = {"gpt": "GPT", "claude": "Claude", "gemini": "Gemini", "grok": "Grok",
          "user": "1415", "friend": "1314", "member3": "1410", "member4": "1411"}
GROUPS = {
    "role_selection": ("roles", "역할 협의"),
    "topic_selection": ("topic", "주제 선정"),
    "plan_discussion": ("plan", "연구 계획·계획발표"),
    "plan_report": ("plan", "연구 계획·계획발표"),
    "plan_slides": ("plan", "연구 계획·계획발표"),
    "plan_script": ("plan", "연구 계획·계획발표"),
    "experiment_discussion": ("experiment", "실험·분석"),
    "experiment_cases": ("experiment", "실험·분석"),
    "experiment_run": ("experiment", "실험·분석"),
    "experiment_analysis": ("experiment", "실험·분석"),
    "middle_slides": ("middle", "중간발표"),
    "middle_script": ("middle", "중간발표"),
    "final_discussion": ("final", "최종 검증·최종발표"),
    "final_report": ("final", "최종 검증·최종발표"),
    "final_slides": ("final", "최종 검증·최종발표"),
    "final_script": ("final", "최종 검증·최종발표"),
}
STAGE_TASKS = {
    "roles": "네 모델이 연구 역할을 협의하고 있습니다.",
    "topic": "역할을 바탕으로 검증 가능한 AI 연구 주제를 선정하고 있습니다.",
    "plan_discussion": "가설·변수·대조군·자료·일정을 토론하고 있습니다.",
    "plan_report": "연구계획보고서를 작성하고 있습니다.",
    "plan_slides": "계획발표 PPT를 작성하고 있습니다.",
    "plan_script": "계획발표 대본을 작성하고 있습니다.",
    "plan_review": "계획서·PPT·대본에 대한 참여자 검토를 기다리고 있습니다.",
    "experiment_discussion": "추가 실험 여부와 방법을 논의하고 있습니다.",
    "experiment_cases": "비교 실험용 입력 사례를 만들고 있습니다.",
    "experiment_run": "네 모델의 실제 BAZE 응답을 독립적으로 수집하고 있습니다.",
    "experiment_analysis": "관찰 결과와 재표본추출 시뮬레이션을 분석하고 있습니다.",
    "middle_slides": "중간발표 PPT를 작성하고 있습니다.",
    "middle_script": "중간발표 대본을 작성하고 있습니다.",
    "middle_review": "중간발표 자료에 대한 참여자 검토를 기다리고 있습니다.",
    "final_discussion": "결과·반례·한계를 검토하고 추가 실험 여부를 결정하고 있습니다.",
    "final_report": "최종보고서를 작성하고 있습니다.",
    "final_slides": "최종발표 PPT를 작성하고 있습니다.",
    "final_script": "최종발표 대본을 작성하고 있습니다.",
    "final_review": "최종보고서·PPT·대본에 대한 참여자 검토를 기다리고 있습니다.",
    "completed": "최종 검토가 승인되어 연구가 완료됐습니다.",
}
SIGNAL = re.compile(r"^(?:MY_ROLE|ROLE_(?:GPT|CLAUDE|GEMINI|GROK)|RESEARCH_TOPIC|RESEARCH_QUESTION|NEXT|TOPIC_CHANGE_REASON|PRIOR_RESULTS_IMPACT)\s*[:：]", re.I)


def excerpt(content: str, limit: int = 300) -> str:
    """Prefer explicit decisions, otherwise retain a short factual quotation."""
    lines = [re.sub(r"\s+", " ", line.strip(" #*`\t-")) for line in content.splitlines()]
    signals = [line for line in lines if SIGNAL.match(line)]
    candidates = signals or [line for line in lines if len(line) >= 12 and line != "---"]
    selected = " · ".join(candidates[:2]) if candidates else content.strip()
    return selected[:limit] + ("…" if len(selected) > limit else "")


def build_overview(transcript: Path | None, *, topic: str, question: str,
                   roles: dict, models: dict, assignments: dict, call_order: tuple,
                   status: str, stage: str, current_model: str, auto: dict,
                   activities: list[dict]) -> dict:
    """Read all archived messages, including turns no longer in the chat state."""
    groups: OrderedDict[str, dict] = OrderedDict()
    milestones: list[dict] = []
    human_input: list[dict] = []
    counts = {"all": 0, "models": 0, "people": 0, "system": 0}
    first_at = last_at = ""
    if transcript and transcript.is_file():
        with transcript.open(encoding="utf-8") as source:
            for line in source:
                try:
                    message = json.loads(line)
                except (ValueError, TypeError):
                    continue  # An unfinished append must not break the dashboard.
                if not isinstance(message, dict):
                    continue
                actor = message.get("actor", "")
                if actor not in ("model", "system", "user", "friend", "member3", "member4"):
                    continue
                counts["all"] += 1
                counts["models" if actor == "model" else "system" if actor == "system" else "people"] += 1
                first_at = first_at or message.get("at", "")
                last_at = message.get("at", "")
                content = str(message.get("content", ""))
                if actor == "model":
                    phase = str(message.get("phase", ""))
                    key, title = GROUPS.get(phase, (phase or "other", "기타 연구 대화"))
                    group = groups.setdefault(key, {"key": key, "title": title, "count": 0, "by_model": {}, "highlights": {}})
                    group["count"] += 1
                    provider = str(message.get("provider", ""))
                    if provider in PROVIDERS:
                        group["by_model"][provider] = group["by_model"].get(provider, 0) + 1
                        if phase != "experiment_run":
                            group["highlights"][provider] = {"provider": provider, "text": excerpt(content),
                                                             "at": message.get("at", "")}
                elif actor == "system" and any(marker in content for marker in
                                                ("역할 합의", "주제 변경", "자료가 준비", "실험 사례", "일시정지", "잔액")):
                    milestones.append({"text": excerpt(content, 260), "at": message.get("at", "")})
                    milestones = milestones[-12:]
                elif actor != "system":
                    human_input.append({"actor": actor, "text": excerpt(content, 260), "at": message.get("at", "")})
                    human_input = human_input[-8:]
    sections = [{**{k: v for k, v in group.items() if k != "highlights"},
                 "highlights": [group["highlights"][name] for name in PROVIDERS if name in group["highlights"]]}
                for group in groups.values()]
    current = current_model or (call_order[int(auto.get("speaker_index", 0)) % len(call_order)]
                                if call_order and stage in ("roles", "topic", "plan_discussion",
                                                            "experiment_discussion", "final_discussion") else "")
    task = STAGE_TASKS.get(stage, "연구를 시작하면 현재 작업이 표시됩니다.")
    if status == "waiting_budget":
        task = f"{task} 현재 크레딧이 0인 계정의 보충을 기다립니다."
    elif status == "paused":
        task = f"{task} 연구가 일시정지됐습니다."
    elif status == "stopped":
        task = "연구가 중지됐습니다."
    elif status == "failed":
        task = "오류로 연구가 멈췄습니다. 활동 기록을 확인하세요."
    assignments_view = [{"provider": provider, "model": models.get(provider, ""),
                         "account": LABELS.get(assignments.get(provider, ""), ""),
                         "role": roles.get(provider, "아직 협의 중"),
                         "state": "응답 대기" if status == "running" and current_model == provider else
                                  "다음 발언" if status == "running" and current == provider else "대기"}
                        for provider in PROVIDERS]
    return {
        "topic": topic, "question": question, "counts": counts, "first_at": first_at, "last_at": last_at,
        "sections": sections, "milestones": milestones, "human_input": human_input,
        "roles": assignments_view, "reviews": list(auto.get("reviews", [])),
        "current": {"stage": stage, "status": status, "task": task, "provider": current,
                    "reason": auto.get("reason", ""), "next_due_at": auto.get("next_due_at", ""),
                    "observation_count": len(auto.get("observations", [])),
                    "pending_calls": len(auto.get("queue", [])), "cycle": auto.get("cycle", 0)},
        "call_count": len(activities),
    }
