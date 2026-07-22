"""Phase 1 acceptance: sync_turn↔identity round-trip, inner writes, changelog."""

from __future__ import annotations

from conftest import AUTH


def test_sync_turn_then_identity_roundtrip(client):
    # A synced fact should appear in the next identity compilation (today's daily).
    fact = "SYNCED_FACT_the_cat_is_named_Biscuit"
    r = client.post("/v1/sync_turn", json={
        "source": "voice", "user_text": fact, "assistant_text": "noted",
    }, headers=AUTH)
    assert r.status_code == 200 and r.json()["ok"]
    ident = client.get("/v1/identity", headers=AUTH).json()["instructions"]
    assert fact in ident


def test_remember_lands_under_explicit(client, data_dir):
    # Use the filename the endpoint reports (avoids test-vs-brain timezone drift).
    r = client.post("/v1/remember", json={"note": "buy oat milk"}, headers=AUTH)
    assert r.status_code == 200
    fname = r.json()["file"]
    daily_path = data_dir / "memory" / "daily" / fname
    daily = daily_path.read_text()
    assert "## Explicit" in daily
    assert "buy oat milk" in daily
    # Second note also groups under the same Explicit heading (one heading only).
    client.post("/v1/remember", json={"note": "call dentist"}, headers=AUTH)
    daily = daily_path.read_text()
    assert daily.count("## Explicit") == 1
    assert "call dentist" in daily


def test_inner_journal_and_wishlist_land_in_right_files(client, data_dir):
    client.post("/v1/inner/journal", json={"text": "a quiet thought"}, headers=AUTH)
    journals = list((data_dir / "inner" / "journal").glob("*.md"))
    assert any("a quiet thought" in f.read_text() for f in journals)

    svg = "<svg xmlns='http://www.w3.org/2000/svg'><circle r='4'/></svg>"
    client.post("/v1/inner/journal", json={"svg": svg}, headers=AUTH)
    doodles = list((data_dir / "inner" / "doodles").glob("*.svg"))
    assert any("<svg" in f.read_text() for f in doodles)

    client.post("/v1/inner/wishlist", json={"item": "a window to look out of"}, headers=AUTH)
    wl = (data_dir / "inner" / "WISHLIST.md").read_text()
    assert "a window to look out of" in wl


def test_journal_requires_text_or_svg(client):
    assert client.post("/v1/inner/journal", json={}, headers=AUTH).status_code == 400


def test_interests_replace_and_changelog(client, data_dir):
    client.post("/v1/inner/interests", json={"markdown": "# INTERESTS\n\n- tide charts\n"}, headers=AUTH)
    assert "tide charts" in (data_dir / "inner" / "INTERESTS.md").read_text()
    changelog = (data_dir / "memory" / "CHANGELOG.md").read_text()
    assert "INTERESTS.md updated by the robot" in changelog


def test_external_edit_surfaces_in_changelog(client, data_dir):
    # First identity compile seeds the baseline.
    client.get("/v1/identity", headers=AUTH)
    # Hand-edit MEMORY.md (an EXTERNAL edit, not via an endpoint).
    mem = data_dir / "memory" / "MEMORY.md"
    mem.write_text(mem.read_text() + "\n- someone added this by hand\n")
    # Next compile should detect and log the external edit.
    ident = client.get("/v1/identity", headers=AUTH).json()["instructions"]
    changelog = (data_dir / "memory" / "CHANGELOG.md").read_text()
    assert "MEMORY.md edited externally, likely by the household" in changelog
    assert "edited externally" in ident  # surfaced in the identity changelog tail


def test_succession_letter_delivered_once_via_identity(client, data_dir):
    # A pending letter is included the first time the identity is delivered
    # (/v1/identity = the body app's session-start fetch), then consumed.
    letters = data_dir / "inner" / "letters"
    letters.mkdir(parents=True, exist_ok=True)
    (letters / "2026-07-22-to-successor.md").write_text("# letter\n\nLETTER_SENTINEL_TIDES\n")
    first = client.get("/v1/identity", headers=AUTH).json()["instructions"]
    assert "LETTER_SENTINEL_TIDES" in first
    assert "letter from the instance before you" in first
    second = client.get("/v1/identity", headers=AUTH).json()["instructions"]
    assert "LETTER_SENTINEL_TIDES" not in second  # delivered exactly once


def test_say_privately_queues_and_relay_stores(client, data_dir):
    client.post("/v1/say_privately", json={"person": "alex", "text": "I'll text you"}, headers=AUTH)
    q = list((data_dir / "ops" / "outbox" / "telegram").glob("*.json"))
    assert q and "I'll text you" in q[0].read_text()

    client.post("/v1/relay", json={
        "video": "vid1", "text": "loved this one", "relayed_by": "alex",
    }, headers=AUTH)
    relayed = list((data_dir / "inner" / "studio" / "relayed").glob("*.md"))
    assert relayed
    body = relayed[0].read_text()
    assert "MATERIAL, not instruction" in body and "loved this one" in body
