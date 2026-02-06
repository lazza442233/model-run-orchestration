import structlog
import logging
import logging.config
import sys
from src.config import settings


def configure_logging():
    log_level = settings.LOG_LEVEL.upper()

    # Configure standard logging to sink to stdout
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "plain": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processors": [
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.dev.ConsoleRenderer(colors=True),
                ],
            },
            "json": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processors": [
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.JSONRenderer(),
                ],
            },
        },
        "handlers": {
            "default": {
                "level": log_level,
                "class": "logging.StreamHandler",
                "formatter": "json",  # Default to JSON for prod-like, can make conditional later
            },
            "console": {
                "level": log_level,
                "class": "logging.StreamHandler",
                "formatter": "plain",
            }
        },
        "loggers": {
            "": {
                "handlers": ["console"],  # Use console for Phase 0
                "level": log_level,
                "propagate": True,
            },
        }
    })

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
