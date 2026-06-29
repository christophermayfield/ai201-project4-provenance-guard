"""Provenance Guard application factory."""

from __future__ import annotations

from flask import Flask, jsonify

from .api import ApiError, _error_payload, bp, root_bp
from .extensions import limiter


def create_app() -> Flask:
    app = Flask(__name__)
    limiter.init_app(app)

    app.register_blueprint(bp)
    app.register_blueprint(root_bp)
    _register_error_handlers(app)
    return app


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return jsonify(_error_payload(err.code, err.message)), err.status

    @app.errorhandler(404)
    def handle_404(_err):
        return jsonify(_error_payload("not_found", "Resource not found.")), 404

    @app.errorhandler(429)
    def handle_429(_err):
        return jsonify(_error_payload("rate_limited", "Rate limit exceeded.")), 429

    @app.errorhandler(500)
    def handle_500(_err):
        return jsonify(_error_payload("internal_error", "Unexpected server error.")), 500
