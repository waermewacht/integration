"""Time-weighted means. Pure Python, no Home Assistant imports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Below one minute of samples a mean says nothing.
MIN_SECONDS = 60.0


@dataclass
class Mean:
    """Mean of a value over the time a condition held (e.g. compressor heating)."""

    weighted: float = 0.0
    seconds: float = 0.0

    def add(self, value: float, seconds: float) -> None:
        if seconds > 0:
            self.weighted += value * seconds
            self.seconds += seconds

    @property
    def value(self) -> float | None:
        if self.seconds < MIN_SECONDS:
            return None
        return self.weighted / self.seconds

    def as_dict(self) -> dict[str, float]:
        return {"weighted": self.weighted, "seconds": self.seconds}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Mean:
        data = data or {}
        return cls(float(data.get("weighted", 0.0)), float(data.get("seconds", 0.0)))
