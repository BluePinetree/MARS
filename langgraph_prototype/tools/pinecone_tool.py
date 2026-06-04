"""
Pinecone retrieval tool with query-length guardrails and diagnostics.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    id: str
    score: float
    text: str
    metadata: Dict[str, Any]


_GLOBAL_LAST_QUERY_DIAGNOSTICS: dict[str, Any] = {}


def get_last_pinecone_query_diagnostics() -> dict[str, Any]:
    """Return the latest Pinecone query diagnostics."""
    return dict(_GLOBAL_LAST_QUERY_DIAGNOSTICS)


class PineconeTool:
    """Thin Pinecone wrapper with safe fallbacks."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        index_name: str = "research-papers",
        namespace: str = "default",
        top_k: int = 5,
        embedding_model: str = "text-embedding-3-small",
        embedding_dimension: int = 1536,
        openai_api_key: Optional[str] = None,
        query_max_chars: int = 1500,
    ):
        self.api_key = api_key or os.getenv("PINECONE_API_KEY")
        self.index_name = index_name
        self.namespace = namespace
        self.top_k = top_k
        self.embedding_model = embedding_model
        self.embedding_dimension = embedding_dimension
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self.query_max_chars = max(200, int(query_max_chars))

        self._index = None
        self._client = None
        self._initialized = False

        if self.api_key:
            try:
                self._initialize_pinecone()
            except Exception as exc:
                logger.warning("Pinecone init failed, fallback mode enabled: %s", exc)
        else:
            logger.info("Pinecone API key missing, fallback mode enabled.")

    def _initialize_pinecone(self) -> None:
        from pinecone import Pinecone

        self._client = Pinecone(api_key=self.api_key)
        existing_indexes = [idx.name for idx in self._client.list_indexes()]
        if self.index_name in existing_indexes:
            self._index = self._client.Index(self.index_name)
            self._initialized = True
            logger.info("Connected Pinecone index '%s'", self.index_name)
        else:
            logger.info(
                "Pinecone index '%s' does not exist. Fallback mode until index is created.",
                self.index_name,
            )

    def create_index(self) -> None:
        if not self._client:
            raise RuntimeError("Pinecone client is not initialized.")

        from pinecone import ServerlessSpec

        existing_indexes = [idx.name for idx in self._client.list_indexes()]
        if self.index_name not in existing_indexes:
            self._client.create_index(
                name=self.index_name,
                dimension=self.embedding_dimension,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )

        self._index = self._client.Index(self.index_name)
        self._initialized = True

    def _get_embedding(self, text: str) -> List[float]:
        if not self.openai_api_key:
            raise ValueError("OpenAI API key is required for embeddings.")

        from openai import OpenAI

        client = OpenAI(api_key=self.openai_api_key)
        response = client.embeddings.create(model=self.embedding_model, input=text)
        return response.data[0].embedding

    def _update_diag(self, payload: dict[str, Any]) -> None:
        _GLOBAL_LAST_QUERY_DIAGNOSTICS.clear()
        _GLOBAL_LAST_QUERY_DIAGNOSTICS.update(payload)

    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        namespace: Optional[str] = None,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Search relevant documents with query-length cap and diagnostics."""
        raw_query = query or ""
        capped_query = raw_query[: self.query_max_chars]
        query_truncated = len(capped_query) < len(raw_query)

        diag = {
            "tool": "pinecone_search",
            "query_length": len(raw_query),
            "query_length_capped": len(capped_query),
            "truncated": query_truncated,
            "top_k": int(top_k or self.top_k),
            "namespace": namespace or self.namespace,
            "status": "pending",
            "failure_point": "collection.query",
        }
        self._update_diag(diag)

        k = top_k or self.top_k
        ns = namespace or self.namespace

        if self._initialized and self._index:
            try:
                text = self._search_pinecone(capped_query, k, ns, filter_dict)
                diag["status"] = "success"
                self._update_diag(diag)
                return text
            except Exception as exc:
                diag["status"] = "failure"
                diag["error_type"] = type(exc).__name__
                diag["error_message"] = str(exc)
                self._update_diag(diag)
                logger.error(
                    "collection.query failed (query_length=%s capped=%s): %s",
                    diag["query_length"],
                    diag["query_length_capped"],
                    exc,
                )
                return self._search_fallback(capped_query, k)

        diag["status"] = "fallback"
        self._update_diag(diag)
        return self._search_fallback(capped_query, k)

    def _search_pinecone(
        self,
        query: str,
        top_k: int,
        namespace: str,
        filter_dict: Optional[Dict[str, Any]],
    ) -> str:
        embedding = self._get_embedding(query)
        params: dict[str, Any] = {
            "vector": embedding,
            "top_k": top_k,
            "namespace": namespace,
            "include_metadata": True,
        }
        if filter_dict:
            params["filter"] = filter_dict

        results = self._index.query(**params)
        if not results.matches:
            return "(No relevant documents found.)"

        lines: list[str] = []
        for idx, match in enumerate(results.matches, 1):
            metadata = match.metadata or {}
            title = metadata.get("title", "Untitled")
            text = metadata.get("text", metadata.get("content", ""))
            source = metadata.get("source", "unknown")
            score = float(match.score)
            preview = text if len(text) <= 500 else f"{text[:500]}..."
            lines.append(
                f"### [{idx}] {title} (score={score:.3f})\n"
                f"- source: {source}\n"
                f"- content: {preview}\n"
            )

        return "\n".join(lines)

    def _search_fallback(self, query: str, top_k: int) -> str:
        return (
            "(Pinecone unavailable; fallback mode)\n"
            f"- query: {query}\n"
            f"- top_k: {top_k}\n"
            "Use model priors and local artifacts for now."
        )

    def upsert_documents(
        self,
        documents: List[Dict[str, Any]],
        namespace: Optional[str] = None,
        batch_size: int = 100,
    ) -> int:
        if not self._initialized or not self._index:
            raise RuntimeError("Pinecone is not initialized. Call create_index() first.")

        ns = namespace or self.namespace
        total = 0

        for start in range(0, len(documents), batch_size):
            batch = documents[start : start + batch_size]
            vectors: list[dict[str, Any]] = []
            for doc in batch:
                text = str(doc.get("text", ""))
                metadata = dict(doc.get("metadata", {}))
                metadata["text"] = text[:1000]
                doc_id = hashlib.md5(text.encode("utf-8")).hexdigest()
                embedding = self._get_embedding(text)
                vectors.append({"id": doc_id, "values": embedding, "metadata": metadata})

            self._index.upsert(vectors=vectors, namespace=ns)
            total += len(vectors)

        return total

    def delete_namespace(self, namespace: Optional[str] = None) -> None:
        if not self._initialized or not self._index:
            raise RuntimeError("Pinecone is not initialized.")

        self._index.delete(delete_all=True, namespace=namespace or self.namespace)

    @property
    def is_available(self) -> bool:
        return self._initialized
