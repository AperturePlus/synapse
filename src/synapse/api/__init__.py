"""HTTP API package for Synapse (optional).

Install with `uv sync --group api` to use the FastAPI server.
"""

from synapse.api.app import create_app

__all__ = ["create_app"]

