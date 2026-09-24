from __future__ import annotations

from unittest.mock import patch

import pytest

from asit_ia.__main__ import build_parser
from asit_ia.injection.abc import Injector
from asit_ia.injection.clipboard import ClipboardError, ClipboardInjector
from asit_ia.injection.xtest import XtestInjector, describe_key_sequence


# ------------------------------------------------------------------
# ABC contract
# ------------------------------------------------------------------


@patch("asit_ia.injection.clipboard.shutil.which", return_value="/usr/bin/wl-copy")
def test_clipboard_injector_is_injector(_which) -> None:
    assert isinstance(ClipboardInjector(), Injector)


def test_xtest_injector_is_injector() -> None:
    assert isinstance(XtestInjector(":0", 0), Injector)


# ------------------------------------------------------------------
# Clipboard backend detection
# ------------------------------------------------------------------


def test_clipboard_detects_qdbus6_first() -> None:
    with patch("asit_ia.injection.clipboard.shutil.which") as mock_which:
        mock_which.side_effect = lambda x: f"/usr/bin/{x}" if x == "qdbus6" else None
        injector = ClipboardInjector()
        assert injector._backend == "qdbus6"


def test_clipboard_falls_back_to_wl_copy() -> None:
    with patch("asit_ia.injection.clipboard.shutil.which") as mock_which:
        mock_which.side_effect = lambda x: (
            "/usr/bin/wl-copy" if x == "wl-copy" else None
        )
        injector = ClipboardInjector()
        assert injector._backend == "wl-copy"


def test_clipboard_falls_back_to_xclip() -> None:
    with patch("asit_ia.injection.clipboard.shutil.which") as mock_which:
        mock_which.side_effect = lambda x: (
            "/usr/bin/xclip" if x == "xclip" else None
        )
        injector = ClipboardInjector()
        assert injector._backend == "xclip"


def test_clipboard_falls_back_to_xsel() -> None:
    with patch("asit_ia.injection.clipboard.shutil.which") as mock_which:
        mock_which.side_effect = lambda x: (
            "/usr/bin/xsel" if x == "xsel" else None
        )
        injector = ClipboardInjector()
        assert injector._backend == "xsel"


def test_clipboard_raises_error_when_no_backend_available() -> None:
    with patch("asit_ia.injection.clipboard.shutil.which", return_value=None):
        with pytest.raises(ClipboardError, match="No clipboard backend found"):
            ClipboardInjector()


# ------------------------------------------------------------------
# Clipboard send_text
# ------------------------------------------------------------------


def test_clipboard_send_text_klipper_qdbus6() -> None:
    with (
        patch("asit_ia.injection.clipboard.shutil.which", return_value="/usr/bin/qdbus6"),
        patch("asit_ia.injection.clipboard.subprocess.run") as mock_run,
    ):
        mock_run.return_value.returncode = 0
        injector = ClipboardInjector()
        injector.send_text("hello")

        mock_run.assert_called_once_with(
            [
                "qdbus6",
                "org.kde.klipper",
                "/klipper",
                "org.kde.klipper.klipper.setClipboardContents",
                "hello",
            ],
            capture_output=True,
            text=True,
        )


def test_clipboard_send_text_wl_copy() -> None:
    with (
        patch(
            "asit_ia.injection.clipboard.shutil.which",
            side_effect=[None, "/usr/bin/wl-copy", None, None],
        ),
        patch("asit_ia.injection.clipboard.subprocess.run") as mock_run,
    ):
        mock_run.return_value.returncode = 0
        injector = ClipboardInjector()
        injector.send_text("hello")

        mock_run.assert_called_once_with(
            ["wl-copy"], input="hello", capture_output=True, text=True
        )


def test_clipboard_send_text_raises_on_nonzero_exit() -> None:
    with (
        patch(
            "asit_ia.injection.clipboard.shutil.which",
            side_effect=[None, "/usr/bin/wl-copy", None, None],
        ),
        patch("asit_ia.injection.clipboard.subprocess.run") as mock_run,
    ):
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "permission denied"

        injector = ClipboardInjector()
        with pytest.raises(ClipboardError, match="wl-copy failed"):
            injector.send_text("hello")


# ------------------------------------------------------------------
# CLI --mode flag
# ------------------------------------------------------------------


def test_cli_default_mode_not_present_in_help() -> None:
    """Push-to-talk mode has no --mode flag — it's always clipboard."""
    args = build_parser().parse_args([])
    assert not hasattr(args, "mode")


def test_cli_help_shows_device_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--help"])
    out = capsys.readouterr().out
    assert "--device" in out
    assert "--duration" in out


def test_injection_mapping_helper_for_ascii_uppercase_and_special_keys() -> None:
    assert describe_key_sequence("a") == ("keysym", "a")
    assert describe_key_sequence("A") == ("shift", "a")
    assert describe_key_sequence("\n") == ("special", "Return")
    assert describe_key_sequence("\t") == ("special", "Tab")


def test_injection_mapping_helper_for_non_ascii_unicode() -> None:
    assert describe_key_sequence("é") == ("unicode", "U00E9")
