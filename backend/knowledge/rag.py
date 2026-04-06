"""ChromaDB knowledge base for data center operations runbooks.

Loads runbook markdown files, chunks them, and stores embeddings in
ChromaDB using the all-MiniLM-L6-v2 sentence transformer model. Provides
vector search for the triage agent's search_runbooks tool and the
standalone RAG Q&A endpoint.
"""

import logging
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from backend.config import settings

logger = logging.getLogger(__name__)

_collection: chromadb.Collection | None = None
_client: chromadb.ClientAPI | None = None

RUNBOOKS_DIR = Path(__file__).parent / "runbooks"
CHUNK_SIZE = 800       # Characters (~200 tokens)
CHUNK_OVERLAP = 200    # Characters (~50 tokens)


def _chunk_text(text: str, source: str) -> list[dict]:
    """Split text into overlapping chunks with metadata."""
    chunks = []
    lines = text.split("\n")
    current_section = "overview"
    current_chunk = []
    current_len = 0

    for line in lines:
        # Track section headers for metadata
        if line.startswith("## "):
            current_section = line.lstrip("# ").strip().lower().replace(" ", "_")

        current_chunk.append(line)
        current_len += len(line) + 1

        if current_len >= CHUNK_SIZE:
            chunk_text = "\n".join(current_chunk)
            chunks.append({
                "text": chunk_text,
                "source": source,
                "section": current_section,
            })
            # Keep overlap
            overlap_chars = 0
            overlap_start = len(current_chunk)
            for i in range(len(current_chunk) - 1, -1, -1):
                overlap_chars += len(current_chunk[i]) + 1
                if overlap_chars >= CHUNK_OVERLAP:
                    overlap_start = i
                    break
            current_chunk = current_chunk[overlap_start:]
            current_len = sum(len(line) + 1 for line in current_chunk)

    # Don't forget the last chunk
    if current_chunk:
        chunk_text = "\n".join(current_chunk)
        if chunk_text.strip():
            chunks.append({
                "text": chunk_text,
                "source": source,
                "section": current_section,
            })

    return chunks


async def init_knowledge_base() -> None:
    """Load runbook documents into ChromaDB, creating embeddings."""
    global _collection, _client

    chroma_path = Path(settings.CHROMA_PATH)
    chroma_path.mkdir(parents=True, exist_ok=True)

    embedding_fn = SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2",
    )

    _client = chromadb.PersistentClient(path=str(chroma_path))
    _collection = _client.get_or_create_collection(
        name="runbooks",
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )

    # Check if already populated
    if _collection.count() > 0:
        logger.info("Knowledge base already loaded (%d chunks)", _collection.count())
        return

    # Load and chunk all runbook files
    runbook_files = sorted(RUNBOOKS_DIR.glob("*.md"))
    if not runbook_files:
        logger.warning("No runbook files found in %s", RUNBOOKS_DIR)
        return

    all_chunks = []
    for filepath in runbook_files:
        text = filepath.read_text(encoding="utf-8")
        chunks = _chunk_text(text, filepath.name)
        all_chunks.extend(chunks)
        logger.debug("Chunked %s into %d pieces", filepath.name, len(chunks))

    # Batch insert into ChromaDB
    _collection.add(
        ids=[f"chunk-{i}" for i in range(len(all_chunks))],
        documents=[c["text"] for c in all_chunks],
        metadatas=[{"source": c["source"], "section": c["section"]} for c in all_chunks],
    )

    logger.info("Loaded %d chunks from %d runbooks into knowledge base",
                len(all_chunks), len(runbook_files))


def search_runbooks(query: str, n_results: int = 3) -> list[dict]:
    """Search the runbook knowledge base and return relevant chunks.

    Args:
        query: Natural language search query.
        n_results: Number of results to return.

    Returns:
        List of dicts with 'text', 'source', and 'section' keys.
    """
    if _collection is None:
        logger.warning("Knowledge base not initialized")
        return []

    results = _collection.query(
        query_texts=[query],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        chunks.append({
            "text": doc,
            "source": meta["source"],
            "section": meta["section"],
            "relevance_score": round(1 - dist, 3),
        })

    return chunks
