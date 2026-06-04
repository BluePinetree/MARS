"""
LanceDB-backed lightweight knowledge tools for AutoGen agents.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


class LanceKnowledgeStore:
    """Simple local LanceDB vector store wrapper."""

    def __init__(
        self,
        db_path: str = "./data/lance_db",
        table_name: str = "research_knowledge",
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        top_k: int = 5,
    ) -> None:
        self._db_path = db_path
        self._table_name = table_name
        self._embedding_model_name = embedding_model
        self._top_k = top_k

        self._db = None
        self._table = None
        self._embedding_model = None
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return

        try:
            import lancedb
        except ImportError as exc:
            raise ImportError(
                "lancedb is not installed. Install: pip install lancedb sentence-transformers"
            ) from exc

        os.makedirs(self._db_path, exist_ok=True)
        self._db = lancedb.connect(self._db_path)

        existing_tables = set(self._db.table_names())
        if self._table_name in existing_tables:
            self._table = self._db.open_table(self._table_name)
            logger.info(
                "[LanceDB] opened table '%s' (%s rows)",
                self._table_name,
                self._table.count_rows(),
            )
        else:
            logger.info("[LanceDB] table '%s' not found; it will be created on first insert.", self._table_name)

        self._initialized = True

    def _load_embedding_model(self) -> None:
        if self._embedding_model is not None:
            return

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is not installed. Install: pip install sentence-transformers"
            ) from exc

        self._embedding_model = SentenceTransformer(self._embedding_model_name)
        logger.info("[LanceDB] loaded embedding model: %s", self._embedding_model_name)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        self._load_embedding_model()
        embeddings = self._embedding_model.encode(texts, show_progress_bar=False)
        return embeddings.tolist()

    def add_documents(
        self,
        texts: list[str],
        metadata_list: list[dict[str, Any]] | None = None,
        source: str = "manual",
    ) -> int:
        self._ensure_initialized()

        if not texts:
            return 0

        embeddings = self._embed(texts)
        rows: list[dict[str, Any]] = []
        for idx, (text, embedding) in enumerate(zip(texts, embeddings)):
            metadata = metadata_list[idx] if metadata_list and idx < len(metadata_list) else {}
            rows.append(
                {
                    "text": text,
                    "vector": embedding,
                    "source": source,
                    "metadata": str(metadata),
                }
            )

        if self._table is None:
            self._table = self._db.create_table(self._table_name, data=rows)
            logger.info("[LanceDB] created table '%s' and inserted %s docs", self._table_name, len(rows))
        else:
            self._table.add(rows)
            logger.info("[LanceDB] inserted %s docs", len(rows))

        return len(rows)

    def search(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        self._ensure_initialized()

        if self._table is None:
            return []

        query_embedding = self._embed([query])[0]
        k = top_k or self._top_k

        results = self._table.search(query_embedding).limit(k).to_list()

        return [
            {
                "text": item.get("text", ""),
                "score": item.get("_distance", 0.0),
                "source": item.get("source", "unknown"),
                "metadata": item.get("metadata", "{}"),
            }
            for item in results
        ]

    def get_document_count(self) -> int:
        self._ensure_initialized()
        if self._table is None:
            return 0
        return int(self._table.count_rows())

    def clear(self) -> None:
        self._ensure_initialized()
        if self._db and self._table_name in self._db.table_names():
            self._db.drop_table(self._table_name)
            self._table = None


_knowledge_store: Optional[LanceKnowledgeStore] = None
_query_max_chars: int = 1500
_last_query_diagnostics: dict[str, Any] = {}


def get_last_lancedb_query_diagnostics() -> dict[str, Any]:
    """Return latest query diagnostics for failure attribution/logging."""
    return dict(_last_query_diagnostics)


def _get_store() -> LanceKnowledgeStore:
    global _knowledge_store
    if _knowledge_store is None:
        _knowledge_store = LanceKnowledgeStore()
    return _knowledge_store


def init_knowledge_store(
    db_path: str = "./data/lance_db",
    table_name: str = "research_knowledge",
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    top_k: int = 5,
    query_max_chars: int = 1500,
) -> LanceKnowledgeStore:
    """Initialize global LanceDB store used by tool functions."""
    global _knowledge_store, _query_max_chars
    _knowledge_store = LanceKnowledgeStore(
        db_path=db_path,
        table_name=table_name,
        embedding_model=embedding_model,
        top_k=top_k,
    )
    _query_max_chars = max(200, int(query_max_chars))
    return _knowledge_store


def search_knowledge(query: str, top_k: int = 5) -> str:
    """Search related documents and return a compact text summary."""
    global _last_query_diagnostics

    query = query or ""
    original_len = len(query)
    capped_query = query[:_query_max_chars]
    capped_len = len(capped_query)
    truncated = capped_len < original_len

    _last_query_diagnostics = {
        "tool": "lancedb_search",
        "query_length": original_len,
        "query_length_capped": capped_len,
        "truncated": truncated,
        "status": "pending",
        "failure_point": "collection.query",
    }

    try:
        store = _get_store()
        results = store.search(capped_query, top_k=top_k)
        _last_query_diagnostics["status"] = "success"
        _last_query_diagnostics["result_count"] = len(results)

        if not results:
            return f"[search] no results for query='{capped_query}'."

        lines: list[str] = [f"[search] top {len(results)} results for '{capped_query}':"]
        if truncated:
            lines.append(
                f"(query capped: original_length={original_len}, capped_length={capped_len})"
            )
        for index, item in enumerate(results, 1):
            text = item["text"].strip()
            preview = text if len(text) <= 300 else f"{text[:300]}..."
            lines.append(
                (
                    f"--- result {index} "
                    f"(distance={item['score']:.4f}, source={item['source']}) ---\n"
                    f"{preview}"
                )
            )
        return "\n".join(lines)

    except Exception as exc:
        _last_query_diagnostics["status"] = "failure"
        _last_query_diagnostics["error_type"] = type(exc).__name__
        _last_query_diagnostics["error_message"] = str(exc)
        raise RuntimeError(
            "collection.query failed "
            f"(query_length={original_len}, capped_length={capped_len}): {exc}"
        ) from exc


def add_knowledge(text: str, source: str = "agent") -> str:
    """Insert one text record into the local knowledge store."""
    try:
        store = _get_store()
        added = store.add_documents([text], source=source)
        total = store.get_document_count()
        return f"[knowledge] added={added}, total_documents={total}, source={source}"
    except Exception as exc:
        return f"[knowledge][error] {type(exc).__name__}: {exc}"
