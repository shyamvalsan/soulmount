"""Daemon REST control and brain connection, with mocked HTTP."""

from __future__ import annotations

import json

import httpx
import respx

from soulmount_body.brain import BrainConnection
from soulmount_body.robot import RobotControl

DAEMON = "http://daemon.test"
BRAIN = "http://brain.test"


@respx.mock
async def test_set_volume_clamps_and_posts_shape():
    route = respx.post(f"{DAEMON}/api/volume/set").mock(return_value=httpx.Response(200))
    r = RobotControl(DAEMON)
    assert await r.set_volume(200) is True          # clamped to 100
    assert json.loads(route.calls[0].request.content) == {"volume": 100}
    await r.aclose()


@respx.mock
async def test_play_emotion_keeps_dataset_slash():
    route = respx.post(
        f"{DAEMON}/api/move/play/recorded-move-dataset/pollen-robotics/reachy-mini-emotions-library/curious1"
    ).mock(return_value=httpx.Response(200))
    r = RobotControl(DAEMON)
    assert await r.play_emotion("curious1") is True
    assert route.called
    await r.aclose()


@respx.mock
async def test_wake_sleep_and_current_app():
    respx.post(f"{DAEMON}/api/move/play/wake_up").mock(return_value=httpx.Response(200))
    respx.post(f"{DAEMON}/api/move/play/goto_sleep").mock(return_value=httpx.Response(200))
    respx.get(f"{DAEMON}/api/apps/current-app-status").mock(return_value=httpx.Response(200, json=None))
    r = RobotControl(DAEMON)
    assert await r.wake_up() is True
    assert await r.sleep_pose() is True
    assert await r.current_app() is None
    await r.aclose()


@respx.mock
async def test_robot_down_returns_false_not_raise():
    respx.post(f"{DAEMON}/api/move/play/wake_up").mock(side_effect=httpx.ConnectError("down"))
    r = RobotControl(DAEMON)
    assert await r.wake_up() is False   # never raises into the app
    await r.aclose()


@respx.mock
async def test_brain_health_identity_house():
    respx.get(f"{BRAIN}/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    respx.get(f"{BRAIN}/v1/identity").mock(return_value=httpx.Response(200, json={"instructions": "I am small."}))
    respx.get(f"{BRAIN}/v1/house").mock(return_value=httpx.Response(200, json={"volume_ceiling": 55}))
    b = BrainConnection(BRAIN, {"Authorization": "Bearer k"})
    assert await b.is_healthy() is True
    assert await b.identity() == "I am small."
    assert (await b.house())["volume_ceiling"] == 55
    await b.aclose()


@respx.mock
async def test_brain_chat_asleep_payload():
    respx.post(f"{BRAIN}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"asleep": True, "reason": "daily", "wake_at": "x"})
    )
    b = BrainConnection(BRAIN, {})
    out = await b.chat("voice", [{"role": "user", "content": "hi"}])
    assert out["asleep"] is True
    await b.aclose()


@respx.mock
async def test_brain_down_health_is_false():
    respx.get(f"{BRAIN}/health").mock(side_effect=httpx.ConnectError("down"))
    b = BrainConnection(BRAIN, {})
    assert await b.is_healthy() is False
    await b.aclose()
