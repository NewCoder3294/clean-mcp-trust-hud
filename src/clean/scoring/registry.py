"""Indicator registry.

Adding a new indicator is a one-file change: write a subclass of
``Indicator`` in ``scoring/indicators/`` and decorate it with
``@register_indicator``. ``indicators/__init__.py`` imports every module so
the decorators fire on package import.
"""

from __future__ import annotations

from typing import Callable

from .base import Indicator

_REGISTRY: dict[str, Callable[[], Indicator]] = {}


def register_indicator(factory: Callable[[], Indicator]) -> Callable[[], Indicator]:
    """Class decorator: register an ``Indicator`` subclass by its ``key``."""
    instance = factory()  # construct once to read .key
    if not instance.key:
        raise ValueError(f"Indicator {factory!r} has no key")
    _REGISTRY[instance.key] = factory
    return factory


class IndicatorRegistry:
    """Builds the set of enabled indicators from config."""

    def __init__(
        self, factories: dict[str, Callable[[], Indicator]] | None = None
    ) -> None:
        # Import for side effects so the default registry is populated.
        from . import indicators as _indicators  # noqa: F401

        self._factories = factories if factories is not None else _REGISTRY

    def available(self) -> list[str]:
        """All registered indicator keys."""
        return list(self._factories)

    def build_enabled(self, enabled_keys: list[str] | None) -> list[Indicator]:
        """Instantiate enabled indicators, preserving the requested order.

        ``None`` or an empty list means "all registered indicators".
        Unknown keys are silently skipped so a typo never crashes scoring.
        """
        keys = enabled_keys or list(self._factories)
        out: list[Indicator] = []
        for key in keys:
            factory = self._factories.get(key)
            if factory is not None:
                out.append(factory())
        return out
