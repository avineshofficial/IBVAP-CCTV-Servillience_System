"""
IBVAP Core Configuration
=========================
"""

import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

MEDIA_DIR = PROJECT_ROOT / "core" / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

# Validate required security keys at startup
_edge_api_key = os.getenv("EDGE_API_KEY")
if not _edge_api_key or _edge_api_key.strip() in ("", "changeme-generate-a-secure-edge-key"):
    raise RuntimeError(
        "CRITICAL STARTUP ERROR: 'EDGE_API_KEY' is not configured in .env! "
        "A secure random shared secret must be configured for edge-to-core mutual authentication."
    )


class CoreConfig:
    """Configuration for the core platform."""

    HOST: str = os.getenv("CORE_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("CORE_PORT", "8000"))
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"sqlite+aiosqlite:///{PROJECT_ROOT / 'ibvap.db'}"
    )
    SECRET_KEY: str = os.getenv("SECRET_KEY", "ibvap-prototype-secret-key-change-in-production")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRY_MINUTES: int = int(os.getenv("JWT_EXPIRY_MINUTES", "1440"))
    MEDIA_DIR: Path = MEDIA_DIR
    CORS_ORIGINS: list = ["http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:3000"]
    WATCHLIST_HASH_SECRET: str = os.getenv(
        "WATCHLIST_HASH_SECRET",
        "ibvap-watchlist-hmac-secret-change-in-production"
    )
    EDGE_API_KEY: str = _edge_api_key

