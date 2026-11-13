"""Normalize verified claims before backend integration."""

from src.schemas.generation import GenerateResponse


def deduplicate_evidence(result: GenerateResponse) -> GenerateResponse:
    """Remove duplicate evidence entries from each claim."""

    for claim in result.claims:
        seen = set()
        unique_evidence = []

        for evidence in claim.evidence:
            key = (
                evidence.document_id,
                evidence.chunk_id,
                evidence.page_number,
                evidence.relation,
                evidence.excerpt,
            )

            if key in seen:
                continue

            seen.add(key)
            unique_evidence.append(evidence)

        claim.evidence = unique_evidence

    return result
