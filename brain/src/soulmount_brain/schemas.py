"""Request/response models for the brain API (SPEC §7.1)."""

from __future__ import annotations

from pydantic import BaseModel


class SyncTurnIn(BaseModel):
    source: str
    user_text: str = ""
    assistant_text: str = ""
    ts: str | None = None


class RememberIn(BaseModel):
    note: str


class JournalIn(BaseModel):
    text: str | None = None
    svg: str | None = None


class WishlistIn(BaseModel):
    item: str


class InterestsIn(BaseModel):
    markdown: str


class SayPrivatelyIn(BaseModel):
    person: str
    text: str


class RelayIn(BaseModel):
    video: str
    text: str
    relayed_by: str
