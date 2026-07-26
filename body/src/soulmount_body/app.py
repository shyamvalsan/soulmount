"""SoulmountApp — the reachy_mini body app (SPEC Phase 3, minimal-diff fork).

Runs under the daemon (one app at a time). The daemon hands us a connected
ReachyMini instance and a stop_event, sends SIGINT to stop, and re-homes after.
We drive rituals/motion through the daemon's own REST (verified shapes, FACTS §1.2).

Enumerated diff vs upstream lives in body/DIFF.md. The actual conversation turn is
handled by the voice backend (Phase 2 seam); everything else here is real:
startup ritual, brain-down droop/retry, sleep-state handling, house enforcement,
instant-ack, graceful stop.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading

from .brain import BrainConnection
from .config import BodyConfig, load_config
from .house import HouseRules
from .robot import RobotControl
from .state import sleep_info
from .voice import make_voice_backend

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx/httpcore INFO logs the full request URL (incl. any Bearer/token) — keep it quiet.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class _RedactingFilter(logging.Filter):
    """Belt-and-suspenders: the body holds the BRAIN_API_KEY bearer — never log it."""

    _RE = re.compile(r"(Bearer\s+[A-Za-z0-9._-]{16,}|[0-9a-fA-F]{48,}|sk-[A-Za-z0-9-]{20,})")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._RE.sub("***REDACTED***", record.msg)
        return True


for _h in logging.getLogger().handlers:
    _h.addFilter(_RedactingFilter())
log = logging.getLogger("soulmount.body")

try:  # Only importable on the robot / SDK venv; tests target the other modules.
    from reachy_mini.apps.app import ReachyMiniApp as _Base
except Exception:  # pragma: no cover - exercised only off-robot
    _Base = object


class SoulmountApp(_Base):
    def __init__(self) -> None:
        super().__init__()  # let the base (ReachyMiniApp) initialise its own state
        self.stop_event = threading.Event()

    # The daemon calls run() with a connected instance + stop_event.
    def run(self, reachy_mini=None, stop_event: threading.Event | None = None) -> None:
        if stop_event is not None:
            self.stop_event = stop_event
        self.reachy_mini = reachy_mini  # SDK instance for audio (voice backend); None off-robot
        asyncio.run(self._arun())

    def stop(self) -> None:
        self.stop_event.set()

    def _stopping(self) -> bool:
        return self.stop_event.is_set()

    async def _sleep_interruptible(self, seconds: float) -> None:
        """Sleep in small slices so stop_event is honoured promptly."""
        end = seconds
        while end > 0 and not self._stopping():
            await asyncio.sleep(min(0.25, end))
            end -= 0.25

    async def _arun(self) -> None:
        cfg = load_config()
        robot = RobotControl(cfg.daemon_url)
        brain = BrainConnection(cfg.brain_base_url, cfg.auth_header)
        voice = make_voice_backend(cfg.voice_backend, cfg, reachy_mini=getattr(self, "reachy_mini", None))
        house = HouseRules()  # replaced once the brain answers
        try:
            house = await self._startup_ritual(cfg, robot, brain, voice)
            if not self._stopping():
                await self._main_loop(cfg, robot, brain, voice, house)
        finally:
            await voice.stop()
            await robot.aclose()
            await brain.aclose()
            log.info("soulmount body app stopped")

    async def _startup_ritual(self, cfg, robot, brain, voice) -> HouseRules:
        """Phase 3 item 2. Ready = healthy AND identity+house obtained (so a bad/missing
        BRAIN_API_KEY can't silently yield default house rules + empty persona). Ready +
        awake → wake + greeting; ready + asleep → sleep pose; not ready → droop + retry."""
        from datetime import datetime

        drooped = False
        while not self._stopping():
            health = await brain.health()
            ready = bool(health and health.get("status") == "ok")
            house_data = await brain.house() if ready else None
            identity = await brain.identity() if ready else None

            if ready and house_data is not None and identity is not None:
                house = HouseRules.from_dict(house_data)
                quiet = house.in_quiet_hours(datetime.now().astimezone())
                await voice.start(identity)
                asleep, wake_at = sleep_info(health)
                if asleep:  # budget-capped at boot → goodnight path, not a greeting (§7.7)
                    log.info("brain asleep at startup (until %s) — sleep pose", wake_at)
                    if not quiet:
                        await robot.play_emotion("sleep1")
                    await robot.sleep_pose()
                    voice.pause()
                elif not quiet:
                    await robot.wake_up()
                    vol = await robot.get_volume()  # keep volume under the ceiling first
                    if vol is not None:
                        await robot.set_volume(house.clamp_volume(vol))
                    await voice.speak(cfg.greeting)
                    log.info("greeting played")
                else:
                    log.info("quiet hours at startup — staying still, no greeting")
                return house

            # Not ready: brain down OR healthy-but-identity/house-unavailable (bad key /
            # misconfig). Droop + retry — never proceed silently with defaults.
            if not drooped:
                if ready:
                    log.error("brain healthy but identity/house unavailable (auth failure? "
                              "misconfig) — drooping and retrying, NOT proceeding with defaults")
                else:
                    log.warning("brain unreachable at startup — droop + retry")
                if not HouseRules().in_quiet_hours(datetime.now().astimezone()):
                    await robot.droop()  # no motion sounds during quiet hours (guardrail 9)
                drooped = True
            await self._sleep_interruptible(cfg.retry_interval_s)
        return HouseRules()

    async def _main_loop(self, cfg, robot, brain, voice, house) -> None:
        from datetime import datetime

        was_asleep = False
        was_down = False
        while not self._stopping():
            health = await brain.health()
            quiet = house.in_quiet_hours(datetime.now().astimezone())

            # Brain unreachable mid-session → droop + pause (not silently "awake"),
            # and refresh identity/house when it returns (Phase 3 item 2 auto-recovery).
            if health is None:
                if not was_down:
                    log.warning("brain unreachable mid-session — antenna droop, pausing")
                    if not quiet:
                        await robot.droop()
                    voice.pause()
                    was_down = True
                await self._sleep_interruptible(cfg.retry_interval_s)
                continue
            if was_down:
                # Re-assert the startup invariant: only resume when BOTH identity and
                # house are obtained, else stay drooped (don't run on a stale/empty
                # persona or default house rules after e.g. a key rotation).
                refreshed = await brain.house()
                new_identity = await brain.identity()
                if refreshed is None or new_identity is None:
                    await self._sleep_interruptible(cfg.retry_interval_s)
                    continue
                log.info("brain reachable again — refreshed identity/house")
                house = HouseRules.from_dict(refreshed)
                await voice.start(new_identity)
                if not quiet:
                    await robot.wake_up()
                voice.resume()
                was_down = False
                was_asleep = False

            asleep, wake_at = sleep_info(health)

            if asleep and not was_asleep:
                # Zero-token goodnight. The wind-down emotion can make motion sounds,
                # so during quiet hours we take the sleep pose silently (guardrail 9).
                log.info("brain asleep until %s — goodnight pose, pausing", wake_at)
                if not quiet:
                    await robot.play_emotion("sleep1")
                await robot.sleep_pose()
                voice.pause()
                was_asleep = True
            elif not asleep and was_asleep:
                # A daily-cap wake is at local midnight — inside quiet hours — so the
                # visible stretch is suppressed; we just resume listening silently.
                log.info("brain awake again%s", "" if quiet else " — stretching")
                if not quiet:
                    await robot.wake_up()
                voice.resume()
                was_asleep = False

            if not asleep:
                # House enforcement: silence during quiet hours; clamp volume.
                if house.in_quiet_hours(datetime.now().astimezone()):
                    voice.pause()
                else:
                    voice.resume()
                    vol = await robot.get_volume()
                    if vol is not None and vol > house.volume_ceiling:
                        await robot.set_volume(house.volume_ceiling)

            await self._sleep_interruptible(cfg.health_poll_s)


def main() -> None:
    app = SoulmountApp()
    try:
        # On the robot the daemon drives run(); this is the dev/direct entry.
        wrapped = getattr(app, "wrapped_run", None)
        if callable(wrapped):
            wrapped()
        else:
            app.run()
    except KeyboardInterrupt:
        app.stop()


if __name__ == "__main__":
    main()
