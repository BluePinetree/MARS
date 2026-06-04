"""
api 패키지.
FastAPI 기반 REST API 서버를 제공합니다.
"""

from api.server import create_app

__all__ = ["create_app"]
