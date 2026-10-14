"""Auditable, multi-model topic voting and evidence-limited role assignment."""

from __future__ import annotations

import itertools
import json
import re


DOMAINS = ("AI", "물리", "수학", "정보")
COMPETENCIES = {
    "theory": "이론·수학적 검증",
    "experiment": "실험 설계·측정",
    "implementation": "정보·구현·데이터 분석",
    "critique": "반례·재현성·보고서 검토",
}


def marked_json(text: str, marker: str):
    found = re.search(r"^" + re.escape(marker) + r"\s*[:：]\s*", text, re.I | re.M)
    if not found:
        return None
    tail = text[found.end():].lstrip()
    if tail.startswith("```"):
        tail = tail.split("\n", 1)[-1].lstrip()
    try:
        return json.JSONDecoder().raw_decode(tail)[0]
    except (TypeError, ValueError):
        return None


def candidates_from_reply(text: str, provider: str, start_index: int) -> list[dict]:
    payload = marked_json(text, "CANDIDATES_JSON")
    if not isinstance(payload, list):
        return []
    candidates = []
    for item in payload[:3]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()[:200]
        question = str(item.get("question", "")).strip()[:400]
        domain = str(item.get("domain", "")).strip()
        domain = {"인공지능": "AI", "ai": "AI", "물리학": "물리", "수학과": "수학",
                  "컴퓨터": "정보", "컴퓨터과학": "정보", "정보과학": "정보"}.get(domain, domain)
        method = str(item.get("method", "")).strip()[:500]
        if len(title) < 6 or len(question) < 10 or domain not in DOMAINS or len(method) < 10:
            continue
        candidates.append({"id": f"C{start_index + len(candidates):02d}", "provider": provider,
                           "title": title, "question": question, "domain": domain,
                           "method": method})
    return candidates


def ranking_from_reply(text: str, valid_ids: set[str]) -> list[str]:
    found = re.search(r"^RANKING\s*[:：]\s*(.+)$", text, re.I | re.M)
    if not found:
        return []
    ranking = re.findall(r"C\d{2}", found.group(1).upper())
    return ranking if len(ranking) >= 3 and len(ranking) == len(set(ranking)) and all(
        item in valid_ids for item in ranking) else []


def select_topic(candidates: list[dict], ballots: dict[str, list[str]]) -> tuple[dict, list[dict]]:
    if len(ballots) != 4 or not candidates:
        raise ValueError("네 모델의 유효한 주제 순위가 모두 필요합니다.")
    scores = {candidate["id"]: 0 for candidate in candidates}
    firsts = {candidate["id"]: 0 for candidate in candidates}
    for ranking in ballots.values():
        for position, candidate_id in enumerate(ranking):
            scores[candidate_id] += max(1, len(ranking) - position)
        firsts[ranking[0]] += 1
    ordered = sorted(candidates, key=lambda item: (-scores[item["id"]],
                                                 -firsts[item["id"]], item["id"]))
    comparison = [{**item, "points": scores[item["id"]], "first_votes": firsts[item["id"]]}
                  for item in ordered]
    return ordered[0], comparison


def role_scores_from_reply(text: str, providers: tuple[str, ...]) -> dict[str, dict[str, int]]:
    payload = marked_json(text, "SCORES_JSON")
    if not isinstance(payload, dict):
        return {}
    result = {}
    for provider in providers:
        row = payload.get(provider)
        if not isinstance(row, dict):
            continue
        scores = {}
        for competency in COMPETENCIES:
            value = row.get(competency)
            if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 5:
                scores[competency] = value
        if len(scores) == len(COMPETENCIES):
            result[provider] = scores
    return result


def assign_roles(providers: tuple[str, ...], reviews: dict[str, dict]) -> tuple[dict, dict]:
    if set(reviews) != set(providers):
        raise ValueError("네 모델의 동료 평가가 모두 필요합니다.")
    scores = {}
    for provider in providers:
        scores[provider] = {}
        for competency in COMPETENCIES:
            other_reviews = [review[provider][competency] for judge, review in reviews.items()
                             if judge != provider and provider in review]
            if len(other_reviews) != 3:
                raise ValueError("모든 역할에 대해 다른 세 모델의 평가가 필요합니다.")
            scores[provider][competency] = round(sum(other_reviews) / 3, 3)
    best = max(itertools.permutations(COMPETENCIES),
               key=lambda roles: (sum(scores[provider][role] for provider, role in zip(providers, roles)),
                                  tuple(-list(COMPETENCIES).index(role) for role in roles)))
    return {provider: COMPETENCIES[role] for provider, role in zip(providers, best)}, scores
