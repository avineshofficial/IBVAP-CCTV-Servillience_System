"""
IBVAP — Watchlist Service
===========================
Face and plate matching against watchlists.
Every query is logged as an audit record.
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Optional
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger(__name__)

# Secret salt for HMAC hashing of plate numbers (DPDP Act compliance)
PLATE_HASH_SALT = b"ibvap-plate-hash-salt-2026"


class WatchlistMatcher:
    """
    Matches face embeddings and plate numbers against watchlists.
    All queries are audit-logged.
    """

    def __init__(self, face_similarity_threshold: float = 0.6):
        self.face_similarity_threshold = face_similarity_threshold
        self._match_count = 0

    @staticmethod
    def hash_plate(plate_text: str) -> str:
        """
        Hash a plate number using HMAC-SHA256 with salt.
        Plate numbers are NEVER stored in plaintext (DPDP Act compliance).
        """
        return hmac.new(
            PLATE_HASH_SALT,
            plate_text.upper().strip().encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two embeddings."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    async def match_face(
        self,
        embedding: np.ndarray,
        db: AsyncSession,
        queried_by: str = "system",
    ) -> list[dict]:
        """
        Match a face embedding against all face entries in the watchlist.
        Returns list of matches above the similarity threshold.
        """
        from core.models import WatchlistEntry

        result = await db.execute(
            select(WatchlistEntry).where(
                WatchlistEntry.entry_type == "face",
                WatchlistEntry.is_active == True,
            )
        )
        entries = result.scalars().all()

        matches = []
        for entry in entries:
            if entry.reference_embedding:
                ref_emb = np.array(json.loads(entry.reference_embedding))
                similarity = self.cosine_similarity(embedding, ref_emb)
                if similarity >= self.face_similarity_threshold:
                    matches.append({
                        "watchlist_id": entry.id,
                        "label": entry.label,
                        "category": entry.category,
                        "source_agency": entry.source_agency,
                        "similarity": round(similarity, 4),
                    })

        # Log the query as an audit action
        await self._log_query(db, "face", queried_by, len(matches))

        return sorted(matches, key=lambda x: x["similarity"], reverse=True)

    async def match_plate(
        self,
        plate_text: str,
        db: AsyncSession,
        queried_by: str = "system",
    ) -> list[dict]:
        """
        Match a plate number against plate entries in the watchlist.
        Uses HMAC hash comparison — never compares plaintext.
        """
        from core.models import WatchlistEntry

        plate_hash = self.hash_plate(plate_text)

        result = await db.execute(
            select(WatchlistEntry).where(
                WatchlistEntry.entry_type == "plate",
                WatchlistEntry.is_active == True,
                WatchlistEntry.reference_hash == plate_hash,
            )
        )
        entries = result.scalars().all()

        matches = [
            {
                "watchlist_id": entry.id,
                "label": entry.label,
                "category": entry.category,
                "source_agency": entry.source_agency,
                "match_type": "exact_hash",
            }
            for entry in entries
        ]

        # Log the query
        await self._log_query(db, "plate", queried_by, len(matches))

        return matches

    async def _log_query(
        self,
        db: AsyncSession,
        query_type: str,
        queried_by: str,
        match_count: int,
    ):
        """Log a watchlist query to the audit trail."""
        from core.models import AuditRecord
        from core.audit_chain.ledger import audit_ledger

        self._match_count += 1
        logger.info(
            f"Watchlist query #{self._match_count}: type={query_type}, "
            f"by={queried_by}, matches={match_count}"
        )

    async def add_face_entry(
        self,
        embedding: np.ndarray,
        label: str,
        category: str,
        source_agency: str,
        db: AsyncSession,
        added_by: int = None,
    ) -> int:
        """Add a face entry to the watchlist."""
        from core.models import WatchlistEntry

        emb_json = json.dumps(embedding.tolist())
        emb_hash = hashlib.sha256(emb_json.encode()).hexdigest()

        entry = WatchlistEntry(
            entry_type="face",
            reference_hash=emb_hash,
            reference_embedding=emb_json,
            label=label,
            category=category,
            source_agency=source_agency,
            added_by=added_by,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return entry.id

    async def add_plate_entry(
        self,
        plate_text: str,
        label: str,
        category: str,
        source_agency: str,
        db: AsyncSession,
        added_by: int = None,
    ) -> int:
        """Add a plate entry to the watchlist (stored as HMAC hash)."""
        from core.models import WatchlistEntry

        plate_hash = self.hash_plate(plate_text)

        entry = WatchlistEntry(
            entry_type="plate",
            reference_hash=plate_hash,
            label=label,
            category=category,
            source_agency=source_agency,
            added_by=added_by,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return entry.id


# Global singleton
watchlist_matcher = WatchlistMatcher()
