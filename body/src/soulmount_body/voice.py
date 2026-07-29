"""Voice backend (SPEC Phase 2/3).

Two backends:
  - NullVoiceBackend: off-robot / tests — logs, no audio. Keeps the lifecycle runnable.
  - CascadeVoiceBackend: on the robot — captures the mic via the reachy SDK, streams each
    utterance to the companion-host voice-service (STT -> brain -> af_heart TTS), plays the
    reply through the SDK (so the XMOS hardware echo-cancel sees the reference), and turns
    the reply's *asterisk* motion cues into emotion moves via the daemon REST.

The cascade runs on a companion host (laptop now, attic GPU later): the Pi is Pi4-class with
no accelerator, so on-device STT/TTS would be too slow (FACTS §2.1 audio investigation).
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import threading
import time
import wave
from abc import ABC, abstractmethod

import httpx

try:  # only present on the robot (via the reachy SDK); off-robot stays importable
    import numpy as np
except Exception:  # pragma: no cover
    np = None

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
    """No-op backend: keeps the lifecycle runnable off-robot / in tests."""

    def __init__(self, requested: str):
        self.requested = requested
        self._paused = False

    async def start(self, identity: str | None) -> None:
        log.info("voice backend '%s' requested; NullVoiceBackend active (no audio). identity_chars=%s",
                 self.requested, len(identity or ""))

    async def stop(self) -> None:
        log.info("voice backend stopped")

    async def speak(self, text: str) -> None:
        log.info("[voice:%s] would say: %s", self.requested, text)

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False


# Map a free-text motion cue to an emotion-library move (default = a small acknowledging gesture).
_CUE_MAP = [
    (("wiggle", "antenna", "cheer", "happy", "excited", "delight", "grin", "smile", "bounce"), "cheerful1"),
    (("curious", "peek", "peer", "look", "nosy", "wonder", "inquis", "tilt"), "curious1"),
    (("laugh", "giggle", "chuckle"), "laughing1"),
    (("wave", "hello", "greet", "welcome", "hi "), "welcoming1"),
    (("sad", "droop", "sigh", "down"), "sad1"),
    (("proud", "success", "celebrat", "yay"), "proud1"),
    (("think", "ponder", "hmm", "thoughtful", "consider"), "thoughtful1"),
    (("surprise", "gasp", "woah", "wow", "startle"), "surprised1"),
]


def _cue_to_emotion(cue: str) -> str:
    c = cue.lower()
    for keys, move in _CUE_MAP:
        if any(k in c for k in keys):
            return move
    return "attentive1"


class CascadeVoiceBackend(VoiceBackend):
    """Robot-side conversational loop. Runs the listen->respond loop in a worker thread so the
    blocking SDK audio calls don't stall the app's asyncio event loop."""

    EMOTIONS = "pollen-robotics/reachy-mini-emotions-library"

    def __init__(self, cfg, reachy_mini):
        self.cfg = cfg
        self.rm = reachy_mini
        self.voice_url = (getattr(cfg, "voice_service_url", "") or "").rstrip("/")
        self.daemon = cfg.daemon_url.rstrip("/")
        self._active = threading.Event()   # listening enabled (cleared while asleep/quiet)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._play_lock = threading.Lock()
        self._wake_key: str | None = None
        self._http = httpx.Client(timeout=httpx.Timeout(90.0, connect=5.0))

    async def start(self, identity: str | None = None) -> None:
        for m in ("start_recording", "start_playing"):
            try:
                getattr(self.rm.media, m)()
            except Exception as e:
                log.warning("voice: media.%s failed: %s", m, e)
        self._active.set()
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="voice-loop", daemon=True)
            self._thread.start()
        log.info("cascade voice backend started (service=%s)", self.voice_url or "<unset>")

    def pause(self) -> None:
        self._active.clear()

    def resume(self) -> None:
        self._active.set()

    async def stop(self) -> None:
        self._stop.set()
        self._active.clear()
        if self._thread is not None:
            await asyncio.to_thread(self._thread.join, 3.0)
        for m in ("stop_recording", "stop_playing"):
            try:
                getattr(self.rm.media, m)()
            except Exception:
                pass
        self._http.close()

    async def speak(self, text: str) -> None:
        # Text -> speech for the greeting / directed lines (no mic). Runs off the event loop.
        await asyncio.to_thread(self._say, text)

    # ── worker-thread side ─────────────────────────────────────────────────────
    def _say(self, text: str) -> None:
        try:
            r = self._http.post(f"{self.voice_url}/say", json={"text": text})
            r.raise_for_status()
            d = r.json()
            self._act(d.get("cues") or [])
            self._play(d.get("audio_b64") or "")
        except Exception as e:
            log.warning("voice: say failed: %s", e)

    def _load_oww(self):
        """Load the openWakeWord detector (on the Pi). Returns None if unavailable.
        cfg.wake_word is a pretrained name (e.g. 'hey_jarvis') or a custom .onnx path."""
        try:
            import os
            import openwakeword
            from openwakeword.model import Model
            ww = self.cfg.wake_word
            if ww.endswith(".onnx") or "/" in ww:
                path = ww
            else:  # resolve a pretrained name to its bundled .onnx path
                path = next(p for p in openwakeword.get_pretrained_model_paths()
                            if ww in os.path.basename(p))
            model = Model(wakeword_model_paths=[path])
            self._wake_key = next(iter(model.models.keys()))
            log.info("wake word active: '%s' (threshold %.2f)", self._wake_key, self.cfg.wake_threshold)
            return model
        except Exception as e:
            log.warning("wake word unavailable (%s) — falling back to open listening", e)
            return None

    def _wait_for_wake(self, oww) -> bool:
        """Block, feeding mic frames to the detector, until the wake word fires. Nothing is
        sent off-device until this returns True — background chatter never leaves the house."""
        try:
            oww.reset()
        except Exception:
            pass
        thr = self.cfg.wake_threshold
        while not self._stop.is_set() and self._active.is_set():
            try:
                s = self.rm.media.get_audio_sample()
            except Exception:
                return False
            if s is None:
                time.sleep(0.01)
                continue
            x = np.asarray(s, dtype=np.float32)
            if x.ndim > 1:
                x = x.mean(axis=1)
            if x.size == 0:
                continue
            pcm16 = (np.clip(x, -1.0, 1.0) * 32767.0).astype(np.int16)
            try:
                scores = oww.predict(pcm16)
            except Exception:
                continue
            if scores.get(self._wake_key, 0.0) >= thr:
                log.info("wake word '%s' detected", self._wake_key)
                return True
        return False

    def _loop(self) -> None:
        oww = self._load_oww()
        while not self._stop.is_set():
            if not self._active.is_set():
                time.sleep(0.1)
                continue
            # Wake gate: capture a turn only after the wake word (ignores background talk).
            # If the detector didn't load, fall back to open listening so the app still works.
            if oww is not None and not self._wait_for_wake(oww):
                continue
            utt = self._collect()
            if utt is None or self._stop.is_set() or not self._active.is_set():
                continue
            try:
                r = self._http.post(f"{self.voice_url}/voice", content=self._wav(utt),
                                    headers={"Content-Type": "audio/wav"})
                r.raise_for_status()
                d = r.json()
                if d.get("reply_text"):
                    log.info("voice turn — you=%r reply=%r", d.get("user_text"), d.get("reply_text"))
                    self._act(d.get("cues") or [])
                    self._play(d.get("audio_b64") or "")
            except Exception as e:
                log.warning("voice: turn failed: %s", e)

    def _collect(self, max_s: float = 13.0, silence_ms: float = 900.0,
                 min_speech_ms: float = 250.0, thr: float = 0.02):
        """Energy-VAD an utterance from SDK mic frames. Returns mono float32 @16k, or None."""
        frames, started, sil, sp, t0 = [], False, 0.0, 0.0, time.time()
        while not self._stop.is_set() and self._active.is_set() and time.time() - t0 < max_s:
            try:
                s = self.rm.media.get_audio_sample()
            except Exception:
                return None
            if s is None:
                time.sleep(0.01)
                continue
            x = np.asarray(s, dtype=np.float32)
            if x.ndim > 1:
                x = x.mean(axis=1)
            if x.size == 0:
                continue
            rms = float(np.sqrt(np.mean(x * x)))
            ms = 1000.0 * x.size / 16000.0
            if rms > thr:
                started, sil, sp = True, 0.0, sp + ms
            elif started:
                sil += ms
            if started:
                frames.append(x)
                if sil >= silence_ms and sp >= min_speech_ms:
                    break
        if not frames or sp < min_speech_ms:
            return None
        return np.concatenate(frames)

    def _wav(self, mono_f32) -> bytes:
        pcm16 = (np.clip(mono_f32, -1.0, 1.0) * 32767.0).astype("<i2")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(pcm16.tobytes())
        return buf.getvalue()

    def _play(self, b64: str) -> None:
        if not b64:
            return
        try:
            with wave.open(io.BytesIO(base64.b64decode(b64)), "rb") as w:
                pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32767.0
            with self._play_lock:
                # push in small frames — the SDK appsrc expects streamed chunks, not one blob.
                step = 1600  # 100 ms @16k
                for i in range(0, len(pcm), step):
                    self.rm.media.push_audio_sample(pcm[i:i + step])
        except Exception as e:
            log.warning("voice: play failed: %s", e)

    def _act(self, cues) -> None:
        for cue in list(cues)[:2]:  # cap emotions per turn
            move = _cue_to_emotion(cue)
            try:
                self._http.post(
                    f"{self.daemon}/api/move/play/recorded-move-dataset/{self.EMOTIONS}/{move}",
                    timeout=8.0)
            except Exception:
                pass


def make_voice_backend(name: str, config=None, reachy_mini=None) -> VoiceBackend:
    # On the robot (reachy_mini present) with a real backend name -> cascade; else the stub.
    if reachy_mini is not None and config is not None and (name or "local") != "null":
        return CascadeVoiceBackend(config, reachy_mini)
    return NullVoiceBackend(requested=name or "local")
