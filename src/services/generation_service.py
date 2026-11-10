
import re

from src.schemas.generation import (
    GenerateResponse,
    RetrievedChunk,
)

from src.services.llm_service import generate_answer
from src.services.claim_service import extract_claims
from src.services.verification_service import verify_claim


# ==========================================
# 1. 답변을 문장 및 목록 단위로 분리
# ==========================================

def split_answer_units(answer: str) -> list[str]:
    """
    AI 답변을 문장 및 목록 항목 단위로 분리한다.

    일반 문장은 문장부호를 기준으로 분리하고,
    목록 항목은 각각 하나의 단위로 보존한다.
    """

    units = []

    for line in answer.splitlines():
        line = line.strip()

        if not line:
            continue

        # 목록 항목은 하나의 단위로 유지
        if re.match(r"^[-*•]\s+", line):
            units.append(line)
            continue

        # 번호가 있는 목록도 하나의 단위로 유지
        if re.match(r"^\d+[.)]\s+", line):
            units.append(line)
            continue

        # 일반 문장은 문장 단위로 분리
        sentences = re.split(
            r"(?<=[.!?。])\s+",
            line,
        )

        for sentence in sentences:
            sentence = sentence.strip()

            if sentence:
                units.append(sentence)

    return units


# ==========================================
# 2. AI 답변 요약
# ==========================================

def summarize_answer(
    answer: str,
    max_length: int = 350,
) -> str:
    """
    답변에서 핵심 정보를 추출하여 요약한다.

    지원 대상, 제외 조건 등 중요한 정보는
    가능한 한 유지한다.

    외부 API를 호출하지 않는다.
    """

    answer = answer.strip()

    if not answer:
        return ""

    # 이미 충분히 짧으면 원문 반환
    if len(answer) <= max_length:
        return answer

    units = split_answer_units(answer)

    if not units:
        return answer[:max_length]

    important_keywords = [
        "지원 대상",
        "지원대상",
        "지원 연령",
        "연령 상한",
        "제외",
        "지원 불가",
        "지원이 불가",
        "지원할 수 없",
        "기수혜자",
        "수혜 중",
    ]

    selected_indices = set()

    # 첫 문장 유지
    selected_indices.add(0)

    # 중요한 조건이 포함된 문장 선택
    for i, unit in enumerate(units):
        if any(
            keyword in unit
            for keyword in important_keywords
        ):
            selected_indices.add(i)

    # 제외 대상 목록이 이어지는 경우
    # 해당 목록도 함께 선택
    for i, unit in enumerate(units):
        if (
            "다음에 해당" in unit
            or "다음의 경우" in unit
        ):
            selected_indices.add(i)

            j = i + 1

            while j < len(units):
                next_unit = units[j]

                if re.match(
                    r"^[-*•]\s+",
                    next_unit,
                ):
                    selected_indices.add(j)
                    j += 1
                else:
                    break

    # 중요한 문장을 먼저 선택
    selected = [
        units[i]
        for i in sorted(selected_indices)
    ]

    # 남은 길이에 일반 문장 추가
    current_length = len(
        "\n".join(selected)
    )

    for i, unit in enumerate(units):

        if i in selected_indices:
            continue

        additional_length = len(unit) + 1

        if (
            current_length + additional_length
            <= max_length
        ):
            selected_indices.add(i)
            current_length += additional_length

    # 원래 답변 순서 유지
    summary = "\n".join(
        units[i]
        for i in sorted(selected_indices)
    )

    return summary


# ==========================================
# 3. 전체 AI 답변 생성 파이프라인
# ==========================================

def run_generation(
    task_id: int,
    question: str,
    context: str,
    document_id: int | None = None,
    chunk_id: int | None = None,
    page_number: int | None = None,
    retrieved_chunks: list[RetrievedChunk] | None = None,
) -> GenerateResponse:
    """
    C.A.S.T. AI 답변 생성 파이프라인.

    처리 순서:
    1. PDF 청크를 이용한 답변 생성
    2. 답변에서 Claim 추출
    3. 각 Claim 사실 검증
    4. 답변 요약
    5. 최종 결과 반환

    기존 단일 청크 방식과
    새로운 다중 청크 방식을 모두 지원한다.
    """

    # --------------------------------------
    # 1. 답변 생성용 문맥 구성
    # --------------------------------------

    if retrieved_chunks:
        context = "\n\n".join(
            chunk.content
            for chunk in retrieved_chunks
        )

    # --------------------------------------
    # 2. AI 답변 생성
    # --------------------------------------

    print("[1/4] AI 답변 생성 중...")

    answer = generate_answer(
        question,
        context,
    )

    # --------------------------------------
    # 3. Claim 추출
    # --------------------------------------

    print("[2/4] Claim 추출 중...")

    claims = extract_claims(answer)

    # --------------------------------------
    # 4. Claim 사실 검증
    # --------------------------------------

    print("[3/4] Claim 사실 검증 중...")

    verified_claims = []

    for claim in claims:

        verified_claim = verify_claim(
            claim=claim,
            context=context,
            document_id=document_id,
            chunk_id=chunk_id,
            page_number=page_number,
            retrieved_chunks=retrieved_chunks,
        )

        verified_claims.append(
            verified_claim
        )

    # --------------------------------------
    # 5. 답변 요약
    # --------------------------------------

    print("[4/4] AI 답변 요약 중...")

    summary = summarize_answer(answer)

    # --------------------------------------
    # 6. 최종 결과 반환
    # --------------------------------------

    result = GenerateResponse(
        task_id=task_id,
        answer=answer,
        summary=summary,
        claims=verified_claims,
    )

    return result
