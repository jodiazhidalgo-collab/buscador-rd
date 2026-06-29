#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os

from flask import Flask, render_template

from api.btdigg_rd.routes import bp as btdigg_bp
from api.btdigg_rd.config import ensure_runtime_dirs


def create_app() -> Flask:
    ensure_runtime_dirs()
    app = Flask(
        __name__,
        template_folder="web/templates",
        static_folder="web/static",
    )
    app.register_blueprint(btdigg_bp)

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/favicon.ico")
    def favicon() -> tuple[str, int]:
        return "", 204

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9007"))
    app.run(host="0.0.0.0", port=port, threaded=True)
