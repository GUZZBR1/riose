"""Local FastAPI interface and dashboard."""

from __future__ import annotations

from dataclasses import asdict
from contextlib import asynccontextmanager
from datetime import date
import json
import math
import os
from pathlib import Path
from typing import Any, Literal
import uuid
import sqlite3
from urllib.error import URLError
from urllib.request import Request as UrlRequest, urlopen

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..domain.behavior import BehaviorObservation
from ..domain.contracts import Anchor, EvidenceStatus, FarmConfig
from .persistence import Store
from ..domain.identity import make_cryptographic_id


class AnimalCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    animal_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    hardware_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    name: str | None = Field(default=None, max_length=120)
    sex: Literal["female", "male", "unknown"] | None = None
    breed: str | None = Field(default=None, max_length=120)
    birth_date: str | None = Field(default=None, max_length=10)
    weight_kg: float | None = Field(default=None, gt=0, le=3000, allow_inf_nan=False)
    property_name: str | None = Field(default=None, max_length=160)
    lot: str | None = Field(default=None, max_length=120)

    @field_validator("birth_date")
    @classmethod
    def validate_birth_date(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("birth_date must use YYYY-MM-DD") from exc
        return value


class EventCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    animal_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    event_type: Literal["OWNER_CHANGED", "WEIGHT_RECORDED", "VACCINATION", "HEALTH_EVENT", "TRANSFER", "SLAUGHTER", "SIMULATION_RUN_RECORDED"]
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: float | None = Field(default=None, allow_inf_nan=False)

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must contain finite JSON-compatible values") from exc
        if len(encoded.encode("utf-8")) > 65536:
            raise ValueError("payload must be at most 64 KiB")
        return value


class AnimalAssetSubmission(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    asset_address: str = Field(min_length=32, max_length=44, pattern=r"^[1-9A-HJ-NP-Za-km-z]+$")
    owner_address: str = Field(min_length=32, max_length=44, pattern=r"^[1-9A-HJ-NP-Za-km-z]+$")
    transaction_signature: str = Field(min_length=80, max_length=90, pattern=r"^[1-9A-HJ-NP-Za-km-z]+$")
    attempt_ref: str = Field(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")


class AnimalAssetReservation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    asset_address: str = Field(min_length=32, max_length=44, pattern=r"^[1-9A-HJ-NP-Za-km-z]+$")
    owner_address: str = Field(min_length=32, max_length=44, pattern=r"^[1-9A-HJ-NP-Za-km-z]+$")
    attempt_ref: str = Field(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")


class AnimalAssetAttemptRelease(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    attempt_ref: str = Field(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")


class AnimalAssetReconciliation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    transaction_signature: str = Field(min_length=80, max_length=90, pattern=r"^[1-9A-HJ-NP-Za-km-z]+$")


def devnet_signature_status(signature: str) -> dict[str, Any] | None:
    """Read one Devnet signature status from the configured Solana JSON-RPC."""
    endpoint = os.environ.get("RIOSE_SOLANA_DEVNET_RPC", "https://api.devnet.solana.com")
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": "riose-asset-reconcile",
        "method": "getSignatureStatuses",
        "params": [[signature], {"searchTransactionHistory": True}],
    }).encode("utf-8")
    request = UrlRequest(endpoint, data=payload, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict) or "error" in result:
        raise ValueError("Solana Devnet RPC returned an error")
    rpc_result = result.get("result")
    if not isinstance(rpc_result, dict):
        raise ValueError("Solana Devnet RPC response has no result object")
    values = rpc_result.get("value")
    if not isinstance(values, list):
        raise ValueError("Solana Devnet RPC response has no status list")
    if not values or values[0] is None:
        return None
    if not isinstance(values[0], dict):
        raise ValueError("Solana Devnet RPC status is malformed")
    return values[0]


class BehaviorObservationCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    animal_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    timestamp_s: float = Field(ge=0, allow_inf_nan=False, strict=True)
    end_timestamp_s: float | None = Field(default=None, ge=0, allow_inf_nan=False, strict=True)
    behavior: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False, strict=True)
    model_version: str | None = Field(default=None, min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:+/-]*$")
    observation_kind: Literal["PREDICTION", "GROUND_TRUTH", "MANUAL_ANNOTATION"]
    evidence_status: EvidenceStatus
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    sensor_position: str | None = Field(
        default=None, min_length=1, max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )

    @field_validator("end_timestamp_s")
    @classmethod
    def validate_interval(cls, value: float | None, info: Any) -> float | None:
        start = info.data.get("timestamp_s")
        if value is not None and start is not None and value < start:
            raise ValueError("end_timestamp_s must be >= timestamp_s")
        return value

    @field_validator("model_version")
    @classmethod
    def validate_prediction_model(cls, value: str | None, info: Any) -> str | None:
        if info.data.get("observation_kind") == "PREDICTION" and not value:
            raise ValueError("prediction requires model_version")
        return value


class AnchorInput(BaseModel):
    anchor_id: str = Field(min_length=1, max_length=64)
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)
    height_m: float = Field(default=3.0, gt=0, allow_inf_nan=False)
    kind: str = "esp32-c6-subghz"
    enabled: bool = True


class SimulationRequest(BaseModel):
    width_m: float = Field(default=1000.0, gt=0, le=100_000, allow_inf_nan=False)
    height_m: float = Field(default=1000.0, gt=0, le=100_000, allow_inf_nan=False)
    animal_count: int = Field(default=1, ge=1, le=1000)
    anchor_count: int = Field(default=4, ge=1, le=40)
    duration_s: float = Field(default=600, gt=0, le=604_800, allow_inf_nan=False)
    sample_period_s: float = Field(default=30, ge=0.001, le=604_800, allow_inf_nan=False)
    seed: int = 7
    packet_loss_probability: float = Field(default=0.05, ge=0, le=1, allow_inf_nan=False)
    method: str = "weighted_centroid"
    anchors: list[AnchorInput] | None = Field(default=None, min_length=1, max_length=40)


class CSIRequest(BaseModel):
    timestamp_s: float = Field(default=0.0, allow_inf_nan=False)
    tag_id: str = "tag-0001"
    anchor_id: str = "anchor-01"
    movement_intensity: float = Field(default=0.2, ge=0, allow_inf_nan=False)
    seed: int = 7


# Bound the in-memory API pipeline before constructing episode/training tuples.
# The budget accounts for episodes, grouped estimator input, truth, and results;
# supervised methods include three additional training episodes.
MAX_SIMULATION_OBSERVATIONS = 500_000
MAX_SIMULATION_MEMORY_UNITS = 1_000_000


def estimate_simulation_observations(body: SimulationRequest, enabled_anchors: int) -> int:
    episode_steps = max(1, math.ceil(body.duration_s / body.sample_period_s))
    count = body.animal_count * episode_steps * enabled_anchors
    if body.method in {"extra_trees", "gradient_boosting"}:
        training_animals = max(300, min(body.animal_count, 1000))
        training_steps = max(1, math.ceil(max(600.0, body.duration_s) /
                                          min(30.0, body.sample_period_s)))
        count += 3 * training_animals * training_steps * enabled_anchors
    return count


def estimate_simulation_memory_units(body: SimulationRequest, enabled_anchors: int) -> int:
    """Estimate allocated per-sample records, including truth and motion.

    RF observation counts alone are not a safe admission bound: movement and
    ground-truth records are generated even when every receiver is disabled.
    One inference sample accounts for truth, motion, observations, and its
    estimate. A supervised training sample accounts for truth, motion,
    observations, and the matching feature/target rows used during fitting.
    """
    episode_steps = max(1, math.ceil(body.duration_s / body.sample_period_s))
    episode_samples = body.animal_count * episode_steps
    units = episode_samples * (enabled_anchors + 3)
    if body.method in {"extra_trees", "gradient_boosting"}:
        training_animals = max(300, min(body.animal_count, 1000))
        training_steps = max(1, math.ceil(max(600.0, body.duration_s) /
                                          min(30.0, body.sample_period_s)))
        units += 3 * training_animals * training_steps * (enabled_anchors + 3)
    return units


def create_app(db_path: str | Path = "data/cattle_rf.sqlite3") -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            app.state.store.close()

    app = FastAPI(title="Cattle RF Local MVP", version="0.1.0", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.exception_handler(RequestValidationError)
    async def validation_error_response(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Python's JSON parser accepts NaN/Infinity extensions. Pydantic correctly
        # rejects them, but its default error payload echoes the raw non-finite
        # input and Starlette cannot serialize that payload as JSON.
        def json_safe(value: Any) -> Any:
            if isinstance(value, float) and not math.isfinite(value):
                return repr(value)
            if isinstance(value, BaseException):
                return str(value)
            if isinstance(value, dict):
                return {key: json_safe(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [json_safe(item) for item in value]
            return value

        return JSONResponse(status_code=422, content={"detail": json_safe(exc.errors())})

    app.state.store = Store(db_path)
    static_dir = Path(__file__).parent / "static"
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="site-assets")

    @app.get("/", response_class=HTMLResponse)
    def landing_page() -> str:
        return (static_dir / "landing.html").read_text(encoding="utf-8")

    @app.get("/manifesto", response_class=HTMLResponse)
    def manifesto_page() -> str:
        return (static_dir / "manifesto.html").read_text(encoding="utf-8")

    @app.get("/demo", response_class=HTMLResponse)
    def dashboard() -> str:
        return (static_dir / "index.html").read_text(encoding="utf-8")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "evidence": "SIMULATED"}

    @app.get("/api/animals")
    def animals() -> list[dict[str, Any]]:
        return app.state.store.list_animals()

    @app.post("/api/animals", status_code=201)
    def create_animal(body: AnimalCreate) -> dict[str, Any]:
        try:
            return app.state.store.create_animal(
                body.animal_id, body.hardware_id, make_cryptographic_id(),
                **body.model_dump(exclude={"animal_id", "hardware_id"}),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="animal_id or hardware_id already exists") from exc

    @app.post("/api/animals/{animal_id}/asset-intent")
    def prepare_animal_asset(animal_id: str, request: Request) -> dict[str, Any]:
        record = app.state.store.prepare_animal_asset(animal_id)
        if record is None:
            raise HTTPException(status_code=404, detail="animal not found")
        attempt = app.state.store.get_animal_asset_attempt(animal_id)
        active_attempt = attempt if attempt and attempt["status"] == "RESERVED" else None
        status = "SIGNING" if active_attempt else record["status"]
        metadata_uri = str(request.url_for(
            "animal_asset_metadata", public_ref=record["public_ref"]
        ))
        return {
            "cluster": "devnet",
            "status": status,
            "public_ref": record["public_ref"],
            "metadata_uri": metadata_uri,
            "asset_address": active_attempt["asset_address"] if active_attempt else record["asset_address"],
            "owner_address": active_attempt["owner_address"] if active_attempt else record["owner_address"],
            "transaction_signature": record["transaction_signature"],
            "attempt_ref": active_attempt["attempt_ref"] if active_attempt else None,
            "evidence": "ATTEMPT_RESERVED" if active_attempt else "PREPARED",
        }

    @app.post("/api/animals/{animal_id}/asset-reserve")
    def reserve_animal_asset(animal_id: str, body: AnimalAssetReservation,
                             request: Request) -> dict[str, Any]:
        current = app.state.store.get_animal_asset(animal_id)
        if current is None:
            if app.state.store.get_animal(animal_id) is None:
                raise HTTPException(status_code=404, detail="animal not found")
            raise HTTPException(status_code=409, detail="create an asset intent first")
        metadata_uri = str(request.url_for(
            "animal_asset_metadata", public_ref=current["public_ref"]
        ))
        try:
            attempt = app.state.store.reserve_animal_asset_attempt(
                animal_id,
                attempt_ref=body.attempt_ref,
                asset_address=body.asset_address,
                owner_address=body.owner_address,
                metadata_uri=metadata_uri,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="asset address or attempt reference already reserved") from exc
        if attempt is None:
            raise HTTPException(status_code=404, detail="animal not found")
        return {
            "cluster": attempt["cluster"],
            "status": attempt["status"],
            "attempt_ref": attempt["attempt_ref"],
            "asset_address": attempt["asset_address"],
            "owner_address": attempt["owner_address"],
            "metadata_uri": attempt["metadata_uri"],
            "evidence": "ATTEMPT_RESERVED",
        }

    @app.post("/api/animals/{animal_id}/asset-release")
    def release_animal_asset_attempt(animal_id: str,
                                     body: AnimalAssetAttemptRelease) -> dict[str, str]:
        current = app.state.store.get_animal_asset(animal_id)
        attempt = app.state.store.get_animal_asset_attempt(animal_id)
        if (current is not None and current["status"] == "PREPARED"
                and attempt is None):
            return {"cluster": "devnet", "status": "PREPARED", "evidence": "UNSIGNED_RESERVATION_RELEASED"}
        released = app.state.store.release_animal_asset_attempt(animal_id, body.attempt_ref)
        if not released:
            raise HTTPException(status_code=409, detail="only the matching unsigned reservation can be released")
        return {"cluster": "devnet", "status": "PREPARED", "evidence": "UNSIGNED_RESERVATION_RELEASED"}

    @app.post("/api/animals/{animal_id}/asset-submission")
    def submit_animal_asset(
        animal_id: str, body: AnimalAssetSubmission, request: Request
    ) -> dict[str, Any]:
        current = app.state.store.get_animal_asset(animal_id)
        if current is None:
            if app.state.store.get_animal(animal_id) is None:
                raise HTTPException(status_code=404, detail="animal not found")
            raise HTTPException(status_code=409, detail="create an asset intent first")
        metadata_uri = str(request.url_for(
            "animal_asset_metadata", public_ref=current["public_ref"]
        ))
        try:
            record = app.state.store.submit_animal_asset(
                animal_id,
                asset_address=body.asset_address,
                owner_address=body.owner_address,
                metadata_uri=metadata_uri,
                transaction_signature=body.transaction_signature,
                attempt_ref=body.attempt_ref,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="asset address or transaction signature already registered") from exc
        if record is None:
            raise HTTPException(status_code=404, detail="animal not found")
        return {
            "cluster": record["cluster"],
            "status": record["status"],
            "asset_address": record["asset_address"],
            "owner_address": record["owner_address"],
            "metadata_uri": record["metadata_uri"],
            "transaction_signature": record["transaction_signature"],
            "evidence": "SUBMITTED_UNVERIFIED",
        }

    @app.get("/api/animals/{animal_id}/asset")
    def animal_asset(animal_id: str, request: Request) -> dict[str, Any]:
        record = app.state.store.get_animal_asset(animal_id)
        if record is None:
            if app.state.store.get_animal(animal_id) is None:
                raise HTTPException(status_code=404, detail="animal not found")
            return {
                "cluster": "devnet",
                "status": "UNREGISTERED",
                "asset_address": None,
                "owner_address": None,
                "metadata_uri": None,
                "transaction_signature": None,
                "evidence": "UNREGISTERED",
            }
        metadata_uri = str(request.url_for(
            "animal_asset_metadata", public_ref=record["public_ref"]
        ))
        attempt = app.state.store.get_animal_asset_attempt(animal_id)
        active_attempt = attempt if attempt and attempt["status"] == "RESERVED" else None
        status = "SIGNING" if record["status"] == "PREPARED" and active_attempt else record["status"]
        return {
            "cluster": record["cluster"],
            "status": status,
            "asset_address": active_attempt["asset_address"] if active_attempt else record["asset_address"],
            "owner_address": active_attempt["owner_address"] if active_attempt else record["owner_address"],
            "metadata_uri": (active_attempt["metadata_uri"] if active_attempt else record["metadata_uri"]) or metadata_uri,
            "transaction_signature": record["transaction_signature"],
            "attempt_ref": active_attempt["attempt_ref"] if active_attempt else None,
            "evidence": ("ATTEMPT_RESERVED" if status == "SIGNING" else
                         "PREPARED" if status == "PREPARED" else "SUBMITTED_UNVERIFIED"),
        }

    @app.post("/api/animals/{animal_id}/asset-reconcile")
    def reconcile_animal_asset(
        animal_id: str, body: AnimalAssetReconciliation
    ) -> dict[str, Any]:
        record = app.state.store.get_animal_asset(animal_id)
        if record is None:
            if app.state.store.get_animal(animal_id) is None:
                raise HTTPException(status_code=404, detail="animal not found")
            raise HTTPException(status_code=409, detail="animal has no submitted asset")
        if record["status"] != "SUBMITTED" or record["transaction_signature"] != body.transaction_signature:
            raise HTTPException(status_code=409, detail="signature does not match the submitted asset")
        try:
            status = devnet_signature_status(body.transaction_signature)
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=503, detail="Devnet RPC is unavailable; submission state is unchanged") from exc
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="Devnet RPC returned an invalid response") from exc
        if status is None or status.get("confirmationStatus") not in {"confirmed", "finalized"}:
            raise HTTPException(status_code=409, detail="transaction outcome is still unknown; state is unchanged")
        if status.get("err") is None:
            raise HTTPException(status_code=409, detail="transaction succeeded; state is unchanged")
        reset = app.state.store.reset_failed_animal_asset(animal_id, body.transaction_signature)
        if reset is None or reset["status"] != "PREPARED":
            raise HTTPException(status_code=409, detail="submitted asset changed during reconciliation")
        return {"cluster": "devnet", "status": "PREPARED", "evidence": "ONCHAIN_FAILURE_CONFIRMED"}

    @app.get("/api/animal-assets/metadata/{public_ref}", name="animal_asset_metadata")
    def animal_asset_metadata(public_ref: str, request: Request) -> dict[str, Any]:
        public_name = app.state.store.animal_asset_public_name(public_ref)
        if public_name is None:
            raise HTTPException(status_code=404, detail="asset metadata not found")
        return {
            "name": public_name,
            "description": "Digital identity only. It does not verify animal records or prove physical identity or ownership.",
            "image": str(request.url_for("site-assets", path="riose-mark.png")),
            "external_url": str(request.base_url),
            "attributes": [],
        }

    @app.get("/api/animals/{animal_id}")
    def animal(animal_id: str) -> dict[str, Any]:
        result = app.state.store.get_animal(animal_id)
        if result is None:
            raise HTTPException(status_code=404, detail="animal not found")
        result["trajectory"] = app.state.store.animal_trajectory(animal_id, limit=100)
        return result

    @app.post("/api/animals/{animal_id}/behaviors", status_code=201)
    def create_behavior_observation(animal_id: str, body: BehaviorObservationCreate) -> Any:
        if animal_id != body.animal_id:
            raise HTTPException(status_code=422, detail="path animal_id must match body animal_id")
        if app.state.store.get_animal(animal_id) is None:
            raise HTTPException(status_code=404, detail="animal not found")
        try:
            observation = BehaviorObservation(**body.model_dump())
            saved, created = app.state.store.save_behavior_observation(observation)
            return JSONResponse(status_code=201 if created else 200, content=saved)
        except ValueError as exc:
            status = 409 if "idempotency_key" in str(exc) else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.get("/api/animals/{animal_id}/behaviors")
    def behavior_history(
        animal_id: str,
        start_s: float | None = Query(None, ge=0, allow_inf_nan=False),
        end_s: float | None = Query(None, ge=0, allow_inf_nan=False),
        behavior: str | None = Query(None, min_length=1, max_length=128),
        source: str | None = Query(None, min_length=1, max_length=128),
        model_version: str | None = Query(None, min_length=1, max_length=128),
        evidence_status: EvidenceStatus | None = None,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0, le=1_000_000),
    ) -> list[dict[str, Any]]:
        if start_s is not None and end_s is not None and end_s < start_s:
            raise HTTPException(status_code=422, detail="end_s must be >= start_s")
        result = app.state.store.behavior_history(
            animal_id, start_s=start_s, end_s=end_s, behavior=behavior, source=source,
            model_version=model_version,
            evidence_status=None if evidence_status is None else evidence_status.value,
            limit=limit, offset=offset,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="animal not found")
        return result

    @app.get("/api/animals/{animal_id}/trajectory")
    def animal_trajectory(animal_id: str, limit: int = Query(1000, ge=1, le=10000),
                          run_id: str | None = Query(None, min_length=1, max_length=64)) -> list[dict[str, Any]]:
        result = app.state.store.animal_trajectory(animal_id, limit, run_id=run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="animal not found")
        return result

    @app.get("/api/anchors")
    def anchors() -> list[dict[str, Any]]:
        return app.state.store.list_anchors()

    @app.get("/api/positions")
    def positions(limit: int = Query(1000, ge=1, le=10000), debug: bool = False,
                  at_s: float | None = Query(None, ge=0)) -> list[dict[str, Any]]:
        # Ground truth is joined only after an explicit debug request.
        return app.state.store.positions(limit, debug=debug, at_s=at_s)

    @app.get("/api/positions/history")
    def position_history(tag_id: str = Query(min_length=1, max_length=64),
                         limit: int = Query(1000, ge=1, le=10000),
                         debug: bool = False) -> list[dict[str, Any]]:
        # Historical ground truth remains isolated behind the explicit debug flag.
        return app.state.store.positions_history(tag_id, limit, debug=debug)

    @app.get("/api/telemetry")
    def telemetry(limit: int = Query(1000, ge=1, le=10000),
                  tag_id: str | None = Query(None, min_length=1, max_length=64)) -> list[dict[str, Any]]:
        return app.state.store.telemetry(limit, tag_id)

    @app.get("/api/events")
    def events(limit: int = Query(1000, ge=1, le=10000)) -> list[dict[str, Any]]:
        return app.state.store.events(limit)

    @app.post("/api/events", status_code=201)
    def append_animal_event(body: EventCreate) -> dict[str, Any]:
        if app.state.store.get_animal(body.animal_id) is None:
            raise HTTPException(status_code=404, detail="animal not found")
        try:
            event = app.state.store.append_animal_event(
                body.animal_id, body.event_type, body.payload, body.timestamp)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {**asdict(event), "chain_valid": app.state.store.verify_animal_chain(body.animal_id)}

    @app.get("/api/animals/{animal_id}/events/verify")
    def verify_animal_events(animal_id: str) -> dict[str, Any]:
        if app.state.store.get_animal(animal_id) is None:
            raise HTTPException(status_code=404, detail="animal not found")
        return {"animal_id": animal_id,
                "valid": app.state.store.verify_animal_chain(animal_id),
                "evidence": "LOCAL_HASH_CHAIN"}

    @app.post("/api/simulation/run")
    def run_simulation(body: SimulationRequest) -> dict[str, Any]:
        from ..application.pipeline import run_episode
        config = FarmConfig(
            width_m=body.width_m, height_m=body.height_m,
            animal_count=body.animal_count, anchor_count=body.anchor_count,
            duration_s=body.duration_s, sample_period_s=body.sample_period_s,
            seed=body.seed, packet_loss_probability=body.packet_loss_probability,
        )
        anchor_set = None
        if body.anchors is not None:
            ids = [anchor.anchor_id for anchor in body.anchors]
            if len(body.anchors) != body.anchor_count:
                raise HTTPException(status_code=422, detail="anchor_count must match the supplied anchors")
            if len(ids) != len(set(ids)):
                raise HTTPException(status_code=422, detail="anchor_id values must be unique")
            if any(anchor.x < 0 or anchor.x > body.width_m or anchor.y < 0 or anchor.y > body.height_m
                   for anchor in body.anchors):
                raise HTTPException(status_code=422, detail="anchor coordinates must be inside the farm")
            anchor_set = tuple(Anchor(**anchor.model_dump()) for anchor in body.anchors)
        enabled_anchors = (sum(anchor.enabled for anchor in anchor_set)
                           if anchor_set is not None else body.anchor_count)
        if enabled_anchors < 1:
            raise HTTPException(status_code=422, detail="at least one anchor must be enabled")
        estimated_observations = estimate_simulation_observations(body, enabled_anchors)
        if estimated_observations > MAX_SIMULATION_OBSERVATIONS:
            raise HTTPException(
                status_code=422,
                detail=(f"requested simulation exceeds the in-memory observation budget "
                        f"({estimated_observations:,} > {MAX_SIMULATION_OBSERVATIONS:,}); "
                        "increase sample_period_s or reduce duration_s, animal_count, anchors, "
                        "or use a non-supervised method"),
            )
        estimated_memory_units = estimate_simulation_memory_units(body, enabled_anchors)
        if estimated_memory_units > MAX_SIMULATION_MEMORY_UNITS:
            raise HTTPException(
                status_code=422,
                detail=(f"requested simulation exceeds the in-memory sample budget "
                        f"({estimated_memory_units:,} > {MAX_SIMULATION_MEMORY_UNITS:,}); "
                        "increase sample_period_s or reduce duration_s or animal_count"),
            )
        try:
            episode, estimates, metrics = run_episode(config, body.method, anchors=anchor_set)
        except (ImportError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        run_id = uuid.uuid4().hex
        app.state.store.replace_anchors(episode.anchors)
        app.state.store.save_episode(
            episode.observations, estimates, episode.ground_truth, run_id=run_id,
        )
        app.state.store.set_metrics(metrics)
        ensure_animals(app.state.store, body.animal_count)
        return {"status": "completed", "evidence": "SIMULATED", "observations": len(episode.observations),
                "estimates": len(estimates), "run_id": run_id, "metrics": metrics}

    @app.get("/api/experiments")
    def experiments() -> dict[str, Any]:
        return {"available_methods": ["strongest_anchor", "weighted_centroid", "path_loss", "extra_trees", "gradient_boosting", "temporal_fusion"],
                "advanced_rf": capability_status(), "evidence": "SIMULATED"}

    @app.post("/api/experiments/csi")
    def simulated_csi(body: CSIRequest) -> dict[str, Any]:
        from dataclasses import asdict
        from ..simulation.experimental import simulate_wifi_csi
        return asdict(simulate_wifi_csi(body.timestamp_s, body.tag_id, body.anchor_id,
                                        body.movement_intensity, body.seed))

    @app.get("/api/capabilities")
    def capabilities() -> dict[str, Any]:
        from ..simulation.advanced import advanced_capabilities
        return {"advanced_rf": advanced_capabilities(), "hardware": capability_status(),
                "cellular": "FUTURE"}

    @app.get("/api/metrics")
    def metrics() -> dict[str, Any]:
        return app.state.store.get_metrics()

    return app


def ensure_animals(store: Store, count: int) -> None:
    import sqlite3
    import uuid
    for index in range(count):
        animal_id = f"cow-{index + 1:04d}"
        if store.get_animal(animal_id) is None:
            try:
                store.create_animal(animal_id, f"tag-{index + 1:04d}", make_cryptographic_id(),
                                    name=f"Animal {index + 1}", property_name="Demo Farm")
            except sqlite3.IntegrityError:
                continue


def capability_status() -> dict[str, bool]:
    import importlib.util
    import shutil
    try:
        ns3_python = importlib.util.find_spec("ns.core") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        ns3_python = False
    return {
        "sionna": importlib.util.find_spec("sionna") is not None,
        "ns3": shutil.which("ns3") is not None or ns3_python,
        "wokwi_cli": shutil.which("wokwi-cli") is not None,
        "zephyr_west": shutil.which("west") is not None,
        "ngspice": shutil.which("ngspice") is not None,
        "kicad_cli": shutil.which("kicad-cli") is not None,
    }
