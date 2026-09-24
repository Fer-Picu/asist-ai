from __future__ import annotations

import argparse
import asyncio
import logging
import math
import os
import signal
import subprocess
import sys
import warnings
from pathlib import Path

# webrtcvad triggers a pkg_resources deprecation warning at import time
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")

from asit_ia.audio.capture import detect_default_source, format_devices, list_audio_devices
from asit_ia.config import CONFIG_PATH, ConfigError, load_config, update_model_path
from asit_ia.daemon import PID_FILE, run_push_to_talk

PID_FILE_CLEAN = PID_FILE  # alias for toggle logic

MODEL_NAMES = {"tiny": "ggml-tiny.bin", "base": "ggml-base.bin"}


def positive_duration(value: str) -> float:
    duration = float(value)
    if not math.isfinite(duration) or duration <= 0:
        raise argparse.ArgumentTypeError("duration must be a finite positive number")
    return duration


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asit-ia")
    parser.add_argument("command", nargs="?", choices=["list-devices"], help="optional command")
    parser.add_argument("--device", help="ALSA/PipeWire capture device, e.g. default or hw:2,0")
    parser.add_argument("--model", help="Path to GGML whisper.cpp model")
    parser.add_argument(
        "--download-model", choices=sorted(MODEL_NAMES), help="Download a GGML model and exit"
    )
    parser.add_argument("--config", type=Path, default=CONFIG_PATH, help="Config file path")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument(
        "--duration", type=positive_duration, help="Stop recording after N seconds"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.command == "list-devices":
        print(asyncio.run(_list_devices()))
        return 0

    if args.download_model:
        return download_model(args.download_model, args.config)

    # ── toggle: stop a running daemon ──────────────────────────────
    if _pid_alive():
        print("Stopping recording…")
        _send_sigterm()
        return 0

    # ── start recording ─────────────────────────────────────────────
    overrides: dict[str, object] = {}
    if args.device:
        audio = overrides.setdefault("audio", {})
        assert isinstance(audio, dict)
        audio["device"] = args.device
    else:
        default_src = detect_default_source()
        if default_src:
            audio = overrides.setdefault("audio", {})
            assert isinstance(audio, dict)
            audio["device"] = default_src
            logging.info("Using system microphone: %s", default_src)
    if args.model:
        model = overrides.setdefault("model", {})
        assert isinstance(model, dict)
        model["path"] = args.model

    try:
        config = load_config(args.config, overrides)
    except ConfigError as exc:
        logging.error("%s", exc)
        return 4

    return asyncio.run(run_push_to_talk(config, duration=args.duration))


# ── toggle helpers ──────────────────────────────────────────────────

def _pid_alive() -> bool:
    try:
        pid = int(PID_FILE_CLEAN.read_text().strip())
    except (FileNotFoundError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        PID_FILE_CLEAN.unlink(missing_ok=True)
        return False
    return True


def _send_sigterm() -> None:
    try:
        pid = int(PID_FILE_CLEAN.read_text().strip())
        os.kill(pid, signal.SIGTERM)
    except (FileNotFoundError, ValueError, OSError):
        pass


# ── utilities ────────────────────────────────────────────────────────

async def _list_devices() -> str:
    return format_devices(await list_audio_devices())


def download_model(size: str, config_path: Path) -> int:
    model_name = MODEL_NAMES[size]
    models_dir = Path("~/.config/asit-ia/models").expanduser()
    models_dir.mkdir(parents=True, exist_ok=True)
    target = models_dir / model_name
    if target.exists():
        print(f"Model already exists: {target}")
        update_model_path(target, config_path)
        return 0
    script = Path(__file__).resolve().parent.parent / "scripts" / "download-model.sh"
    if script.exists():
        cmd = [str(script), size]
    else:
        url = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{model_name}"
        cmd = ["curl", "-L", "--fail", "-o", str(target), url]
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        return result.returncode
    update_model_path(target, config_path)
    print(f"Downloaded {size} model to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
