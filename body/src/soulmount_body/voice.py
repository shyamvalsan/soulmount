"""Voice backend abstraction (SPEC Phase 2/3).

The upstream conversation app is now Hugging-Face-realtime-ONLY (FACTS §3). Putting
the Grok brain behind the voice loop is the Phase 2 bake-off decision:
  - local:    HF `speech-to-speech` cascade (VAD→STT→LLM→TTS) pointed at the brain
              via --responses_api_base_url, exposed as an OpenAI-Realtime WS.
  - realtime: the hosted HF/OpenAI realtime endpoint (+ optional ask_brain tool).

Both need infrastructure and a family voice choice that this overnight run can't
settle, so both are NullVoiceBackend for now: the app's lifecycle, rituals, sleep
handling and house enforcement are real and testable; the conversation turn is the
documented seam wired in the morning. See body/DIFF.md.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

log = logging.getLogger("soulmount.body.voice")


class VoiceBackend(ABC):
    @abstractmethod
    async def start(self, identity: str | None) -> None: ...
    @abstractmethod
    async def stop(self) -> None: ...
    @abstractmethod
    async def speak(self, text: str) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...


class NullVoiceBackend(VoiceBackend):
    """No-op backend: keeps the lifecycle runnable before the Phase 2 wiring."""

    def __init__(self, requested: str):
        self.requested = requested
        self._paused = False

    async def start(self, identity: str | None) -> None:
        log.info("voice backend '%s' requested; conversation turn is the Phase 2 seam "
                 "(NullVoiceBackend active). identity_chars=%s",
                 self.requested, len(identity or ""))

    async def stop(self) -> None:
        log.info("voice backend stopped")

    async def speak(self, text: str) -> None:
        log.info("[voice:%s] would say: %s", self.requested, text)

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False


def make_voice_backend(name: str, config=None) -> VoiceBackend:
    # Both 'local' and 'realtime' resolve to the stub until Phase 2 wiring.
    return NullVoiceBackend(requested=name or "local")
