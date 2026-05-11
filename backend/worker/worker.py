"""Compatibility shim — the canonical worker is `app.workers.sqs_worker`.

The audit (ship-stopper #5) flagged two divergent worker implementations
(`worker/worker.py` and `app/workers/sqs_worker.py`) that behaved
differently. The `app/workers` version is the one wired to the canonical
`app/services/translation_processor.py` (layout-preserving rebuild,
glossary usage counting, watchdog heartbeats, etc.) — so we delegate
everything to it.

`python -m worker.worker` is preserved as an entrypoint so Docker
images and existing process managers don't break.
"""
import logging

from app.workers.sqs_worker import start_worker as _real_start


logger = logging.getLogger(__name__)


def main():
    logger.info(
        "worker/worker.py shim → delegating to app.workers.sqs_worker.start_worker"
    )
    return _real_start()


if __name__ == "__main__":
    main()
