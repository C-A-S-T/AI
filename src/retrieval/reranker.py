
"""Rule-based reranking for policy document retrieval."""

from __future__ import annotations

from typing import Any


INTENT_KEYWORDS = {
    "amount": {
        "question": ["얼마", "금액", "지원금", "몇 원"],
        "document": ["지원금액", "지원내용", "월 최대", "만원"],
    },
    "eligibility": {
        "question": ["누구", "대상", "자격", "조건"],
        "document": ["지원대상", "신청자격", "신청 대상", "자격요건"],
    },
    "period": {
        "question": ["언제", "기간", "마감", "접수일"],
        "document": ["신청기간", "접수기간", "신청접수", "접수마감"],
    },
}


def detect_intent(question: str) -> str | None:
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(word in question for word in keywords["question"]):
            return intent
    return None


def rerank_chunks(
    question: str,
    retrieved_chunks: list[dict[str, Any]],
    top_k: int = 5,
) -> list[dict[str, Any]]:
    if top_k <= 0:
        raise ValueError("top_k must be positive")

    if not retrieved_chunks:
        return []

    intent = detect_intent(question)
    reranked = []

    for chunk in retrieved_chunks:
        bonus = 0.0

        if intent:
            keywords = INTENT_KEYWORDS[intent]["document"]
            bonus = sum(
                1.0 for keyword in keywords
                if keyword in chunk["content"]
            )

        reranked.append({
            **chunk,
            "rerank_score": bonus,
        })

    reranked.sort(
        key=lambda item: item["rerank_score"],
        reverse=True,
    )

    return reranked[:top_k]
