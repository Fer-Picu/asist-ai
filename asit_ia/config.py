from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


CONFIG_DIR = Path("~/.config/asit-ia").expanduser()
CONFIG_PATH = CONFIG_DIR / "config.yaml"
DEFAULT_MODEL_PATH = CONFIG_DIR / "models" / "ggml-tiny.bin"


class ConfigError(Exception):
    """Configuration error that should exit with code 4."""


@dataclass(slots=True)
class AudioConfig:
    device: str = "default"
    sample_rate: int = 16000
    channels: int = 1
    format: str = "S16_LE"
    silence_timeout_ms: int = 500


@dataclass(slots=True)
class VadConfig:
    aggressiveness: int = 3
    frame_ms: int = 20
    ring_buffer_seconds: float = 2.0


@dataclass(slots=True)
class ModelConfig:
    path: Path = DEFAULT_MODEL_PATH
    threads: int = 4
    language: str = "es"


@dataclass(slots=True)
class InjectionConfig:
    mode: str = "clipboard"  # "clipboard" | "injection"
    display: str = ":0"
    typing_speed_ms: int = 0


@dataclass(slots=True)
class Config:
    audio: AudioConfig
    vad: VadConfig
    model: ModelConfig
    injection: InjectionConfig

    @classmethod
    def defaults(cls) -> "Config":
        return cls(AudioConfig(), VadConfig(), ModelConfig(), InjectionConfig())


def _expand_path(value: str | Path) -> Path:
    return Path(value).expanduser()


def default_config_dict() -> dict[str, Any]:
    return {
        "model": {"path": str(DEFAULT_MODEL_PATH), "threads": 4, "language": "es"},
        "audio": {
            "device": "default",
            "sample_rate": 16000,
            "channels": 1,
            "format": "S16_LE",
            "silence_timeout_ms": 500,
        },
        "vad": {"aggressiveness": 3, "frame_ms": 20, "ring_buffer_seconds": 2.0},
        "injection": {"mode": "clipboard", "display": ":0", "typing_speed_ms": 0},
    }


def write_default_config(path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(default_config_dict(), sort_keys=False), encoding="utf-8")


def load_config(path: Path = CONFIG_PATH, overrides: dict[str, Any] | None = None) -> Config:
    if not path.exists():
        write_default_config(path)
        print(f"Wrote default config to {path}")
        data = default_config_dict()
    else:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            line = f" line {mark.line + 1}" if mark else ""
            raise ConfigError(f"Malformed YAML in {path}{line}: {exc}") from exc
        if raw is None:
            data = default_config_dict()
        elif not isinstance(raw, dict):
            raise ConfigError("config root must be a mapping")
        else:
            data = _deep_merge(default_config_dict(), raw)

    if overrides:
        data = _deep_merge(data, overrides)
    return parse_config(data)


def parse_config(data: dict[str, Any]) -> Config:
    try:
        audio_data = data["audio"]
        vad_data = data["vad"]
        model_data = data["model"]
        injection_data = data.get("injection", {})
    except KeyError as exc:
        raise ConfigError(f"missing config key: {exc.args[0]}") from exc

    cfg = Config(
        audio=AudioConfig(
            device=str(audio_data.get("device", "default")),
            sample_rate=int(audio_data.get("sample_rate", 16000)),
            channels=int(audio_data.get("channels", 1)),
            format=str(audio_data.get("format", "S16_LE")),
            silence_timeout_ms=int(audio_data.get("silence_timeout_ms", 500)),
        ),
        vad=VadConfig(
            aggressiveness=int(vad_data.get("aggressiveness", vad_data.get("mode", 3))),
            frame_ms=int(vad_data.get("frame_ms", 20)),
            ring_buffer_seconds=float(vad_data.get("ring_buffer_seconds", 2.0)),
        ),
        model=ModelConfig(
            path=_expand_path(model_data.get("path", DEFAULT_MODEL_PATH)),
            threads=int(model_data.get("threads", 4)),
            language=_parse_model_language(model_data.get("language", "es")),
        ),
        injection=InjectionConfig(
            mode=str(injection_data.get("mode", "clipboard")),
            display=str(injection_data.get("display", ":0")),
            typing_speed_ms=int(injection_data.get("typing_speed_ms", 0)),
        ),
    )
    validate_config(cfg)
    return cfg


def validate_config(cfg: Config) -> None:
    if cfg.audio.sample_rate != 16000:
        raise ConfigError("audio.sample_rate must be 16000 for whisper.cpp compatibility")
    if cfg.audio.channels != 1:
        raise ConfigError("audio.channels must be 1")
    if cfg.audio.format != "S16_LE":
        raise ConfigError("audio.format must be S16_LE")
    if cfg.vad.aggressiveness not in range(4):
        raise ConfigError("vad.aggressiveness must be 0–3")
    if cfg.vad.frame_ms not in (10, 20, 30):
        raise ConfigError("vad.frame_ms must be 10, 20, or 30")
    if cfg.audio.silence_timeout_ms <= 0:
        raise ConfigError("audio.silence_timeout_ms must be positive")


def _parse_model_language(value: Any) -> str:
    language = str(value or "es").strip().lower()
    return "es" if language in {"", "auto"} else language


def update_model_path(path: Path, config_path: Path = CONFIG_PATH) -> None:
    cfg = default_config_dict()
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            cfg = _deep_merge(cfg, loaded)
    cfg.setdefault("model", {})["path"] = str(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
