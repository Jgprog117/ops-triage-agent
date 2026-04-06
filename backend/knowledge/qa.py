import asyncio
import logging

from backend.knowledge.rag import search_runbooks
from backend.llm.client import llm

logger = logging.getLogger(__name__)

QA_SYSTEM_PROMPT = """You are a knowledgeable data center operations assistant for the dc-tokyo-01 facility. Answer the question based on the provided runbook excerpts.

Rules:
- Explain technical terms and acronyms in plain language (e.g., "CRAC unit (cooling system)", "ECC errors (memory fault detection)", "NVLink (GPU-to-GPU connection)")
- Use short paragraphs and bullet points for readability
- Cite which runbook you're referencing
- If the answer isn't fully covered in the runbooks, say so clearly
- Include specific thresholds and procedures when available
- Your audience may not have deep hardware experience — prioritize clarity over jargon
- Keep answers concise — aim for 3-6 short paragraphs max. Avoid large tables; use bullet points instead"""


async def answer_question(query: str) -> dict:
    loop = asyncio.get_running_loop()
    chunks = await loop.run_in_executor(None, lambda: search_runbooks(query, n_results=5))

    if not chunks:
        return {
            "answer": "The knowledge base is not yet initialized. Please wait for the system to finish loading runbooks.",
            "sources": [],
        }

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
