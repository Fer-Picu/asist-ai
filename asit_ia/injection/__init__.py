"""Text injection backends."""

from asit_ia.injection.abc import Injector
from asit_ia.injection.clipboard import ClipboardError, ClipboardInjector

__all__ = [
    "ClipboardError",
    "ClipboardInjector",
    "Injector",
]
