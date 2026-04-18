"""
aureon.agents._base — Uniform Agent ABC contract.

Every Aureon doctrine-governed agent inherits from AureonAgent.
This locks the constructor signature, the get_status() surface,
and the NotActivatedError for declared-but-dormant agents.
"""

import threading
from abc import ABC, abstractmethod


class NotActivatedError(RuntimeError):
    """Raised when a declared-but-not-activated agent method is called."""


class AureonAgent(ABC):
    """
    Base contract for all Aureon agents.

    Constructor: (aureon_state: dict, state_lock: threading.Lock)
    Required:    get_status() -> dict
    """

    def __init__(self, aureon_state: dict, state_lock: threading.Lock):
        self._state = aureon_state
        self._lock = state_lock

    @abstractmethod
    def get_status(self) -> dict:
        """Return agent operational status for dashboard and regulatory display."""
        ...
