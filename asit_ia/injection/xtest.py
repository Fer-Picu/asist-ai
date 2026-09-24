from __future__ import annotations

import ctypes
import contextlib
import logging
import os
import time
from ctypes import c_char_p, c_int, c_uint, c_ulong, c_void_p

from asit_ia.injection.abc import Injector

log = logging.getLogger(__name__)


class XTestError(RuntimeError):
    """Critical XTEST error; daemon should exit with code 3."""


_SHIFT_CHARS = {
    "A": "a", "B": "b", "C": "c", "D": "d", "E": "e", "F": "f", "G": "g", "H": "h", "I": "i", "J": "j",
    "K": "k", "L": "l", "M": "m", "N": "n", "O": "o", "P": "p", "Q": "q", "R": "r", "S": "s", "T": "t",
    "U": "u", "V": "v", "W": "w", "X": "x", "Y": "y", "Z": "z", "!": "1", "@": "2", "#": "3", "$": "4",
    "%": "5", "^": "6", "&": "7", "*": "8", "(": "9", ")": "0", "_": "-", "+": "=", "{": "[", "}": "]",
    "|": "\\", ":": ";", '"': "'", "<": ",", ">": ".", "?": "/", "~": "`",
}
_SPECIAL_KEYSYMS = {"\n": "Return", "\t": "Tab", " ": "space"}


def describe_key_sequence(char: str) -> tuple[str, str]:
    """Return the non-hardware key mapping strategy for a single character."""
    if len(char) != 1:
        raise ValueError("expected exactly one character")
    if char in _SPECIAL_KEYSYMS:
        return ("special", _SPECIAL_KEYSYMS[char])
    if char in _SHIFT_CHARS:
        return ("shift", _SHIFT_CHARS[char])
    if ord(char) < 128:
        return ("keysym", char)
    return ("unicode", f"U{ord(char):04X}")


class XtestInjector(Injector):
    def __init__(self, display: str = ":0", typing_speed_ms: int = 0) -> None:
        self.display_name = display
        self.typing_speed = typing_speed_ms / 1000
        self.display: c_void_p | None = None
        self._x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
        self._xtst = ctypes.cdll.LoadLibrary("libXtst.so.6")
        self._configure_signatures()
        self._held_modifiers: set[int] = set()
        self._modifier_cache: set[int] | None = None

    def _configure_signatures(self) -> None:
        self._x11.XOpenDisplay.argtypes = [c_char_p]
        self._x11.XOpenDisplay.restype = c_void_p
        self._x11.XCloseDisplay.argtypes = [c_void_p]
        self._x11.XFlush.argtypes = [c_void_p]
        self._x11.XStringToKeysym.argtypes = [c_char_p]
        self._x11.XStringToKeysym.restype = c_ulong
        self._x11.XKeysymToKeycode.argtypes = [c_void_p, c_ulong]
        self._x11.XKeysymToKeycode.restype = c_uint
        self._xtst.XTestFakeKeyEvent.argtypes = [c_void_p, c_uint, c_int, c_ulong]
        self._xtst.XTestFakeKeyEvent.restype = c_int

    def detect_display(self) -> bool:
        try:
            self._open()
            return True
        except XTestError:
            return False

    def send_text(self, text: str) -> None:
        self._open()
        try:
            for char in text:
                self._send_char(char)
                if self.typing_speed:
                    time.sleep(self.typing_speed)
            self._cleanup_modifiers()
            self._x11.XFlush(self.display)
        except Exception:
            self._cleanup_modifiers()
            self._x11.XFlush(self.display)
            raise

    def close(self) -> None:
        if self.display:
            self._cleanup_modifiers()
            self._x11.XCloseDisplay(self.display)
            self.display = None

    def _open(self) -> None:
        if self.display:
            return
        os.environ["DISPLAY"] = self.display_name
        display = self._x11.XOpenDisplay(self.display_name.encode())
        if not display:
            raise XTestError("XTEST requires XWayland. DISPLAY=:0 not available.")
        self.display = display

    def _send_char(self, char: str) -> None:
        strategy, value = describe_key_sequence(char)
        if strategy == "special":
            self._tap_keysym_name(value)
            return
        if strategy == "shift":
            self._with_shift(lambda: self._tap_keysym_name(value))
            return
        if strategy == "keysym":
            self._tap_keysym_name(value)
            return
        if not self._tap_unicode_keysym(char):
            self._unicode_input_fallback(char)

    def _tap_unicode_keysym(self, char: str) -> bool:
        keysym = self._x11.XStringToKeysym(f"U{ord(char):04X}".encode())
        keycode = self._keysym_to_keycode(keysym)
        if keycode == 0:
            return False
        self._tap_keycode(keycode)
        return True

    def _unicode_input_fallback(self, char: str) -> None:
        # Linux Unicode input: Ctrl+Shift+u, hex codepoint, Enter. This keeps non-ASCII working
        # when the active layout does not expose a direct keysym/keycode.
        ctrl = self._keycode("Control_L")
        shift = self._keycode("Shift_L")
        self._press(ctrl)
        self._press(shift)
        self._tap_keysym_name("u")
        self._release(shift)
        self._release(ctrl)
        for digit in f"{ord(char):x}":
            self._tap_keysym_name(digit)
        self._tap_keysym_name("Return")

    def _with_shift(self, action) -> None:
        shift = self._keycode("Shift_L")
        self._press(shift)
        action()
        self._release(shift)

    def _tap_keysym_name(self, name: str) -> None:
        self._tap_keycode(self._keycode(name))

    def _keycode(self, name: str) -> int:
        keysym = self._x11.XStringToKeysym(name.encode())
        keycode = self._keysym_to_keycode(keysym)
        if not keycode:
            raise XTestError(f"No keycode found for keysym {name!r}")
        return keycode

    def _keysym_to_keycode(self, keysym: int) -> int:
        if not self.display or keysym == 0:
            return 0
        return int(self._x11.XKeysymToKeycode(self.display, keysym))

    def _tap_keycode(self, keycode: int) -> None:
        self._press(keycode)
        self._release(keycode)

    def _press(self, keycode: int) -> None:
        self._fake_key(keycode, True)
        self._held_modifiers.add(keycode) if keycode in self._modifier_keycodes() else None

    def _release(self, keycode: int) -> None:
        self._fake_key(keycode, False)
        self._held_modifiers.discard(keycode)

    def _fake_key(self, keycode: int, pressed: bool) -> None:
        self._open()
        if self._xtst.XTestFakeKeyEvent(self.display, keycode, 1 if pressed else 0, 0) == 0:
            self._reconnect_once()
            if self._xtst.XTestFakeKeyEvent(self.display, keycode, 1 if pressed else 0, 0) == 0:
                raise XTestError("XTestFakeKeyEvent failed after reconnect")

    def _reconnect_once(self) -> None:
        log.warning("X11 connection failed; reconnecting once")
        if self.display:
            self._x11.XCloseDisplay(self.display)
        self.display = None
        self._open()

    def _modifier_keycodes(self) -> set[int]:
        if self._modifier_cache is not None:
            return self._modifier_cache
        keycodes: set[int] = set()
        for name in ("Shift_L", "Control_L", "ISO_Level3_Shift", "Mode_switch"):
            with contextlib.suppress(XTestError):
                keycodes.add(self._keycode(name))
        self._modifier_cache = keycodes
        return keycodes

    def _cleanup_modifiers(self) -> None:
        for keycode in list(self._held_modifiers):
            with contextlib.suppress(Exception):
                self._xtst.XTestFakeKeyEvent(self.display, keycode, 0, 0)
            self._held_modifiers.discard(keycode)
