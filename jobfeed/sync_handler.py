"""AWS Lambda entry point for the daily sync, run by EventBridge Scheduler."""
import logging
import os

from .board import build
from .storage import S3Store

logging.getLogger().setLevel(logging.INFO)
log = logging.getLogger(__name__)


def handler(event, context):
    result = build(S3Store(os.environ["DATA_BUCKET"]))
    summary = {
        "roles": result.roles,
        "skipped_outside_uk": result.skipped,
        "kept_previous": result.kept,
        "new_logos": result.new_logos,
        "missing_logos": result.missing_logos,
    }
    log.info("Sync finished: %s", summary)
    return summary
