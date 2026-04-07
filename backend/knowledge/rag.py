"""Chroma-backed RAG index over the runbook markdown files.

The index is rebuilt automatically on first start (or when an
incompatible on-disk format is detected) by chunking each markdown file
into ~800-character pieces, embedding them with ``all-MiniLM-L6-v2``,
and persisting them to a local Chroma collection. After init, callers
can search via :func:`search_runbooks`.
"""

import logging
from pathlib import Path

import shutil

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
    """Splits a markdown document into overlapping fixed-size chunks.

    Tracks the most recent ``## Section`` heading so each chunk can be
    tagged with its containing section. Chunks are emitted whenever the
    accumulated character count crosses :data:`CHUNK_SIZE`, with the
    trailing :data:`CHUNK_OVERLAP` characters carried into the next
    chunk to preserve continuity across boundaries.

    Args:
        text: The full markdown document text.
        source: The filename used to tag every emitted chunk.

    Returns:
        A list of chunk dicts, each with ``text``, ``source`` and
        ``section`` keys.
    """
    chunks = []
    lines = text.split("\n")
    current_section = "overview"
    current_chunk = []
    current_len = 0

    for line in lines:
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

    if current_chunk:
        chunk_text = "\n".join(current_chunk)
        if chunk_text.strip():
            chunks.append({
                "text": chunk_text,
                "source": source,
                "section": current_section,
            })

    return chunks


def init_knowledge_base() -> None:
    """Initializes (and if necessary populates) the runbook RAG index.

    Opens or creates the persistent Chroma collection at
    :attr:`Settings.CHROMA_PATH`. If the on-disk format is incompatible
    with the installed Chroma version, the directory is wiped and
    recreated. When the collection is empty after init, every markdown
    file under :data:`RUNBOOKS_DIR` is chunked and embedded.

    This is a synchronous, CPU/disk-heavy operation; callers in async
    contexts should run it via :func:`asyncio.to_thread`.
    """
    global _collection, _client

    chroma_path = Path(settings.CHROMA_PATH)
    chroma_path.mkdir(parents=True, exist_ok=True)

    embedding_fn = SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2",
    )

    try:
        _client = chromadb.PersistentClient(path=str(chroma_path))
        _collection = _client.get_or_create_collection(
            name="runbooks",
            embedding_function=embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception:
        logger.warning("ChromaDB data incompatible, rebuilding from scratch")
        shutil.rmtree(chroma_path)
        chroma_path.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(chroma_path))
        _collection = _client.get_or_create_collection(
            name="runbooks",
            embedding_function=embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

    if _collection.count() > 0:
        logger.info("Knowledge base already loaded (%d chunks)", _collection.count())
        return

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

    _collection.add(
        ids=[f"chunk-{i}" for i in range(len(all_chunks))],
        documents=[c["text"] for c in all_chunks],
        metadatas=[{"source": c["source"], "section": c["section"]} for c in all_chunks],
    )

    logger.info("Loaded %d chunks from %d runbooks into knowledge base",
                len(all_chunks), len(runbook_files))


def search_runbooks(query: str, n_results: int = 3) -> list[dict]:
    """Performs a semantic search over the runbook collection.

    Args:
        query: Natural-language query text.
        n_results: Maximum number of chunks to return.

    Returns:
        A list of chunk dicts ordered by similarity, each with ``text``,
        ``source``, ``section``, and a ``relevance_score`` in ``[0, 1]``
        derived from the cosine distance. Returns an empty list when the
        collection has not been initialized.
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
