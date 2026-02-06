from flask import Flask
from src.config import settings
from src.infrastructure.logging import configure_logging
from src.infrastructure.database import Session


def create_app():
    # 1. Configure logging first
    configure_logging()

    # 2. Initialize Flask
    app = Flask(__name__)

    # 3. Register Teardown
    @app.teardown_appcontext
    def shutdown_session(exception=None):
        Session.remove()

    # 4. Register Blueprints
    from src.api.health import health_bp
    app.register_blueprint(health_bp)

    return app
