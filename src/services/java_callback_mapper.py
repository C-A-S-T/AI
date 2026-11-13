
"""Convert verified RAG results into Java callback payloads."""

from uuid import UUID

from src.schemas.generation import GenerateResponse
from src.services.citation_metadata import get_citation_metadata


MAX_CLAIMS = 500
MAX_CITATIONS_PER_CLAIM = 100

VALID_CLAIM_TYPES = {
    "DATE", "AMOUNT", "TARGET", "CONDITION"
}

VALID_VERIFICATION_STATUSES = {
    "SUPPORTED",
    "CONTRADICTED",
    "PARTIAL",
    "INSUFFICIENT",
}

VALID_CITATION_RELATIONS = {
    "SUPPORTS", "CONTRADICTS", "NEUTRAL"
}


def build_java_callback(
    job_id: UUID,
    result: GenerateResponse,
) -> dict:
    """Build and validate a Java-compatible SUCCESS callback."""

    if not isinstance(result.answer, str) or not result.answer.strip():
        raise ValueError("SUCCESS callback requires a nonempty answer")

    if len(result.claims) > MAX_CLAIMS:
        raise ValueError(
            f"Too many claims: maximum {MAX_CLAIMS}"
        )

    claims = []

    for claim in result.claims:
        if not claim.content or not claim.content.strip():
            raise ValueError("Claim content cannot be empty")

        if claim.claim_type not in VALID_CLAIM_TYPES:
            raise ValueError(
                f"Invalid claim type: {claim.claim_type}"
            )

        if claim.verification_status not in VALID_VERIFICATION_STATUSES:
            raise ValueError(
                "Invalid verification status: "
                f"{claim.verification_status}"
            )

        if len(claim.evidence) > MAX_CITATIONS_PER_CLAIM:
            raise ValueError(
                "Too many citations for claim: "
                f"maximum {MAX_CITATIONS_PER_CLAIM}"
            )

        citations = []

        for evidence in claim.evidence:
            if evidence.relation not in VALID_CITATION_RELATIONS:
                raise ValueError(
                    f"Invalid citation relation: {evidence.relation}"
                )

            metadata = get_citation_metadata(
                evidence.document_id,
                evidence.chunk_id,
            )

            if not metadata or not isinstance(metadata, dict):
                raise ValueError("Citation metadata is missing")

            source = metadata.get("source")

            if not isinstance(source, dict):
                raise ValueError("Citation source is missing")

            if source.get("aiDocumentId") is None:
                raise ValueError("Citation document ID is missing")

            if source["aiDocumentId"] != evidence.document_id:
                raise ValueError(
                    "Citation document ID mismatch"
                )

            if metadata.get("aiChunkId") != evidence.chunk_id:
                raise ValueError(
                    "Citation chunk ID mismatch"
                )

            citation_text = (
                evidence.excerpt
                or metadata.get("chunkContent")
            )

            if not isinstance(citation_text, str) or not citation_text.strip():
                raise ValueError("Citation text is missing")

            citations.append({
                "source": source,
                "aiChunkId": metadata["aiChunkId"],
                "text": citation_text,
                "relation": evidence.relation,
                "pageStart": metadata.get("pageStart"),
                "pageEnd": metadata.get("pageEnd"),
                "sectionTitle": metadata.get("sectionTitle"),
            })

        claims.append({
            "content": claim.content,
            "type": claim.claim_type,
            "value": {
                "rawText": claim.content,
            },
            "aiRunId": None,
            "verification": {
                "status": claim.verification_status,
                "reason": "RAG evidence verification result",
                "method": "LLM",
                "ruleResult": None,
                "llmResult": claim.verification_status,
                "confidence": None,
            },
            "citations": citations,
        })

    return {
        "jobId": str(job_id),
        "outcome": "SUCCESS",
        "answer": result.answer,
        "summary": result.summary,
        "errorMessage": None,
        "claims": claims,
    }


def build_java_failure_callback(
    job_id: UUID,
    error_message: str = "AI processing failed",
) -> dict:
    """Build a safe Java-compatible FAILURE callback."""

    safe_message = (
        error_message.strip()
        if isinstance(error_message, str)
        else ""
    )

    if not safe_message:
        safe_message = "AI processing failed"

    return {
        "jobId": str(job_id),
        "outcome": "FAILURE",
        "answer": None,
        "summary": None,
        "errorMessage": safe_message[:500],
        "claims": [],
    }
