from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta

from backend.config import Settings

logger = logging.getLogger(__name__)


class Scheduler:
    """Controls when the worker processes images based on a daily time window.

    When enabled, the worker is paused outside the schedule window and resumed
    (with an auto-scan) when the window opens.  When disabled, the worker runs
    normally.
    """

    def __init__(
        self,
        settings: Settings,
        worker,           # backend.worker.WorkerQueue — avoid circular import
        watcher,          # backend.watcher.FileWatcher
    ) -> None:
        self.settings = settings
        self.worker = worker
        self.watcher = watcher
        self._running = False
        self._task: asyncio.Task | None = None
        # None = first check (apply correct state immediately on startup)
        self._was_in_window: bool | None = None

    async def start(self) -> None:
        """Start the scheduler loop."""
        if self._running:
            return
        self._running = True
        self._was_in_window = None
        self._task = asyncio.create_task(self._loop())
        logger.info("Scheduler started")

    async def stop(self) -> None:
        """Stop the scheduler and ensure worker is unpaused."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # Always resume worker on shutdown so it can drain gracefully
        if self.worker.is_paused:
            self.worker.resume()
        logger.info("Scheduler stopped")

    async def _loop(self) -> None:
        """Main loop — checks the schedule every 30 seconds."""
        while self._running:
            try:
                self._tick()
            except Exception:
                logger.error("Scheduler tick error", exc_info=True)
            await asyncio.sleep(30)

    def _tick(self) -> None:
        """Single schedule check — called every 30s."""
        if not self.settings.schedule_enabled:
            # Schedule disabled — ensure worker is running
            if self.worker.is_paused:
                logger.info("Schedule disabled — resuming worker")
                self.worker.resume()
            self._was_in_window = None
            return

        in_window = self._is_in_window()

        if in_window and self._was_in_window is not True:
            # Entering window (or first check during window)
            logger.info(
                "Schedule window opened (%s–%s) — resuming worker and triggering scan",
                self.settings.schedule_start, self.settings.schedule_end,
            )
            self.worker.resume()
            # Trigger a scan to pick up any new files
            asyncio.create_task(self._auto_scan())
        elif not in_window and self._was_in_window is not False:
            # Leaving window (or first check outside window)
            logger.info(
                "Schedule window closed (%s–%s) — pausing worker",
                self.settings.schedule_start, self.settings.schedule_end,
            )
            self.worker.pause()

        self._was_in_window = in_window

    async def _auto_scan(self) -> None:
        """Trigger a scan when the schedule window opens."""
        try:
            new_count, skipped, _ = await self.watcher.scan_once()
            if new_count > 0:
                logger.info("Schedule auto-scan found %d new images (%d skipped)", new_count, skipped)
        except Exception:
            logger.error("Schedule auto-scan failed", exc_info=True)

    # -- Time window logic ---------------------------------------------------

    def _is_in_window(self) -> bool:
        """Check if current time is within the schedule window."""
        now = datetime.now().time()
        start = self._parse_time(self.settings.schedule_start)
        end = self._parse_time(self.settings.schedule_end)

        if start == end:
            # Same start and end = always active (24h window)
            return True
        elif start < end:
            # Same-day window (e.g. 09:00–17:00)
            return start <= now < end
        else:
            # Crosses midnight (e.g. 22:00–06:00)
            return now >= start or now < end

    @staticmethod
    def _parse_time(hhmm: str) -> time:
        """Parse HH:MM string to a time object."""
        try:
            parts = hhmm.strip().split(":")
            return time(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            return time(0, 0)

    # -- Status for API / dashboard ------------------------------------------

    def get_status(self) -> dict:
        """Return schedule status dict for the dashboard API."""
        if not self.settings.schedule_enabled:
            return {"enabled": False}

        in_window = self._is_in_window()
        return {
            "enabled": True,
            "start": self.settings.schedule_start,
            "end": self.settings.schedule_end,
            "in_window": in_window,
            "next_change": self._next_transition_desc(in_window),
        }

    def _next_transition_desc(self, in_window: bool) -> str:
        """Human-readable description of the next state change."""
        now = datetime.now()
        start = self._parse_time(self.settings.schedule_start)
        end = self._parse_time(self.settings.schedule_end)

        if in_window:
            # Currently active — next change is when window closes
            target = end
            label = "pauses"
        else:
            # Currently paused — next change is when window opens
            target = start
            label = "resumes"

        # Build target datetime (today or tomorrow)
        target_dt = now.replace(
            hour=target.hour, minute=target.minute, second=0, microsecond=0
        )
        if target_dt <= now:
            target_dt += timedelta(days=1)

        delta = target_dt - now
        total_minutes = int(delta.total_seconds() // 60)
        hours, minutes = divmod(total_minutes, 60)

        if hours > 0:
            return f"{label} in {hours}h {minutes}m"
        return f"{label} in {minutes}m"
