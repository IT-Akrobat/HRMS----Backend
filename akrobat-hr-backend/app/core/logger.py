import logging
import os
from logging.handlers import RotatingFileHandler

# Cloud platforms (Render, Railway, Heroku, most containers/Kubernetes) either
# have an ephemeral or read-only filesystem, or expect logs on stdout so their
# log collector can pick them up. Writing to a plain FileHandler("app.log")
# grows without bound on disk (it had reached ~19MB in this repo) and can
# crash the app entirely on a read-only filesystem. Default to stdout only;
# file logging is opt-in via env for local debugging, and rotates instead of
# growing forever.
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_TO_FILE = os.getenv("LOG_TO_FILE", "false").lower() in ("1", "true", "yes")
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", "app.log")

handlers = [logging.StreamHandler()]

if LOG_TO_FILE:
    handlers.append(
        RotatingFileHandler(
            LOG_FILE_PATH, maxBytes=5 * 1024 * 1024, backupCount=3
        )
    )

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=handlers,
)

logger = logging.getLogger("AkrobatHR")
