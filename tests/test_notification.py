from __future__ import annotations

from unittest.mock import patch

from pathlib import Path

from asit_ia.notification import notify_ready


def test_notify_ready_skips_missing_backends() -> None:
    with (
        patch("asit_ia.notification.shutil.which", return_value=None),
        patch("asit_ia.notification.subprocess.Popen") as mock_popen,
        patch("asit_ia.notification.subprocess.run") as mock_run,
    ):
        notify_ready()

    mock_popen.assert_not_called()
    mock_run.assert_not_called()


def test_notify_ready_uses_notify_send_best_effort() -> None:
    sound_path = Path("/tmp/ready.oga")

    with (
        patch(
            "asit_ia.notification.shutil.which",
            side_effect=lambda name: f"/usr/bin/{name}"
            if name in {"notify-send", "paplay"}
            else None,
        ),
        patch(
            "asit_ia.notification._READY_SOUND_CANDIDATES",
            (sound_path,),
        ),
        patch.object(Path, "exists", return_value=True),
        patch("asit_ia.notification.subprocess.run") as mock_run,
        patch("asit_ia.notification.subprocess.Popen") as mock_popen,
    ):
        notify_ready()

    assert mock_run.call_args.args[0] == [
        "notify-send",
        "--app-name=asit-ia",
        "--urgency=normal",
        "--expire-time=2000",
        "asit-ia 🙂",
    ]
    assert mock_run.call_args.kwargs == {
        "check": False,
        "stdout": -3,
        "stderr": -3,
        "timeout": 1,
    }
    assert mock_popen.call_args_list[0].args[0] == [
        "paplay",
        "--volume=12000",
        str(sound_path),
    ]
    assert mock_popen.call_args_list[0].kwargs == {
        "stdout": -3,
        "stderr": -3,
    }


def test_notify_ready_logs_notify_send_failure() -> None:
    with (
        patch(
            "asit_ia.notification.shutil.which",
            side_effect=lambda name: f"/usr/bin/{name}" if name == "notify-send" else None,
        ),
        patch(
            "asit_ia.notification.subprocess.run",
            side_effect=OSError("dbus unavailable"),
        ),
        patch("asit_ia.notification.log") as mock_log,
    ):
        notify_ready()

    mock_log.warning.assert_called_once()
