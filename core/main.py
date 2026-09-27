"""
IBVAP — Core Platform (FastAPI Application)
=============================================
Central platform that aggregates events from edge nodes,
runs cross-camera services, and serves the web dashboard.
"""

import sys
import time
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import CoreConfig
from core.database import init_db, async_session
from core.models import Camera, User
from core.auth.jwt_auth import get_current_user, hash_password
from core.dashboard_api.websocket import alert_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-25s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("IBVAP.Core")

_start_time = time.time()


async def seed_demo_data():
    """Seed initial demo data for the prototype."""
    async with async_session() as db:
        from sqlalchemy import select

        # Check if already seeded
        result = await db.execute(select(Camera).limit(1))
        if result.scalar_one_or_none():
            return

        logger.info("Seeding demo data...")

        # Demo cameras
        cameras = [
            Camera(name="BOP Alpha - Gate", camera_uid="cam_01", bop_id="bop_alpha",
                   lat=26.8467, lng=80.9462, status="online"),
            Camera(name="BOP Alpha - Perimeter N", camera_uid="cam_02", bop_id="bop_alpha",
                   lat=26.8470, lng=80.9465, status="online"),
            Camera(name="BOP Alpha - Perimeter S", camera_uid="cam_03", bop_id="bop_alpha",
                   lat=26.8464, lng=80.9460, status="online"),
            Camera(name="BOP Bravo - Main", camera_uid="cam_04", bop_id="bop_bravo",
                   lat=26.9100, lng=81.0200, status="offline"),
        ]
        for cam in cameras:
            db.add(cam)

        # Demo users
        users = [
            User(username="admin", name="Admin User", role="admin",
                 hashed_password=hash_password("admin123"), bop_id="hq"),
            User(username="commander", name="Post Commander Singh", role="post_commander",
                 hashed_password=hash_password("commander123"), bop_id="bop_alpha"),
            User(username="officer", name="Field Officer Kumar", role="field_officer",
                 hashed_password=hash_password("officer123"), bop_id="bop_alpha"),
            User(username="analyst", name="HQ Analyst Sharma", role="hq_analyst",
                 hashed_password=hash_password("analyst123"), bop_id="hq"),
        ]
        for user in users:
            db.add(user)

        await db.commit()
        logger.info(f"Seeded {len(cameras)} cameras and {len(users)} users")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info("=" * 60)
    logger.info("IBVAP Core Platform — Starting")
    logger.info("=" * 60)

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Seed demo data
    await seed_demo_data()

    # Create media directories
    CoreConfig.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    (CoreConfig.MEDIA_DIR / "thumbnails").mkdir(exist_ok=True)
    (CoreConfig.MEDIA_DIR / "clips").mkdir(exist_ok=True)

    logger.info(f"Core API ready at http://{CoreConfig.HOST}:{CoreConfig.PORT}")
    logger.info(f"Dashboard API docs at http://localhost:{CoreConfig.PORT}/docs")
    logger.info("=" * 60)

    yield

    logger.info("IBVAP Core Platform — Shutdown")


# Create FastAPI app
app = FastAPI(
    title="IBVAP — Intelligent Border Video Analytics Platform",
    description=(
        "Central platform for the IBVAP border surveillance system. "
        "Aggregates AI-driven detection events from edge nodes, "
        "manages alerts, and provides a tamper-evident audit trail."
    ),
    version="1.0.0-prototype",
    lifespan=lifespan,
)

# CORS for dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=CoreConfig.CORS_ORIGINS + ["*"],  # Permissive for prototype
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static media
app.mount("/media", StaticFiles(directory=str(CoreConfig.MEDIA_DIR)), name="media")

# ──────────────────────────────────────
# Include Routers
# ──────────────────────────────────────

from core.ingestion_api.router import router as ingestion_router
from core.dashboard_api.router import router as dashboard_router
from core.security.router import router as security_router

app.include_router(ingestion_router)
app.include_router(dashboard_router)
app.include_router(security_router)


# ──────────────────────────────────────
# Auth Endpoints
# ──────────────────────────────────────

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from core.database import get_db
from core.models import User as UserModel
from core.schemas import LoginRequest, TokenResponse, UserResponse, UserCreate
from core.auth.jwt_auth import get_current_user, require_role, verify_password, create_token, hash_password as hp


@app.post("/api/v1/auth/login", response_model=TokenResponse, tags=["Auth"])
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login with username and password."""
    result = await db.execute(select(UserModel).where(UserModel.username == req.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.hashed_password):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token({"sub": str(user.id), "role": user.role, "username": user.username})
    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user.id, username=user.username, name=user.name,
            role=user.role, bop_id=user.bop_id, email=user.email,
        ),
    )


@app.get("/api/v1/auth/users", response_model=list[UserResponse], tags=["Auth"])
async def list_users(user = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    """List all users (admin only)."""
    result = await db.execute(select(UserModel).order_by(UserModel.id))
    return result.scalars().all()


# ──────────────────────────────────────
# Watchlist Endpoints
# ──────────────────────────────────────

from core.schemas import WatchlistCreate, WatchlistResponse
from core.models import WatchlistEntry


@app.get("/api/v1/watchlist", response_model=list[WatchlistResponse], tags=["Watchlist"])
async def list_watchlist(user = Depends(require_role("hq_analyst")), db: AsyncSession = Depends(get_db)):
    """List all watchlist entries (hq_analyst or admin only)."""
    result = await db.execute(select(WatchlistEntry).order_by(WatchlistEntry.id.desc()))
    return result.scalars().all()


@app.post("/api/v1/watchlist", response_model=WatchlistResponse, tags=["Watchlist"])
async def add_watchlist_entry(entry: WatchlistCreate, user = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    """Add a watchlist entry (admin only)."""
    import hmac
    import hashlib
    ref_hash = hmac.new(
        CoreConfig.WATCHLIST_HASH_SECRET.encode(),
        entry.reference_data.encode(),
        hashlib.sha256,
    ).hexdigest()

    db_entry = WatchlistEntry(
        entry_type=entry.entry_type,
        reference_hash=ref_hash,
        label=entry.label,
        category=entry.category,
        source_agency=entry.source_agency,
    )
    db.add(db_entry)
    await db.commit()
    await db.refresh(db_entry)
    return db_entry


# ──────────────────────────────────────
# WebSocket Endpoint
# ──────────────────────────────────────

@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    """Live alert stream via WebSocket."""
    await alert_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, handle incoming messages
            data = await websocket.receive_text()
            # Client can send filter preferences
            logger.debug(f"WS received: {data}")
    except WebSocketDisconnect:
        alert_manager.disconnect(websocket)


# ──────────────────────────────────────
# Health / Root
# ──────────────────────────────────────

@app.get("/", tags=["System"])
async def root():
    return {
        "name": "IBVAP — Intelligent Border Video Analytics Platform",
        "version": "1.0.0-prototype",
        "status": "running",
        "uptime_seconds": round(time.time() - _start_time, 1),
        "docs": "/docs",
    }


@app.get("/health", tags=["System"])
async def health():
    return {"status": "healthy", "uptime": round(time.time() - _start_time, 1)}


# ──────────────────────────────────────
# Entry Point
# ──────────────────────────────────────

def main():
    import uvicorn
    uvicorn.run(
        "core.main:app",
        host=CoreConfig.HOST,
        port=CoreConfig.PORT,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
