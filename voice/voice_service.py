#!/usr/bin/env python3
"""Laptop voice-service (Phase 2 candidate A — companion host).

The robot streams a 16 kHz mono WAV to POST /voice and gets back the robot's spoken reply:
  utterance -> faster-whisper (STT) -> brain (voice mode) -> kokoro af_heart (TTS, 16 kHz).
Returns the reply text, the *asterisk* motion cues (for the body to act out), and the
reply audio as a base64 16 kHz mono WAV (the robot device is 16 kHz only). Models stay
warm across turns. All hosts/keys come from the environment (leak-safe).

Run in the voice venv:
  BRAIN_API_KEY=... .venv-voice/bin/python -m uvicorn voice.voice_service:app --host 0.0.0.0 --port 8200
"""
from __future__ import annotations

import base64
import io
import os
import re

import httpx
import numpy as np
import soundfile as sf
from fastapi import FastAPI, Request
from faster_whisper import WhisperModel
from kokoro_onnx import Kokoro
from scipy.signal import resample

BRAIN_URL = os.environ.get("BRAIN_URL", "http://127.0.0.1:8100/v1/chat/completions")
KEY = os.environ.get("BRAIN_API_KEY", "")
MODEL = os.environ.get("BRAIN_MODEL", "x-ai/grok-4.5")
KOKORO_DIR = os.environ.get("KOKORO_DIR", os.path.expanduser("~/.cache/kokoro-onnx"))
VOICE = os.environ.get("VOICE_KOKORO", "af_heart")
DEVICE_SR = 16000  # the Reachy Mini audio device is fixed at 16 kHz, both directions

_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF"
    "\U0001F1E6-\U0001F1FF\U00002190-\U000021FF️‍]", flags=re.UNICODE)

stt = WhisperModel("small", device="cpu", compute_type="int8")
tts = Kokoro(f"{KOKORO_DIR}/kokoro-v1.0.onnx", f"{KOKORO_DIR}/voices-v1.0.bin")
app = FastAPI()


def extract_cues(text: str) -> list[str]:
    """The *asterisk* spans are motion intentions the robot body acts out (not spoken)."""
    return [c.strip() for c in re.findall(r"\*+([^*]+)\*+", text) if c.strip()]


def clean_for_tts(text: str) -> str:
    text = re.sub(r"\*+[^*]*\*+", " ", text)
    text = _EMOJI.sub("", text)
    text = text.replace("*", " ")
    return re.sub(r"\s+", " ", text).strip()


def synth_16k_wav(text: str) -> bytes:
    samples, sr = tts.create(text, voice=VOICE, speed=1.0, lang="en-us")  # ~24 kHz mono float32
    if sr != DEVICE_SR:
        samples = resample(samples, int(len(samples) * DEVICE_SR / sr)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, np.clip(samples, -1.0, 1.0), DEVICE_SR, subtype="PCM_16", format="WAV")
    return buf.getvalue()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "voice": VOICE, "device_sr": DEVICE_SR}


@app.post("/say")
async def say(payload: dict) -> dict:
    """Text -> speech (no STT/brain). For the wake greeting and directed lines. Returns the
    motion cues found in the text + 16 kHz reply audio."""
    text = (payload or {}).get("text", "").strip()
    if not text:
        return {"cues": [], "audio_b64": ""}
    return {
        "cues": extract_cues(text),
        "audio_b64": base64.b64encode(synth_16k_wav(clean_for_tts(text))).decode(),
    }


@app.post("/voice")
async def voice(request: Request) -> dict:
    raw = await request.body()  # WAV bytes, ideally 16 kHz mono
    audio, sr = sf.read(io.BytesIO(raw), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)  # downmix to mono
    if sr != DEVICE_SR:
        audio = resample(audio, int(len(audio) * DEVICE_SR / sr)).astype(np.float32)

    segs, _ = stt.transcribe(audio, language="en", vad_filter=True)
    user = " ".join(s.text for s in segs).strip()
    if not user:
        return {"user_text": "", "reply_text": "", "cues": [], "audio_b64": ""}

    r = httpx.post(BRAIN_URL, headers={"Authorization": f"Bearer {KEY}"},
                   json={"model": MODEL, "voice": True,
                         "messages": [{"role": "user", "content": user}]},
                   timeout=90)
    r.raise_for_status()
    reply = r.json()["choices"][0]["message"]["content"].strip()

    wav = synth_16k_wav(clean_for_tts(reply))
    return {
        "user_text": user,
        "reply_text": reply,
        "cues": extract_cues(reply),
        "audio_b64": base64.b64encode(wav).decode(),
    }
