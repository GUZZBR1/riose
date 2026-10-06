"""SQLite persistence for a local property deployment."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from ...domain.behavior import BehaviorObservation
from ...domain.identity import append_event

if TYPE_CHECKING:
    from ...domain.identity import LocalChainEvidence


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS animals (
  animal_id TEXT PRIMARY KEY, hardware_id TEXT NOT NULL UNIQUE,
  cryptographic_id TEXT NOT NULL UNIQUE, name TEXT, sex TEXT, breed TEXT,
  birth_date TEXT, weight_kg REAL, property_name TEXT, lot TEXT, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS anchors (
  anchor_id TEXT PRIMARY KEY, x REAL NOT NULL, y REAL NOT NULL,
  height_m REAL NOT NULL, kind TEXT NOT NULL, enabled INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS animal_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT, animal_id TEXT NOT NULL,
  event_type TEXT NOT NULL, timestamp REAL NOT NULL, payload TEXT NOT NULL,
  previous_hash TEXT NOT NULL, hash TEXT NOT NULL, signature TEXT,
  schema_version TEXT,
  FOREIGN KEY(animal_id) REFERENCES animals(animal_id)
);
CREATE TABLE IF NOT EXISTS telemetry (
  id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL,
  tag_id TEXT NOT NULL, anchor_id TEXT NOT NULL, rssi_dbm REAL, snr_db REAL,
  packet_received INTEGER NOT NULL, imu_accel_norm_g REAL,
  behavior_state TEXT, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL,
  tag_id TEXT NOT NULL, x REAL, y REAL, method TEXT NOT NULL,
  quality REAL, status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_telemetry_sample_reruns
  ON telemetry(tag_id,anchor_id,timestamp,id);
CREATE INDEX IF NOT EXISTS idx_position_sample_reruns
  ON positions(tag_id,timestamp,id);
CREATE TABLE IF NOT EXISTS debug_truth (
  timestamp REAL NOT NULL, tag_id TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL,
  PRIMARY KEY(timestamp, tag_id)
);
CREATE TABLE IF NOT EXISTS run_metrics (
  key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS behavior_observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  animal_id TEXT NOT NULL,
  timestamp_s REAL NOT NULL,
  end_timestamp_s REAL,
  behavior TEXT NOT NULL,
  confidence REAL,
  model_version TEXT,
  source TEXT NOT NULL,
  observation_kind TEXT NOT NULL,
  evidence_status TEXT NOT NULL,
  sensor_position TEXT,
  idempotency_key TEXT NOT NULL,
  persisted_at REAL NOT NULL,
  UNIQUE(animal_id,idempotency_key),
  FOREIGN KEY(animal_id) REFERENCES animals(animal_id),
  CHECK(timestamp_s >= 0),
  CHECK(end_timestamp_s IS NULL OR end_timestamp_s >= timestamp_s),
  CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  CHECK(observation_kind IN ('PREDICTION','GROUND_TRUTH','MANUAL_ANNOTATION')),
  CHECK(evidence_status IN ('VALIDATED','SIMULATED','ASSUMED','EXPERIMENTAL','FUTURE'))
);
CREATE INDEX IF NOT EXISTS idx_behavior_history
  ON behavior_observations(animal_id,timestamp_s,id);
CREATE TABLE IF NOT EXISTS behavior_predictions (
  prediction_id TEXT PRIMARY KEY, animal_id TEXT NOT NULL, tag_id TEXT NOT NULL,
  window_start_s REAL NOT NULL, window_end_s REAL NOT NULL, created_at_s REAL NOT NULL,
  behavior TEXT NOT NULL, confidence REAL, model_score REAL, model_version TEXT NOT NULL,
  model_sha256 TEXT NOT NULL, feature_version TEXT NOT NULL,
  evidence_status TEXT NOT NULL, source_ref TEXT NOT NULL, input_sha256 TEXT NOT NULL,
  time_basis TEXT NOT NULL,
  CHECK(window_start_s >= 0), CHECK(window_end_s > window_start_s),
  CHECK(created_at_s >= 0), CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  CHECK(model_score IS NULL OR (model_score >= 0 AND model_score <= 1)),
  CHECK(evidence_status IN ('VALIDATED','SIMULATED','ASSUMED','EXPERIMENTAL','FUTURE')),
  CHECK(time_basis IN ('UTC_UNIX_SECONDS','SOURCE_RELATIVE_SECONDS'))
);
CREATE INDEX IF NOT EXISTS idx_behavior_predictions_animal_window
  ON behavior_predictions(animal_id,window_start_s,prediction_id);
"""


class Store:
    def __init__(self, path: str | Path = "data/cattle_rf.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(SCHEMA)
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(animal_events)")}
        if "schema_version" not in columns:
            # NULL identifies historical rows written before the v1 marker existed.
            self.connection.execute("ALTER TABLE animal_events ADD COLUMN schema_version TEXT")
        self.connection.commit()

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def save_anchors(self, anchors: Iterable[Any]) -> None:
        with self._lock:
            self.connection.executemany(
                "INSERT INTO anchors(anchor_id,x,y,height_m,kind,enabled) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(anchor_id) DO UPDATE SET x=excluded.x,y=excluded.y,height_m=excluded.height_m,kind=excluded.kind,enabled=excluded.enabled",
                [(a.anchor_id, a.x, a.y, a.height_m, a.kind, int(a.enabled)) for a in anchors],
            )
            self.connection.commit()

    def create_animal(self, animal_id: str, hardware_id: str, cryptographic_id: str,
                      **profile: Any) -> dict[str, Any]:
        import time
        with self._lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                self.connection.execute(
                    "INSERT INTO animals(animal_id,hardware_id,cryptographic_id,name,sex,breed,birth_date,weight_kg,property_name,lot,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (animal_id, hardware_id, cryptographic_id, profile.get("name"), profile.get("sex"),
                     profile.get("breed"), profile.get("birth_date"), profile.get("weight_kg"),
                     profile.get("property_name"), profile.get("lot"), time.time()),
                )
                append_event(self.connection, animal_id, "ANIMAL_CREATED", {"hardware_id": hardware_id}, commit=False)
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            return self.get_animal(animal_id) or {}

    def append_animal_event(self, animal_id: str, event_type: str,
                            payload: dict[str, Any], timestamp: float | None = None):
        with self._lock:
            return append_event(self.connection, animal_id, event_type, payload, timestamp)

    def verify_animal_chain(self, animal_id: str) -> bool:
        from ...domain.identity import verify_event_chain
        with self._lock:
            return verify_event_chain(self.connection, animal_id)

    def event_chain_evidence(self, animal_id: str) -> LocalChainEvidence | None:
        """Return a read-only summary without exposing the animal id or payload."""
        from ...domain.identity import event_chain_evidence

        with self._lock:
            return event_chain_evidence(self.connection, animal_id)

    def get_animal(self, animal_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.connection.execute("SELECT * FROM animals WHERE animal_id=?", (animal_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["events"] = [dict(r) for r in self.connection.execute(
                "SELECT event_id,event_type,timestamp,payload,previous_hash,hash,signature FROM animal_events WHERE animal_id=? ORDER BY event_id DESC LIMIT 100",
                (animal_id,),
            )]
            for event in result["events"]:
                try:
                    event["payload"] = json.loads(event["payload"])
                except (TypeError, json.JSONDecodeError):
                    event["payload"] = None
            return result

    def animal_id_for_hardware_id(self, hardware_id: str) -> str | None:
        """Find the registered animal assigned to a telemetry tag identifier."""
        with self._lock:
            row = self.connection.execute(
                "SELECT animal_id FROM animals WHERE hardware_id=?", (hardware_id,)
            ).fetchone()
            return str(row["animal_id"]) if row is not None else None

    def list_animals(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self.connection.execute("SELECT * FROM animals ORDER BY animal_id")]

    def animal_trajectory(self, animal_id: str, limit: int = 1000) -> list[dict[str, Any]] | None:
        """Return receiver-derived positions for the tag assigned to an animal."""
        with self._lock:
            animal = self.connection.execute(
                "SELECT hardware_id FROM animals WHERE animal_id=?", (animal_id,)
            ).fetchone()
            if animal is None:
                return None
            rows = self.connection.execute(
                "SELECT timestamp,tag_id,x,y,method,quality,status FROM ("
                "SELECT timestamp,tag_id,x,y,method,quality,status,id,"
                "ROW_NUMBER() OVER(PARTITION BY tag_id,timestamp ORDER BY id DESC) AS sample_rank "
                "FROM positions WHERE tag_id=?"
                ") WHERE sample_rank=1 ORDER BY timestamp DESC,id DESC LIMIT ?",
                (animal["hardware_id"], limit),
            ).fetchall()
            return [dict(row) for row in reversed(rows)]

    def save_episode(self, observations: Iterable[Any], estimates: Iterable[Any],
                     truth: Iterable[Any], persist_truth: bool = True) -> None:
        with self._lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                self.connection.executemany(
                    "INSERT INTO telemetry(timestamp,tag_id,anchor_id,rssi_dbm,snr_db,packet_received,imu_accel_norm_g,behavior_state,status) VALUES(?,?,?,?,?,?,?,?,?)",
                    ((o.timestamp_s, o.tag_id, o.anchor_id, o.rssi_dbm, o.snr_db,
                      int(o.packet_received), o.imu_accel_norm_g, o.behavior_state, o.status.value)
                     for o in observations),
                )
                self.connection.executemany(
                    "INSERT INTO positions(timestamp,tag_id,x,y,method,quality,status) VALUES(?,?,?,?,?,?,?)",
                    ((e.timestamp_s, e.tag_id, e.x, e.y, e.method, e.quality, e.status.value)
                     for e in estimates),
                )
                if persist_truth:
                    self.connection.executemany(
                        "INSERT OR REPLACE INTO debug_truth(timestamp,tag_id,x,y) VALUES(?,?,?,?)",
                        ((t.timestamp_s, t.tag_id, t.x, t.y) for t in truth),
                    )
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise

    def telemetry(self, limit: int = 1000, tag_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if tag_id is not None:
                rows = self.connection.execute(
                    "SELECT id,timestamp,tag_id,anchor_id,rssi_dbm,snr_db,packet_received,imu_accel_norm_g,behavior_state,status FROM (SELECT *,ROW_NUMBER() OVER("
                    "PARTITION BY tag_id,anchor_id,timestamp ORDER BY id DESC) AS sample_rank "
                    "FROM telemetry WHERE tag_id=?) WHERE sample_rank=1 ORDER BY id DESC LIMIT ?",
                    (tag_id, limit))
            else:
                rows = self.connection.execute(
                    "SELECT id,timestamp,tag_id,anchor_id,rssi_dbm,snr_db,packet_received,imu_accel_norm_g,behavior_state,status FROM (SELECT *,ROW_NUMBER() OVER("
                    "PARTITION BY tag_id,anchor_id,timestamp ORDER BY id DESC) AS sample_rank "
                    "FROM telemetry) WHERE sample_rank=1 ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in rows]

    def positions(self, limit: int = 1000, debug: bool = False,
                  at_s: float | None = None) -> list[dict[str, Any]]:
        time_filter = "WHERE timestamp <= ?" if at_s is not None else ""
        args: tuple[Any, ...] = (at_s,) if at_s is not None else ()
        projection = "p.timestamp,p.tag_id,p.x,p.y,p.method,p.quality,p.status"
        join = ""
        truth_cte = ""
        if debug:
            projection += ",truth.x AS ground_truth_x,truth.y AS ground_truth_y"
            truth_cte = """, truth_ranked AS (
                SELECT p.id AS position_id, d.x, d.y,
                       ROW_NUMBER() OVER(PARTITION BY p.id
                         ORDER BY ABS(d.timestamp-p.timestamp), d.timestamp) AS truth_rank
                FROM ranked p JOIN debug_truth d
                  ON d.tag_id=p.tag_id AND ABS(d.timestamp-p.timestamp)<=1.0
            )"""
            join = "LEFT JOIN truth_ranked truth ON truth.position_id=p.id AND truth.truth_rank=1"
        query = f"""WITH ranked AS (
            SELECT *, ROW_NUMBER() OVER(PARTITION BY tag_id ORDER BY timestamp DESC,id DESC) AS rn
            FROM positions {time_filter}
          ){truth_cte} SELECT {projection} FROM ranked p {join}
          WHERE p.rn=1 ORDER BY p.tag_id LIMIT ?"""
        with self._lock:
            return [dict(r) for r in self.connection.execute(query, (*args, limit))]

    def positions_history(self, tag_id: str, limit: int = 1000,
                          debug: bool = False) -> list[dict[str, Any]]:
        """Return one estimate per tag/timestep, preferring the latest rerun."""
        ranked = """WITH ranked AS (
            SELECT p.id,p.timestamp,p.tag_id,p.x,p.y,p.method,p.quality,p.status,
                   ROW_NUMBER() OVER(PARTITION BY p.tag_id,p.timestamp ORDER BY p.id DESC) AS sample_rank
            FROM positions p WHERE p.tag_id=?
          ), latest AS (
            SELECT id,timestamp,tag_id,x,y,method,quality,status FROM ranked
            WHERE sample_rank=1 ORDER BY timestamp DESC,id DESC LIMIT ?
          )"""
        query = ranked + " SELECT timestamp,tag_id,x,y,method,quality,status FROM latest ORDER BY timestamp,id"
        args: tuple[Any, ...] = (tag_id, limit)
        if debug:
            query = ranked + """, candidates AS (
                SELECT p.id,p.timestamp,p.tag_id,p.x,p.y,p.method,p.quality,p.status,
                       d.x AS ground_truth_x,d.y AS ground_truth_y,
                       ROW_NUMBER() OVER(PARTITION BY p.id ORDER BY ABS(d.timestamp-p.timestamp),d.timestamp) AS truth_rank
                FROM latest p LEFT JOIN debug_truth d
                  ON d.tag_id=p.tag_id AND ABS(d.timestamp-p.timestamp)<=1.0
              ) SELECT timestamp,tag_id,x,y,method,quality,status,ground_truth_x,ground_truth_y
                FROM candidates WHERE truth_rank=1 ORDER BY timestamp,id"""
        with self._lock:
            return [dict(r) for r in self.connection.execute(query, args)]

    def events(self, limit: int = 1000) -> list[dict[str, Any]]:
        with self._lock:
            events = [dict(r) for r in self.connection.execute(
                "SELECT event_id,animal_id,event_type,timestamp,payload,previous_hash,hash,signature "
                "FROM animal_events ORDER BY event_id DESC LIMIT ?", (limit,))]
            for event in events:
                try:
                    event["payload"] = json.loads(event["payload"])
                except (TypeError, json.JSONDecodeError):
                    event["payload"] = None
            return events

    def set_metrics(self, metrics: dict[str, Any]) -> None:
        with self._lock:
            self.connection.executemany(
                "INSERT OR REPLACE INTO run_metrics(key,value) VALUES(?,?)",
                [(key, json.dumps(value, default=str)) for key, value in metrics.items()],
            )
            self.connection.commit()

    def get_metrics(self) -> dict[str, Any]:
        with self._lock:
            return {row["key"]: json.loads(row["value"]) for row in self.connection.execute("SELECT * FROM run_metrics")}

    def save_behavior_observation(
        self, observation: BehaviorObservation
    ) -> tuple[dict[str, Any], bool]:
        """Persist once per animal/key; conflicting retries preserve the first record."""
        with self._lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                existing = self.connection.execute(
                    "SELECT * FROM behavior_observations WHERE animal_id=? AND idempotency_key=?",
                    (observation.animal_id, observation.idempotency_key),
                ).fetchone()
                expected = _behavior_values(observation)
                if existing is not None:
                    if any(existing[key] != value for key, value in expected.items()):
                        raise ValueError("idempotency_key already exists with different observation data")
                    self.connection.commit()
                    return dict(existing), False
                import time

                columns = ",".join((*expected.keys(), "persisted_at"))
                marks = ",".join("?" for _ in range(len(expected) + 1))
                self.connection.execute(
                    f"INSERT INTO behavior_observations({columns}) VALUES({marks})",
                    (*expected.values(), time.time()),
                )
                row = self.connection.execute(
                    "SELECT * FROM behavior_observations WHERE animal_id=? AND idempotency_key=?",
                    (observation.animal_id, observation.idempotency_key),
                ).fetchone()
                self.connection.commit()
                return dict(row), True
            except Exception:
                self.connection.rollback()
                raise

    def behavior_history(
        self,
        animal_id: str,
        *,
        start_s: float | None = None,
        end_s: float | None = None,
        behavior: str | None = None,
        source: str | None = None,
        model_version: str | None = None,
        evidence_status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]] | None:
        """Return a deterministic, animal-scoped behavior history."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be an integer in [1, 1000]")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        if any(not _valid_behavior_time(value) for value in (start_s, end_s)):
            raise ValueError("time filters must be finite Unix timestamps >= 0")
        if start_s is not None and end_s is not None and end_s < start_s:
            raise ValueError("end_s must be >= start_s")
        clauses = ["animal_id=?"]
        args: list[Any] = [animal_id]
        for column, value, operator in (
            ("timestamp_s", start_s, ">="),
            ("timestamp_s", end_s, "<="),
            ("behavior", behavior, "="),
            ("source", source, "="),
            ("model_version", model_version, "="),
            ("evidence_status", evidence_status, "="),
        ):
            if value is not None:
                clauses.append(f"{column}{operator}?")
                args.append(value)
        args.extend((limit, offset))
        with self._lock:
            if self.connection.execute(
                "SELECT 1 FROM animals WHERE animal_id=?", (animal_id,)
            ).fetchone() is None:
                return None
            rows = self.connection.execute(
                "SELECT id,animal_id,timestamp_s,end_timestamp_s,behavior,confidence,model_version,"
                "source,observation_kind,evidence_status,sensor_position,idempotency_key,persisted_at "
                f"FROM behavior_observations WHERE {' AND '.join(clauses)} "
                "ORDER BY timestamp_s,id LIMIT ? OFFSET ?",
                args,
            ).fetchall()
            return [dict(row) for row in rows]

    def save_behavior_prediction(self, prediction: Any) -> bool:
        """Persist an intelligence prediction without inventing an animal profile.

        The prediction contract owns validation. External research subjects need
        not be inserted into the registered-device ``animals`` table.
        """
        from ...domain.intelligence import BehaviorPrediction, PredictionTimeBasis

        if not isinstance(prediction, BehaviorPrediction):
            raise TypeError("prediction must be a BehaviorPrediction")
        values = {
            "prediction_id": prediction.prediction_id,
            "animal_id": prediction.animal_id,
            "tag_id": prediction.tag_id,
            "window_start_s": float(prediction.window_start_s),
            "window_end_s": float(prediction.window_end_s),
            "created_at_s": float(prediction.created_at_s),
            "behavior": prediction.behavior,
            "confidence": None if prediction.confidence is None else float(prediction.confidence),
            "model_score": None if prediction.model_score is None else float(prediction.model_score),
            "model_version": prediction.model_version,
            "model_sha256": prediction.model_sha256,
            "feature_version": prediction.feature_version,
            "evidence_status": prediction.evidence_status.value,
            "source_ref": prediction.source_ref,
            "input_sha256": prediction.input_sha256,
            "time_basis": prediction.time_basis.value,
        }
        columns = tuple(values)
        with self._lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                existing = self.connection.execute(
                    "SELECT * FROM behavior_predictions WHERE prediction_id=?",
                    (prediction.prediction_id,),
                ).fetchone()
                if existing is not None:
                    if any(existing[key] != value for key, value in values.items()):
                        raise ValueError("prediction_id already exists with different prediction data")
                    self.connection.commit()
                    return False
                marks = ",".join("?" for _ in columns)
                self.connection.execute(
                    f"INSERT INTO behavior_predictions({','.join(columns)}) VALUES({marks})",
                    tuple(values[name] for name in columns),
                )
                self.connection.commit()
                return True
            except Exception:
                self.connection.rollback()
                raise

    def list_behavior_predictions(self, animal_id: str, *, limit: int = 100):
        """List predictions by animal and source clock, without UTC conversion."""
        from ...domain.contracts import EvidenceStatus
        from ...domain.intelligence import BehaviorPrediction, PredictionTimeBasis

        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError("limit must be an integer in [1, 10000]")
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM behavior_predictions WHERE animal_id=? "
                "ORDER BY window_start_s,prediction_id LIMIT ?", (animal_id, limit),
            ).fetchall()
        return [BehaviorPrediction(
            animal_id=row["animal_id"], tag_id=row["tag_id"],
            window_start_s=row["window_start_s"], window_end_s=row["window_end_s"],
            created_at_s=row["created_at_s"], behavior=row["behavior"],
            confidence=row["confidence"], model_score=row["model_score"],
            model_version=row["model_version"],
            model_sha256=row["model_sha256"], feature_version=row["feature_version"],
            evidence_status=EvidenceStatus(row["evidence_status"]),
            source_ref=row["source_ref"], input_sha256=row["input_sha256"],
            prediction_id=row["prediction_id"],
            time_basis=PredictionTimeBasis(row["time_basis"]),
        ) for row in rows]

    def get_behavior_prediction(self, prediction_id: str):
        """Fetch one prediction so deterministic replays can reuse its creation time."""
        from ...domain.contracts import EvidenceStatus
        from ...domain.intelligence import BehaviorPrediction, PredictionTimeBasis

        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM behavior_predictions WHERE prediction_id=?", (prediction_id,)
            ).fetchone()
        if row is None:
            return None
        return BehaviorPrediction(
            animal_id=row["animal_id"], tag_id=row["tag_id"],
            window_start_s=row["window_start_s"], window_end_s=row["window_end_s"],
            created_at_s=row["created_at_s"], behavior=row["behavior"],
            confidence=row["confidence"], model_score=row["model_score"],
            model_version=row["model_version"], model_sha256=row["model_sha256"],
            feature_version=row["feature_version"],
            evidence_status=EvidenceStatus(row["evidence_status"]),
            source_ref=row["source_ref"], input_sha256=row["input_sha256"],
            prediction_id=row["prediction_id"],
            time_basis=PredictionTimeBasis(row["time_basis"]),
        )


def _valid_behavior_time(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _behavior_values(observation: BehaviorObservation) -> dict[str, Any]:
    return {
        "animal_id": observation.animal_id,
        "timestamp_s": float(observation.timestamp_s),
        "end_timestamp_s": None if observation.end_timestamp_s is None else float(observation.end_timestamp_s),
        "behavior": observation.behavior,
        "confidence": None if observation.confidence is None else float(observation.confidence),
        "model_version": observation.model_version,
        "source": observation.source,
        "observation_kind": observation.observation_kind,
        "evidence_status": observation.evidence_status.value,
        "sensor_position": observation.sensor_position,
        "idempotency_key": observation.idempotency_key,
    }
