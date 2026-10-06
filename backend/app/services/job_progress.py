"""Staged progress for a translation job: reading, translating, rebuilding, finishing."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Callable, Iterator, Optional

logger = logging.getLogger(__name__)

READING = "reading"
TRANSLATING = "translating"
REBUILDING = "rebuilding"
FINISHING = "finishing"

# Share of the bar per stage, roughly matching where a scanned PDF spends its time.
STAGE_WEIGHTS: dict[str, int] = {READING: 45, TRANSLATING: 10, REBUILDING: 40, FINISHING: 5}
STAGES = tuple(STAGE_WEIGHTS)
STAGE_LABELS = {
    READING: "Reading the document",
    TRANSLATING: "Translating the text",
    REBUILDING: "Rebuilding the layout",
    FINISHING: "Finishing up",
}
MAX_WHILE_PROCESSING = 99

Reporter = Callable[[str, float, Optional[str]], None]
_reporter: ContextVar[Optional[Reporter]] = ContextVar("job_progress_reporter", default=None)


def overall_percent(stage: str, fraction: float = 0.0) -> int:
    """Map a stage and the fraction done inside it to a 0-99 percent for the whole job."""
    if stage not in STAGE_WEIGHTS:
        return 0
    start = sum(STAGE_WEIGHTS[s] for s in STAGES[: STAGES.index(stage)])
    fraction = min(max(float(fraction or 0.0), 0.0), 1.0)
    return min(MAX_WHILE_PROCESSING, int(start + STAGE_WEIGHTS[stage] * fraction))


def report(stage: str, fraction: float = 0.0, detail: Optional[str] = None) -> None:
    """Tell the running job where it is; a no-op outside a job, and it never raises."""
    reporter = _reporter.get()
    if reporter is None:
        return
    try:
        reporter(stage, fraction, detail)
    except Exception:
        logger.warning("Progress report failed", exc_info=True)


@contextmanager
def bind(reporter: Reporter) -> Iterator[None]:
    token = _reporter.set(reporter)
    try:
        yield
    finally:
        _reporter.reset(token)


@contextmanager
def scope(lo: float, hi: float, detail: Optional[str] = None) -> Iterator[None]:
    """Nested reports land inside [lo, hi] of the outer stage, under `detail` when given."""
    outer = _reporter.get()
    if outer is None:
        yield
        return

    def inner(stage: str, fraction: float, inner_detail: Optional[str]) -> None:
        fraction = min(max(float(fraction or 0.0), 0.0), 1.0)
        outer(stage, lo + (hi - lo) * fraction, detail or inner_detail)

    token = _reporter.set(inner)
    try:
        yield
    finally:
        _reporter.reset(token)


class ProjectProgress:
    """Writes the stage to the project row (one commit per report) and broadcasts it."""

    def __init__(self, db, project, broadcast: Callable[[str, int, str, dict], None]):
        self.db = db
        self.project = project
        self.broadcast = broadcast

    def __call__(self, stage: str, fraction: float = 0.0, detail: Optional[str] = None) -> None:
        p = self.project
        percent = max(p.progress_percent or 0, overall_percent(stage, fraction))
        detail = detail or STAGE_LABELS.get(stage)
        if stage == p.progress_stage and detail == p.progress_detail and percent == (p.progress_percent or 0):
            return
        now = datetime.utcnow()
        if stage != p.progress_stage:
            p.stage_started_at = now
        p.progress_stage = stage
        p.progress_detail = detail
        p.progress_percent = percent
        p.last_heartbeat = now
        self.db.commit()
        self.broadcast(str(p.id), percent, "PROCESSING", {"stage": stage, "detail": detail})


def display_percent(project) -> int:
    """The percent the UI shows: 100 only once COMPLETED, never above 99 before that."""
    status = getattr(project.status, "value", project.status)
    if status == "COMPLETED":
        return 100
    if status == "PENDING":
        return 0
    return min(MAX_WHILE_PROCESSING, max(0, project.progress_percent or 0))


def stage_fields(project) -> dict:
    """The progress fields the project endpoints expose; empty stage once the job is no longer running."""
    status = getattr(project.status, "value", project.status)
    running = status == "PROCESSING"
    return {
        "progress_stage": project.progress_stage if running else None,
        "progress_detail": project.progress_detail if running else None,
        "stage_started_at": project.stage_started_at if running else None,
    }
