
import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from src.services.research_job_processor import (
    process_next_research_job,
    process_next_callback,
)
from src.services.research_job_protection import (
    JobProtectionConfigError,
    load_job_protection_policy,
    workers_enabled,
)

from src.routers.research_jobs import (
    router as research_jobs_router,
)
from src.routers.policy_compare import router as policy_compare_router

from src.services.generation_service import run_generation
from src.services.ai_auth import verify_ai_service_token
from src.retrieval.pipeline import retrieve_evidence

from src.schemas.generation import (
    GenerateResponse,
    ClaimResult,
    RetrievedChunk,
)

from src.schemas.retrieval import (
    RetrieveRequest,
    RetrieveResponse,
)


logger = logging.getLogger(__name__)


# ==========================================
# 1. AI Research Job Worker
# ==========================================

async def research_job_worker():
    """
    Process pending AI research jobs.

    1. Claim a pending job.
    2. Run RAG and AI generation.
    3. Save the callback payload in PostgreSQL.

    Java callback delivery is handled separately.
    """

    while True:
        try:
            processed = await asyncio.to_thread(
                process_next_research_job
            )

            if not processed:
                await asyncio.sleep(5)

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "Research job worker error"
            )
            await asyncio.sleep(5)


# ==========================================
# 2. Java Callback Worker
# ==========================================

async def callback_worker():
    """
    Deliver persisted AI results to Java.

    1. Find a pending or retryable callback.
    2. Send the stored payload to Java.
    3. Mark delivery as successful or schedule retry.

    Does not rerun RAG or GPT.
    """

    while True:
        try:
            processed = await asyncio.to_thread(
                process_next_callback
            )

            if not processed:
                await asyncio.sleep(5)

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "Callback worker error"
            )
            await asyncio.sleep(5)


# ==========================================
# 3. FastAPI Lifespan
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Start AI and callback workers independently.

    Both workers run while the FastAPI application
    is active.
    """

    # Parse the explicit worker switch and protection policy BEFORE task creation.
    # Invalid protection leaves health/other APIs available but starts no workers.
    try:
        enabled = workers_enabled()
        policy = load_job_protection_policy() if enabled else None
    except JobProtectionConfigError as exc:
        logger.error("Automatic AI workers disabled: %s", exc)
        enabled = False
        policy = None

    if not enabled:
        logger.info("C.A.S.T. automatic AI workers are disabled")
        yield
        return

    logger.info(
        "Automatic AI protection validated: cutover=%s protected_count=%s",
        policy.cutover_at.isoformat(),
        len(policy.protected_job_ids),
    )

    workers = [
        asyncio.create_task(
            research_job_worker(),
            name="research-job-worker",
        ),
        asyncio.create_task(
            callback_worker(),
            name="java-callback-worker",
        ),
    ]

    logger.info(
        "C.A.S.T. AI workers started"
    )

    try:
        yield

    finally:
        for worker in workers:
            worker.cancel()

        for worker in workers:
            with suppress(asyncio.CancelledError):
                await worker

        logger.info(
            "C.A.S.T. AI workers stopped"
        )


# ==========================================
# 4. FastAPI Application
# ==========================================

app = FastAPI(
    title="C.A.S.T. AI Server",
    lifespan=lifespan,
)

app.include_router(
    research_jobs_router
)
app.include_router(policy_compare_router)


# ==========================================
# 5. Java Request Schema
# ==========================================

class GenerateRequest(BaseModel):

    task_id: int = Field(gt=0)

    question: str = Field(min_length=1)

    # Legacy single-context request
    context: str = ""

    document_id: int | None = Field(
        default=None,
        gt=0,
    )

    chunk_id: int | None = Field(
        default=None,
        gt=0,
    )

    page_number: int | None = Field(
        default=None,
        ge=1,
    )

    # Multi-chunk RAG request
    retrieved_chunks: list[RetrievedChunk] = Field(
        default_factory=list,
    )


# ==========================================
# 6. Health Check API
# ==========================================

@app.get("/health")
def health_check():

    return {
        "status": "ok"
    }


# ==========================================
# 7. AI Answer Generation API
# ==========================================

def generate_answer(
    request: GenerateRequest,
):

    # Prefer retrieved chunks when available.
    if request.retrieved_chunks:

        context = "\n\n".join(
            chunk.content
            for chunk in request.retrieved_chunks
        )

        # Do not assign one citation ID
        # to multiple retrieved chunks.
        document_id = None
        chunk_id = None
        page_number = None

    else:

        # Preserve legacy single-context behavior.
        context = request.context
        document_id = request.document_id
        chunk_id = request.chunk_id
        page_number = request.page_number

    result = run_generation(
        task_id=request.task_id,
        question=request.question,
        context=context,
        document_id=document_id,
        chunk_id=chunk_id,
        page_number=page_number,
        retrieved_chunks=request.retrieved_chunks,
    )

    return {
        "task_id": result.task_id,
        "status": "completed",
        "question": request.question,
        "answer": result.answer,
        "summary": result.summary,
        "claims": [
            claim.model_dump()
            for claim in result.claims
        ],
    }


# Legacy direct-context generation is not part of the production RAG pipeline.
# Never expose it by merely setting a flag in a production environment.
def _legacy_generate_enabled() -> bool:
    switch = os.getenv("CAST_AI_ENABLE_LEGACY_GENERATE", "false").strip().lower()
    if switch not in ("true", "false"):
        logger.warning("Legacy /generate disabled: invalid opt-in value")
        return False
    if switch != "true":
        return False

    environment = os.getenv("CAST_AI_ENV", "production").strip().lower()
    if environment not in ("local", "development", "test"):
        logger.warning("Legacy /generate disabled: non-development environment")
        return False
    return True


# Register only in explicit development or test mode. No entry in OpenAPI
# or FastAPI's routing table when the route is disabled.
if _legacy_generate_enabled():
    app.add_api_route(
        "/generate",
        generate_answer,
        methods=["POST"],
        dependencies=[Depends(verify_ai_service_token)],
    )


# ==========================================
# 8. Hybrid RAG Retrieval API
# ==========================================

@app.post(
    "/retrieve",
    response_model=RetrieveResponse,
)
def retrieve_documents(
    request: RetrieveRequest,
):

    results = retrieve_evidence(
        question=request.question,
        document_id=request.document_id,
        top_k=request.top_k,
        candidate_k=max(
            10,
            request.top_k,
        ),
    )

    return RetrieveResponse(
        question=request.question,
        document_id=request.document_id,
        total_results=len(results),
        retrieved_chunks=results,
    )


# ==========================================
# 9. AI Response Structure Test API
# ==========================================

@app.get(
    "/test-generation",
    response_model=GenerateResponse,
)
def test_generation():

    return GenerateResponse(
        task_id=1,
        answer=(
            "청년월세 지원 조건은 "
            "공고문 확인이 필요합니다."
        ),
        summary="청년월세 지원 조건 확인",
        claims=[
            ClaimResult(
                content=(
                    "청년월세 지원 조건은 "
                    "공고문 확인이 필요합니다."
                ),
                claim_type="CONDITION",
                verification_status="INSUFFICIENT",
                evidence=[],
            )
        ],
    )
