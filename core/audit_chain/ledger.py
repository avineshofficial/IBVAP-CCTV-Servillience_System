"""
IBVAP — Tamper-Evident Audit Chain Ledger
===========================================
SHA-256 hash-chain for tamper-evident audit trail.
Every event/alert is chained — altering any past record breaks the chain.
"""

import json
import hashlib
import time
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

logger = logging.getLogger(__name__)

# Genesis hash for the first record in the chain
GENESIS_HASH = "0" * 64


class AuditLedger:
    """
    Tamper-evident audit ledger using SHA-256 hash chains.

    Each record's hash includes:
    - The record's canonical JSON serialization
    - The previous record's hash

    This creates an unbroken chain — modifying any record
    invalidates all subsequent hashes.
    """

    def __init__(self):
        self._last_hash = GENESIS_HASH
        self._record_count = 0

    @staticmethod
    def canonical_json(data: dict) -> str:
        """
        Create a deterministic JSON serialization.
        Keys are sorted, no whitespace, consistent encoding.
        """
        return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def compute_hash(data_json: str, prev_hash: str) -> str:
        """
        Compute SHA-256 hash of (data + previous_hash).
        This is the core hash-chain primitive.
        """
        payload = f"{data_json}|{prev_hash}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def append_record(self, db: AsyncSession, alert_or_event) -> Optional[str]:
        """
        Append a record to the hash chain.
        Returns the computed hash.
        """
        try:
            from core.models import AuditRecord

            # Build canonical data snapshot
            data = {
                "type": type(alert_or_event).__name__,
                "id": alert_or_event.id if alert_or_event.id else "pending",
                "timestamp": time.time(),
            }

            # Add type-specific fields
            if hasattr(alert_or_event, "severity"):
                data["severity"] = alert_or_event.severity
                data["alert_type"] = alert_or_event.alert_type
                data["message"] = alert_or_event.message
                data["data"] = alert_or_event.data_json

            if hasattr(alert_or_event, "event_type"):
                data["event_type"] = alert_or_event.event_type
                data["confidence"] = alert_or_event.confidence
                data["metadata"] = alert_or_event.metadata_json

            # Serialize to canonical JSON
            data_json = self.canonical_json(data)

            # Get previous hash
            result = await db.execute(
                select(AuditRecord)
                .order_by(AuditRecord.id.desc())
                .limit(1)
            )
            last_record = result.scalar_one_or_none()
            prev_hash = last_record.record_hash if last_record else GENESIS_HASH

            # Compute this record's hash
            record_hash = self.compute_hash(data_json, prev_hash)

            # Store the audit record
            audit = AuditRecord(
                event_id=alert_or_event.id if hasattr(alert_or_event, "event_type") else None,
                record_hash=record_hash,
                prev_hash=prev_hash,
                timestamp=time.time(),
                signer="core_01",
                data_snapshot=data_json,
            )
            db.add(audit)

            self._last_hash = record_hash
            self._record_count += 1

            logger.debug(f"Audit record appended: {record_hash[:16]}...")
            return record_hash

        except Exception as e:
            logger.error(f"Audit chain error: {e}")
            return None

    async def verify_chain(self, db: AsyncSession, event_id: int = None) -> dict:
        """
        Verify the integrity of the hash chain.

        If event_id is provided, verifies the chain up to that event.
        Otherwise, verifies the entire chain.
        """
        from core.models import AuditRecord

        try:
            query = select(AuditRecord).order_by(AuditRecord.id.asc())
            result = await db.execute(query)
            records = result.scalars().all()

            if not records:
                return {
                    "verified": True,
                    "chain_length": 0,
                    "message": "Empty chain — nothing to verify",
                }

            # Walk the chain and verify each hash
            prev_hash = GENESIS_HASH
            broken_at = None
            verified_count = 0
            target_record = None

            for record in records:
                # Verify prev_hash linkage
                if record.prev_hash != prev_hash:
                    broken_at = record.id
                    break

                # Recompute hash from stored data
                if record.data_snapshot:
                    computed = self.compute_hash(record.data_snapshot, record.prev_hash)
                    if computed != record.record_hash:
                        broken_at = record.id
                        break

                prev_hash = record.record_hash
                verified_count += 1

                if event_id and record.event_id == event_id:
                    target_record = record

            if broken_at:
                return {
                    "verified": False,
                    "chain_length": len(records),
                    "broken_at_record_id": broken_at,
                    "verified_count": verified_count,
                    "message": f"Chain broken at record {broken_at} — data has been tampered with!",
                    "computed_hash": computed if 'computed' in dir() else "N/A",
                    "stored_hash": records[verified_count].record_hash if verified_count < len(records) else "N/A",
                }

            result = {
                "verified": True,
                "chain_length": len(records),
                "verified_count": verified_count,
                "message": f"All {verified_count} records verified — chain integrity confirmed",
                "last_hash": records[-1].record_hash if records else GENESIS_HASH,
            }

            if target_record:
                result["event_record"] = {
                    "record_id": target_record.id,
                    "record_hash": target_record.record_hash,
                    "prev_hash": target_record.prev_hash,
                    "timestamp": target_record.timestamp,
                }

            return result

        except Exception as e:
            logger.error(f"Chain verification error: {e}")
            return {
                "verified": False,
                "chain_length": 0,
                "message": f"Verification error: {str(e)}",
            }

    async def get_chain_stats(self, db: AsyncSession) -> dict:
        """Get audit chain statistics."""
        from core.models import AuditRecord

        result = await db.execute(select(func.count(AuditRecord.id)))
        total = result.scalar() or 0

        last_result = await db.execute(
            select(AuditRecord).order_by(AuditRecord.id.desc()).limit(1)
        )
        last = last_result.scalar_one_or_none()

        return {
            "total_records": total,
            "last_hash": last.record_hash if last else GENESIS_HASH,
            "last_timestamp": last.timestamp if last else None,
            "genesis_hash": GENESIS_HASH,
        }


# Global singleton
audit_ledger = AuditLedger()
