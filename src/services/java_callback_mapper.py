"""Convert verified RAG results into the Java callback format."""

from uuid import UUID

from src.schemas.generation import GenerateResponse
from src.services.citation_metadata import get_citation_metadata


def build_java_callback(
    job_id: UUID,
    result: GenerateResponse,
) -> dict:
    """Build a Java-compatible SUCCESS callback without inventing facts."""

    claims = []

    for claim in result.claims:
        citations = []

        for evidence in claim.evidence:
            metadata = get_citation_metadata(
                evidence.document_id,
                evidence.chunk_id,
            )

            citations.append({
                "source": metadata["source"],
                "aiChunkId": metadata["aiChunkId"],
                "text": evidence.excerpt or metadata["chunkContent"],
                "relation": evidence.relation,
                "pageStart": metadata["pageStart"],
                "pageEnd": metadata["pageEnd"],
                "sectionTitle": metadata["sectionTitle"],
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
