"""
Tool factory package.
"""

from __future__ import annotations

from tools.docker_tool import DockerTool
from tools.pinecone_tool import PineconeTool, SearchResult
from tools.wandb_tool import WandBTool

__all__ = [
    "PineconeTool",
    "SearchResult",
    "DockerTool",
    "WandBTool",
    "create_tools",
]


def create_tools(settings=None) -> dict:
    """Create integrated tool instances from settings."""
    import os

    pinecone_tool = PineconeTool(
        api_key=getattr(settings, "pinecone_api_key", None) or os.getenv("PINECONE_API_KEY"),
        index_name=getattr(settings, "pinecone_index_name", "research-papers"),
        namespace=getattr(settings, "pinecone_namespace", "default"),
        top_k=getattr(settings, "pinecone_top_k", 5),
        embedding_model=getattr(settings, "embedding_model", "text-embedding-3-small"),
        embedding_dimension=getattr(settings, "embedding_dimension", 1536),
        openai_api_key=getattr(settings, "openai_api_key", None) or os.getenv("OPENAI_API_KEY"),
        query_max_chars=getattr(settings, "pinecone_query_max_chars", 1500),
    )

    docker_tool = DockerTool(
        base_image=getattr(settings, "docker_base_image", "python:3.11-slim"),
        memory_limit=getattr(settings, "docker_memory_limit", "4g"),
        cpu_limit=getattr(settings, "docker_cpu_limit", 2.0),
        timeout_seconds=getattr(settings, "docker_timeout", 600),
        network_mode=getattr(settings, "docker_network_mode", "none"),
    )

    wandb_tool = WandBTool(
        api_key=getattr(settings, "wandb_api_key", None) or os.getenv("WANDB_API_KEY"),
        project=getattr(settings, "wandb_project", "autonomous-research"),
    )

    return {
        "pinecone": pinecone_tool,
        "docker": docker_tool,
        "wandb": wandb_tool,
    }
