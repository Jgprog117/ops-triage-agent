"""HTTP route for the runbook knowledge-base Q&A endpoint."""

from fastapi import APIRouter

from backend.db.database import insert_audit_log
from backend.db.models import KnowledgeQuery
from backend.knowledge.qa import answer_question

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.post("/ask")
async def ask_knowledge_base(body: KnowledgeQuery) -> dict:
    """Answers a free-form question against the runbook RAG index.

    Records the query in the audit log so operators can see what
    questions are being asked, then delegates to
    :func:`backend.knowledge.qa.answer_question`. Rate-limited per IP
    by the rate-limit middleware.

    Args:
        body: A request body with a single ``query`` field.

    Returns:
        A dict with ``answer`` and ``sources``, matching the
        :class:`KnowledgeAnswer` model.
    """
    await insert_audit_log("knowledge_query", details={"query": body.query})
    result = await answer_question(body.query)
    return result
