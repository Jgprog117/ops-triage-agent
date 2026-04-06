"""Knowledge base RAG Q&A endpoint."""

from fastapi import APIRouter

from backend.db.database import insert_audit_log
from backend.db.models import KnowledgeQuery
from backend.knowledge.qa import answer_question

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.post("/ask")
async def ask_knowledge_base(body: KnowledgeQuery) -> dict:
    """Answer a question using RAG over the data center runbooks."""
    await insert_audit_log("knowledge_query", details={"query": body.query})
    result = await answer_question(body.query)
    return result
