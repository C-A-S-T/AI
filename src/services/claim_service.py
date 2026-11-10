
import json
import os

from dotenv import load_dotenv
from openai import OpenAI

from src.schemas.generation import ClaimResult


load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

MODEL = "gpt-4.1-mini"

VALID_CLAIM_TYPES = {
    "DATE",
    "AMOUNT",
    "TARGET",
    "CONDITION",
}


def extract_claims(answer: str) -> list[ClaimResult]:
    """
    AI 답변에서 독립적으로 검증 가능한
    정책 관련 사실 주장을 추출한다.
    """

    if not answer.strip():
        return []

    response = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "당신은 C.A.S.T.의 정책 Claim 추출 AI입니다.\n"
                    "AI 답변에서 독립적으로 검증 가능한 "
                    "사실 주장을 추출하세요.\n\n"

                    "Claim 유형:\n"
                    "DATE: 신청 기간, 마감일, 시행일, 지급일 등 날짜 관련 사실\n"
                    "AMOUNT: 지원 금액, 소득 기준, 금전 관련 수치\n"
                    "TARGET: 지원 대상, 연령, 거주 요건\n"
                    "CONDITION: 자격 조건, 제외 조건, 예외 조건, 신청 유형\n\n"

                    "추출 규칙:\n"
                    "1. 답변의 모든 문장과 목록을 확인하세요.\n"
                    "2. 독립적으로 참 또는 거짓을 판단할 수 있는 "
                    "완전한 사실 주장만 추출하세요.\n"
                    "3. 정책명, 사업명, 연도만 나열한 표현은 "
                    "독립적인 Claim으로 추출하지 마세요.\n"
                    "4. 단순한 제목, 주제 소개, 문장 조각은 제외하세요.\n"
                    "5. 서로 다른 사실은 가능한 한 별도의 Claim으로 분리하세요.\n"
                    "6. 지원 대상, 지원 금액, 신청 기간, 제외 조건, "
                    "예외 조건 등을 누락하지 마세요.\n"
                    "7. 날짜, 금액, 연령 등 숫자는 원문 그대로 유지하세요.\n"
                    "8. 원래 답변에 없는 사실을 추가하지 마세요.\n"
                    "9. 동일한 사실을 중복 추출하지 마세요.\n"
                    "10. 하나의 정책 분류 목록은 필요한 경우 "
                    "하나의 복합 Claim으로 유지할 수 있습니다.\n"
                    "11. 각 Claim은 다른 Claim 없이도 "
                    "의미를 이해할 수 있어야 합니다.\n"
                    "12. 정책명과 연도는 Claim의 대상을 명확하게 하는 데 "
                    "필요한 경우에만 포함하세요.\n"
                    "13. 정책명에 포함된 연도를 별도의 DATE Claim으로 "
                    "자동 추출하지 마세요.\n"
                    "14. 실제 시행 연도나 신청 기간에 관한 명시적인 "
                    "사실 주장은 DATE Claim으로 추출하세요.\n"
                    "15. Claim 유형은 DATE, AMOUNT, TARGET, CONDITION 중 "
                    "하나만 사용하세요.\n"
                    "16. 출력 전 누락된 사실과 불완전한 Claim이 "
                    "없는지 다시 확인하세요.\n"
                    "17. 반드시 JSON 객체만 출력하세요.\n\n"

                    "올바른 추출 예시:\n"
                    "답변: 2026년 청년월세지원 사업의 지원 대상은 "
                    "19세부터 39세까지의 청년이며, "
                    "지원 금액은 월 20만 원입니다.\n"
                    "출력:\n"
                    '{"claims": ['
                    '{"content": "2026년 청년월세지원 사업의 지원 대상은 '
                    '19세부터 39세까지의 청년이다.", '
                    '"claim_type": "TARGET"}, '
                    '{"content": "2026년 청년월세지원 사업의 지원 금액은 '
                    '월 20만 원이다.", '
                    '"claim_type": "AMOUNT"}'
                    "]}\n\n"

                    "잘못된 추출 예시:\n"
                    '{"content": "2026년 청년월세지원 사업이다.", '
                    '"claim_type": "DATE"}\n'
                    "이 문장은 독립적으로 검증할 수 있는 "
                    "완전한 사실 주장이 아니므로 제외합니다."
                ),
            },
            {
                "role": "user",
                "content": (
                    "[다음 AI 답변에서 독립적으로 검증 가능한 "
                    "사실 주장만 빠짐없이 추출하세요.]\n\n"
                    f"{answer}"
                ),
            },
        ],
        response_format={
            "type": "json_object"
        },
    )

    # GPT 응답 JSON 파싱
    try:
        result = json.loads(
            response.choices[0].message.content or "{}"
        )
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(result, dict):
        return []

    raw_claims = result.get("claims", [])

    if not isinstance(raw_claims, list):
        return []

    claims = []
    seen_contents = set()

    for item in raw_claims:

        if not isinstance(item, dict):
            continue

        content = item.get("content", "")
        claim_type = item.get("claim_type", "")

        if not isinstance(content, str):
            continue

        content = content.strip()

        if not content:
            continue

        if claim_type not in VALID_CLAIM_TYPES:
            continue

        # 동일한 Claim 중복 제거
        if content in seen_contents:
            continue

        seen_contents.add(content)

        claims.append(
            ClaimResult(
                content=content,
                claim_type=claim_type,
                verification_status="INSUFFICIENT",
                evidence=[],
            )
        )

    return claims
