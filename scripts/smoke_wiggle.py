#!/usr/bin/env python3
"""smoke_wiggle.py — Phase 0 live smoke tests (SUPERVISED; motion + sound).

Announces and asks before EACH action (guardrail 11). Not for quiet hours. Uses the
daemon REST (verified shapes); the SDK antenna-wiggle is an alternative once the SDK
venv exists. Run via `make smoke`.
"""
from __future__ import annotations

import argparse
import sys
import time

import httpx

EMO_DS = "pollen-robotics/reachy-mini-emotions-library"


def ask(prompt: str) -> bool:
    if not sys.stdin.isatty():
        print(f"[non-interactive] skipping: {prompt}")
        return False
    return input(f"{prompt} [y/N] ").strip().lower() == "y"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="reachy-mini.local")
    args = ap.parse_args()
    base = f"http://{args.host}:8000"
    c = httpx.Client(timeout=20.0)

    print(f"Live smoke test against {base}. Each step asks first; the robot is in a")
    print("shared living room — announce in chat before running.\n")

    if ask("1) Play a gentle emotion (cheerful1) — a small wiggle?"):
        r = c.post(f"{base}/api/move/play/recorded-move-dataset/{EMO_DS}/cheerful1")
        print("   ->", r.status_code)
        time.sleep(2)

    if ask("2) Play one more emotion (curious1)?"):
        r = c.post(f"{base}/api/move/play/recorded-move-dataset/{EMO_DS}/curious1")
        print("   ->", r.status_code)
        time.sleep(2)

    if ask("3) Play a short sound at low volume?"):
        sounds = c.get(f"{base}/api/media/sounds").json()
        name = (sounds[0] if isinstance(sounds, list) and sounds else None)
        if name:
            c.post(f"{base}/api/volume/set", json={"volume": 30})
            r = c.post(f"{base}/api/media/play_sound", json={"filename": name})
            print(f"   played {name} ->", r.status_code)
        else:
            print("   no sounds available to play")

    if ask("4) Fetch a camera snapshot (robot must be awake/head-up)?"):
        print("   camera snapshots are via WebRTC :8443 (see FACTS §1.2); wire at Phase 2.")

    print("\nSmoke test done. Record results in FACTS.md if anything differed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
