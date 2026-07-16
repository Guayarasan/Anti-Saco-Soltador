from __future__ import annotations

import json
import logging

from endstone_antidupe.domain.confidence import ConfidenceLevel
from endstone_antidupe.domain.models import Detection, Position
from endstone_antidupe.persistence.database import Database
from endstone_antidupe.persistence.repository import DetectionRepository


class SQLiteDetectionRepository(DetectionRepository):
    """SQLite implementation. Writes are batched by the caller (see
    services/stats_service.py) so this class stays a thin, synchronous
    mapper between :class:`Detection` and rows.
    """

    def __init__(self, database: Database, logger: logging.Logger | None = None):
        self._db = database
        self._logger = logger or logging.getLogger("antidupe.repository")

    def save(self, detection: Detection) -> None:
        try:
            self._db.execute(
                """
                INSERT OR REPLACE INTO detections
                    (id, detector_id, player_name, player_uuid, world, dimension,
                     x, y, z, confidence_score, confidence_level, reason, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    detection.detection_id,
                    detection.detector_id,
                    detection.player_name,
                    detection.player_uuid,
                    detection.position.world,
                    detection.position.dimension,
                    detection.position.x,
                    detection.position.y,
                    detection.position.z,
                    detection.confidence_score,
                    int(detection.confidence_level),
                    detection.reason,
                    json.dumps(detection.metadata, default=str),
                    detection.timestamp,
                ),
            )
            self._db.commit()
        except Exception as exc:  # noqa: BLE001 - persistence must never crash the server
            self._logger.warning("Failed to persist detection: %s", exc)

    def history_for(self, player_name: str, limit: int = 50, offset: int = 0) -> list[Detection]:
        rows = self._db.execute(
            """
            SELECT * FROM detections
            WHERE player_name = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (player_name, limit, offset),
        ).fetchall()
        return [self._row_to_detection(r) for r in rows]

    def recent(self, limit: int = 50) -> list[Detection]:
        rows = self._db.execute(
            "SELECT * FROM detections ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_detection(r) for r in rows]

    def count_by_detector(self) -> dict:
        rows = self._db.execute(
            "SELECT detector_id, COUNT(*) as cnt FROM detections GROUP BY detector_id"
        ).fetchall()
        return {r["detector_id"]: r["cnt"] for r in rows}

    def count_by_player(self, limit: int = 15) -> list[tuple]:
        rows = self._db.execute(
            """
            SELECT player_name, COUNT(*) as cnt FROM detections
            GROUP BY player_name ORDER BY cnt DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [(r["player_name"], r["cnt"]) for r in rows]

    def total_count(self) -> int:
        row = self._db.execute("SELECT COUNT(*) as cnt FROM detections").fetchone()
        return int(row["cnt"]) if row else 0

    def clear(self) -> None:
        self._db.execute("DELETE FROM detections")
        self._db.commit()

    def prune(self, keep_latest: int) -> None:
        self._db.execute(
            """
            DELETE FROM detections WHERE id NOT IN (
                SELECT id FROM detections ORDER BY created_at DESC LIMIT ?
            )
            """,
            (keep_latest,),
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    @staticmethod
    def _row_to_detection(row) -> Detection:
        metadata = {}
        try:
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        except (json.JSONDecodeError, TypeError):
            pass
        position = Position(
            x=row["x"], y=row["y"], z=row["z"],
            dimension=row["dimension"], world=row["world"],
        )
        return Detection(
            detector_id=row["detector_id"],
            player_name=row["player_name"],
            player_uuid=row["player_uuid"],
            position=position,
            confidence_score=row["confidence_score"],
            confidence_level=ConfidenceLevel(row["confidence_level"]),
            reason=row["reason"],
            metadata=metadata,
            timestamp=row["created_at"],
            detection_id=row["id"],
        )
