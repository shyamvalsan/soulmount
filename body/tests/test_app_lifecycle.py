"""Body startup-ritual behaviour (SPEC Phase 3 item 2) — the readiness gate, quiet-hours
suppression, and asleep-at-boot. Drives SoulmountApp._startup_ritual with fakes; no SDK,
no robot, no network."""

from __future__ import annotations

from soulmount_body.app import SoulmountApp
from soulmount_body.config import BodyConfig

# quiet_start == quiet_end → never quiet; (00:00, 23:59) → effectively always quiet.
HOUSE_AWAKE = {"quiet_start": "00:00", "quiet_end": "00:00", "volume_ceiling": 60,
               "camera_capture": "on-request-only"}
HOUSE_QUIET = {"quiet_start": "00:00", "quiet_end": "23:59", "volume_ceiling": 60,
               "camera_capture": "on-request-only"}


class FakeRobot:
    def __init__(self):
        self.calls: list = []

    async def wake_up(self):
        self.calls.append("wake_up"); return True

    async def droop(self):
        self.calls.append("droop"); return True

    async def sleep_pose(self):
        self.calls.append("sleep_pose"); return True

    async def play_emotion(self, m):
        self.calls.append(("emotion", m)); return True

    async def get_volume(self):
        return 100

    async def set_volume(self, v):
        self.calls.append(("set_volume", v)); return True

    async def aclose(self):
        pass


class FakeVoice:
    def __init__(self):
        self.events: list = []

    async def start(self, identity):
        self.events.append(("start", identity))

    async def stop(self):
        pass

    async def speak(self, text):
        self.events.append(("speak", text))

    def pause(self):
        self.events.append("pause")

    def resume(self):
        self.events.append("resume")


class FakeBrain:
    def __init__(self, health, house, identity, on_identity=None):
        self._health, self._house, self._identity = health, house, identity
        self._on_identity = on_identity

    async def is_healthy(self):
        return bool(self._health and self._health.get("status") == "ok")

    async def health(self):
        return self._health

    async def house(self):
        return self._house

    async def identity(self, slim=False):
        if self._on_identity:
            self._on_identity()
        return self._identity


def _app():
    app = SoulmountApp()
    return app, FakeRobot(), FakeVoice()


async def test_ready_awake_wakes_and_greets():
    app, robot, voice = _app()
    brain = FakeBrain({"status": "ok", "budget": {"state": "awake"}}, HOUSE_AWAKE, "I am small.")
    house = await app._startup_ritual(BodyConfig(greeting="hi there"), robot, brain, voice)
    assert ("start", "I am small.") in voice.events
    assert ("speak", "hi there") in voice.events
    assert "wake_up" in robot.calls
    assert house.volume_ceiling == 60


async def test_ready_quiet_hours_no_greeting_no_motion():
    app, robot, voice = _app()
    brain = FakeBrain({"status": "ok", "budget": {"state": "awake"}}, HOUSE_QUIET, "I am small.")
    await app._startup_ritual(BodyConfig(greeting="hi"), robot, brain, voice)
    assert any(e[0] == "start" for e in voice.events)      # identity still injected
    assert not any(e[0] == "speak" for e in voice.events)  # but no greeting
    assert "wake_up" not in robot.calls                    # and no motion


async def test_ready_but_asleep_takes_sleep_pose_not_greeting():
    app, robot, voice = _app()
    brain = FakeBrain({"status": "ok", "budget": {"state": "asleep", "wake_at": "x"}}, HOUSE_AWAKE, "I am small.")
    await app._startup_ritual(BodyConfig(), robot, brain, voice)
    assert "sleep_pose" in robot.calls
    assert not any(e[0] == "speak" for e in voice.events)


async def test_healthy_but_identity_unavailable_does_not_proceed():
    # Bad/missing key: /health ok but /v1/identity 401→None → must NOT run with defaults.
    app, robot, voice = _app()
    brain = FakeBrain({"status": "ok", "budget": {"state": "awake"}}, HOUSE_AWAKE, None,
                      on_identity=lambda: app.stop_event.set())  # stop after one probe
    await app._startup_ritual(BodyConfig(), robot, brain, voice)
    assert not any(e[0] == "start" for e in voice.events)   # never proceeded
    assert not any(e[0] == "speak" for e in voice.events)
