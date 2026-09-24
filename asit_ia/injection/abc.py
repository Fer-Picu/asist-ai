from __future__ import annotations

from abc import ABC, abstractmethod


class Injector(ABC):
    """Abstract base protocol for text injectors.

    Both XtestInjector and ClipboardInjector implement this contract,
    allowing MainLoop to switch between backends polymorphically.
    """

    @abstractmethod
    def send_text(self, text: str) -> None:
        """Inject *text* into the system (clipboard or keystroke)."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Release any held resources."""
        ...

    @abstractmethod
    def detect_display(self) -> bool:
        """Return True when the injector can deliver output.

        For XtestInjector this checks whether an X display is available.
        For ClipboardInjector this always returns True.
        """
        ...
