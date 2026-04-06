"""RAG-powered Q&A endpoint for the knowledge base.

Retrieves relevant runbook chunks via vector search, then sends them
to the LLM with the user's question for a grounded, cited answer.
"""

import logging
from typing import Any

from backend.knowledge.rag import search_runbooks
from backend.llm.client import llm

logger = logging.getLogger(__name__)

QA_SYSTEM_PROMPT = """You are a knowledgeable data center operations assistant for ai&'s dc-tokyo-01 facility. Answer the question based on the provided runbook excerpts. Be specific and actionable.

Rules:
- Cite which runbook you're referencing (e.g., "According to gpu_thermal_throttling.md...")
- If the answer isn't fully covered in the runbooks, say so clearly
- Include specific thresholds, commands, and procedures when available
- Keep your answer concise but complete"""


async def answer_question(query: str) -> dict[str, Any]:
    """Answer a question using RAG over the runbook knowledge base.

    Args:
        query: The user's natural language question.

    Returns:
        Dict with 'answer' (str) and 'sources' (list of source dicts).
    """
    # Retrieve relevant chunks
    chunks = search_runbooks(query, n_results=5)

    if not chunks:
        return {
            "answer": "The knowledge base is not yet initialized. Please wait for the system to finish loading runbooks.",
            "sources": [],
        }

    # Build context from chunks
    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        context_parts.append(
            f"--- Runbook: {chunk['source']} (section: {chunk['section']}) ---\n{chunk['text']}"
        )
    context = "\n\n".join(context_parts)

    messages = [
        {"role": "system", "content": QA_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Runbook excerpts:\n\n{context}\n\n---\n\nQuestion: {query}",
        },
    ]

    try:
        response = await llm.chat_completion(messages, temperature=0.3)
        answer = llm.get_content(llm.extract_message(response))
    except Exception:
        logger.exception("LLM call failed for knowledge Q&A")
        answer = "Unable to generate an answer at this time. Please check LLM configuration."

    # Deduplicate sources
    seen = set()
    sources = []
    for chunk in chunks:
        if chunk["source"] not in seen:
            seen.add(chunk["source"])
            sources.append({
                "source": chunk["source"],
                "section": chunk["section"],
                "relevance_score": chunk["relevance_score"],
            })

    return {"answer": answer, "sources": sources}
