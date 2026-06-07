"""Indicator implementations.

Importing this package imports every indicator module so their
``@register_indicator`` decorators populate the registry.
"""

from __future__ import annotations

from . import alignment  # noqa: F401
from . import blast_radius  # noqa: F401
from . import duplication  # noqa: F401
from . import grounding  # noqa: F401
from . import index_trust  # noqa: F401
from . import orphan  # noqa: F401
