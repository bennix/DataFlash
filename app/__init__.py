from pathlib import Path

from flask import Flask, send_from_directory


def create_app(test_config=None):
    instance_path = None
    if test_config and test_config.get("INSTANCE_PATH"):
        instance_path = str(test_config["INSTANCE_PATH"])
    app = Flask(
        __name__,
        static_folder="static",
        static_url_path="/static",
        instance_path=instance_path,
    )
    root = Path(app.instance_path)
    root.mkdir(parents=True, exist_ok=True)
    app.config.from_mapping(
        DATABASE=str(root / "dataflash.sqlite3"),
        CACHE_DIR=str(root / ".cache"),
        SECRET_DIR=str(Path.home() / ".dataflash"),
        AI_CALL_LIMIT=50,
        AI_MOCK=False,
    )
    if test_config:
        app.config.update(test_config)
    Path(app.config["CACHE_DIR"]).mkdir(parents=True, exist_ok=True)

    # Register nodes before API
    from . import nodes as _nodes  # noqa: F401
    from .api import api, init_app

    init_app(app)
    app.register_blueprint(api, url_prefix="/api")

    # Install bundled samples + load user custom nodes into registry
    from .custom_nodes import ensure_samples_installed, load_all_custom_nodes

    try:
        ensure_samples_installed(app.instance_path)
    except Exception:
        pass
    load_all_custom_nodes(app.instance_path)

    @app.get("/")
    def index():
        dist = Path(app.static_folder) / "dist"
        if (dist / "index.html").exists():
            return send_from_directory(dist, "index.html")
        return send_from_directory(app.static_folder, "index.html")

    return app
