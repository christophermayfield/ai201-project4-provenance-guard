"""Shared Flask extensions.

Kept in its own module so route modules can import the limiter and apply
per-route limits without a circular import on the app factory.
"""

from __future__ import annotations

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Per-IP limiter. No global default limits; limits are applied per route.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",
)
