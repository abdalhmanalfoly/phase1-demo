"""Typed configuration loaded from ``config/*.yaml`` with a small set of environment overrides."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT_DIR = Path(__file__).resolve().parents[2]
HOST_VERSION = "0.1.0"


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServerCfg(_Cfg):
    host: str = "0.0.0.0"
    port: int = Field(8765, ge=1, le=65535)
    allowed_origins: list[str] = []
    public_ws_url: str | None = None


class SessionCfg(_Cfg):
    max_sessions: int = Field(8, ge=1)
    max_sensors: int = Field(4, ge=1, le=32)
    hello_timeout_s: float = Field(5.0, gt=0)
    sweep_interval_s: float = Field(1.0, gt=0)
    retain_stopped_sessions: int = Field(16, ge=0)


class LoggingCfg(_Cfg):
    log_dir: str = "logs"
    save_landmark_events: bool = True
    save_raw_video: bool = False
    recent_events_buffer: int = Field(200, ge=10)

    @model_validator(mode="after")
    def _no_video(self):
        if self.save_raw_video:
            raise ValueError("logging.save_raw_video=true is refused: Phase 1 has no video path "
                             "and raw video must not be persisted by default")
        return self


class LimitsCfg(_Cfg):
    max_message_bytes: int = Field(16384, ge=1024)
    max_observation_hz_host: int = Field(60, ge=1)
    error_throttle_ms: int = Field(1000, ge=0)


class HeartbeatCfg(_Cfg):
    interval_ms: int = Field(2000, ge=100)
    degraded_after_ms: int = 4500
    offline_after_ms: int = 8000

    @model_validator(mode="after")
    def _ordered(self):
        if not (self.interval_ms < self.degraded_after_ms < self.offline_after_ms):
            raise ValueError("heartbeat: need interval_ms < degraded_after_ms < offline_after_ms")
        return self


class ObservationCfg(_Cfg):
    max_ingress_age_ms: int = Field(2000, ge=1)
    max_future_skew_ms: int = Field(1000, ge=0)
    rate_window_ms: int = Field(5000, ge=1000)


class VisionCfg(_Cfg):
    target_update_hz: float = Field(15, gt=0, le=120)
    max_update_hz: float = Field(30, gt=0, le=120)
    min_detection_confidence: float = Field(0.5, ge=0, le=1)
    min_presence_confidence: float = Field(0.5, ge=0, le=1)
    min_tracking_confidence: float = Field(0.5, ge=0, le=1)
    required_landmarks: list[str]
    optional_landmarks: list[str] = []

    @model_validator(mode="after")
    def _caps(self):
        if self.target_update_hz > self.max_update_hz:
            raise ValueError("vision.target_update_hz must be <= max_update_hz")
        return self


class ReconnectCfg(_Cfg):
    base_ms: int = Field(500, ge=50)
    max_ms: int = Field(10000, ge=100)
    factor: float = Field(2, ge=1)
    jitter: float = Field(0.2, ge=0, le=1)


class ClientCfg(_Cfg):
    reconnect: ReconnectCfg = ReconnectCfg()
    max_buffered_bytes: int = Field(65536, ge=1024)


class ThresholdsCfg(_Cfg):
    heartbeat: HeartbeatCfg = HeartbeatCfg()
    observation: ObservationCfg = ObservationCfg()
    vision: VisionCfg
    client: ClientCfg = ClientCfg()


class CameraCfg(_Cfg):
    facing_mode: str = Field("user", pattern="^(user|environment)$")
    ideal_width: int = Field(640, ge=64)
    ideal_height: int = Field(480, ge=64)
    ideal_frame_rate: int = Field(30, ge=1, le=120)
    flip_handedness: bool = True


class ModelCfg(_Cfg):
    name: str
    variant: str
    version: str
    mediapipe_tasks_vision_version: str
    bundle_path: str
    wasm_path: str
    model_path: str


class Settings(BaseModel):
    server: ServerCfg
    session: SessionCfg
    logging: LoggingCfg
    limits: LimitsCfg
    thresholds: ThresholdsCfg
    camera: CameraCfg
    model: ModelCfg
    root_dir: Path = ROOT_DIR
    sweeper_enabled: bool = True

    @property
    def log_dir(self) -> Path:
        p = Path(self.logging.log_dir)
        return p if p.is_absolute() else self.root_dir / p

    @property
    def client_dir(self) -> Path:
        return self.root_dir / "sensor-client"

    def model_version_string(self) -> str:
        m = self.model
        return f"{m.name}/{m.variant}/{m.version}; tasks-vision {m.mediapipe_tasks_vision_version}"

    def client_config(self) -> dict:
        """Everything the browser needs; served at ``/api/client-config`` (single source of truth)."""
        t, v = self.thresholds, self.thresholds.vision
        return {
            "protocol_version": "1.0",
            "host_version": HOST_VERSION,
            "ws_path": "/ws/sensor",
            "public_ws_url": self.server.public_ws_url,
            "vision": {
                "target_update_hz": v.target_update_hz, "max_update_hz": v.max_update_hz,
                "min_detection_confidence": v.min_detection_confidence,
                "min_presence_confidence": v.min_presence_confidence,
                "min_tracking_confidence": v.min_tracking_confidence,
                "required_landmarks": v.required_landmarks, "optional_landmarks": v.optional_landmarks,
            },
            "camera": self.camera.model_dump(),
            "model": {**self.model.model_dump(), "version_string": self.model_version_string()},
            "reconnect": t.client.reconnect.model_dump(),
            "max_buffered_bytes": t.client.max_buffered_bytes,
        }


def _yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_settings(config_dir: Path | str | None = None, env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    cdir = Path(config_dir or env.get("SAGA_CONFIG_DIR") or ROOT_DIR / "config")
    app, thr, cam = _yaml(cdir / "app.yaml"), _yaml(cdir / "thresholds.yaml"), _yaml(cdir / "camera.yaml")
    server = dict(app.get("server", {}))
    logging_cfg = dict(app.get("logging", {}))
    if env.get("SAGA_HOST"):
        server["host"] = env["SAGA_HOST"]
    if env.get("SAGA_PORT"):
        server["port"] = int(env["SAGA_PORT"])
    if env.get("SAGA_PUBLIC_WS_URL"):
        server["public_ws_url"] = env["SAGA_PUBLIC_WS_URL"]
    if "SAGA_ALLOWED_ORIGINS" in env and env["SAGA_ALLOWED_ORIGINS"].strip():
        server["allowed_origins"] = [o.strip() for o in env["SAGA_ALLOWED_ORIGINS"].split(",") if o.strip()]
    if env.get("SAGA_LOG_DIR"):
        logging_cfg["log_dir"] = env["SAGA_LOG_DIR"]
    return Settings(
        server=server, session=app.get("session", {}), logging=logging_cfg, limits=app.get("limits", {}),
        thresholds=thr, camera=cam.get("camera", {}), model=cam["model"],
    )
