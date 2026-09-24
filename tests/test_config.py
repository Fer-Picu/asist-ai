from __future__ import annotations

from pathlib import Path

import pytest

from asit_ia.config import ConfigError, load_config, parse_config


def test_missing_config_writes_defaults(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = tmp_path / "config.yaml"

    cfg = load_config(config_path)

    assert config_path.exists()
    assert cfg.audio.device == "default"
    assert cfg.audio.sample_rate == 16000
    assert cfg.audio.silence_timeout_ms == 500
    assert cfg.model.path.name == "ggml-tiny.bin"
    assert "Wrote default config" in capsys.readouterr().out


def test_valid_config_loads_and_expands_model_path(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
model:
  path: ~/models/custom.bin
audio:
  device: hw:2,0
  sample_rate: 16000
  channels: 1
  format: S16_LE
  silence_timeout_ms: 500
vad:
  aggressiveness: 2
""",
        encoding="utf-8",
    )

    cfg = load_config(config_path)

    assert cfg.model.path == Path("~/models/custom.bin").expanduser()
    assert cfg.audio.device == "hw:2,0"
    assert cfg.vad.aggressiveness == 2


def test_malformed_yaml_reports_line_number(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("audio:\n  device: [unterminated\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=r"line \d+"):
        load_config(config_path)


def test_invalid_vad_aggressiveness_is_rejected() -> None:
    with pytest.raises(ConfigError, match="vad.aggressiveness must be 0–3"):
        parse_config({"audio": {}, "vad": {"aggressiveness": 5}, "model": {}})


def test_invalid_sample_rate_is_rejected() -> None:
    with pytest.raises(ConfigError, match="audio.sample_rate must be 16000"):
        parse_config({"audio": {"sample_rate": 44100}, "vad": {}, "model": {}})


def test_injection_mode_default_is_clipboard() -> None:
    cfg = parse_config({"audio": {}, "vad": {}, "model": {}})
    assert cfg.injection.mode == "clipboard"


def test_model_language_auto_is_forced_to_spanish() -> None:
    cfg = parse_config({"audio": {}, "vad": {}, "model": {"language": "auto"}})
    assert cfg.model.language == "es"


def test_injection_mode_parsed_from_config() -> None:
    cfg = parse_config(
        {"audio": {}, "vad": {}, "model": {}, "injection": {"mode": "injection"}}
    )
    assert cfg.injection.mode == "injection"


def test_injection_mode_override_clobbers_config() -> None:
    cfg = parse_config(
        {
            "audio": {},
            "vad": {},
            "model": {},
            "injection": {"mode": "injection"},
        }
    )
    assert cfg.injection.mode == "injection"


def test_cli_style_overrides_do_not_modify_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("audio:\n  device: default\n", encoding="utf-8")

    cfg = load_config(config_path, {"audio": {"device": "hw:2,0"}})

    assert cfg.audio.device == "hw:2,0"
    assert "device: default" in config_path.read_text(encoding="utf-8")
