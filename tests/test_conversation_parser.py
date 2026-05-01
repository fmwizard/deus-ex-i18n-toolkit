"""Tests for Conversation property-tag parser and eventList traversal."""
import os
from pathlib import Path

import pytest
from ue1_reader import Package
from contex.conversation_parser import parse_conversation, walk_event_list

STOCK_CONTEX = os.environ.get("DX1_TEST_STOCK_DEUSEXCONTEXT")
HAS_STOCK = bool(STOCK_CONTEX) and Path(STOCK_CONTEX).exists()


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_parse_all_conversations_extract_5_fields():
    pkg = Package(STOCK_CONTEX)
    convs = [e for e in pkg.exports if pkg.resolve_class(e["class_ref"]) == "Conversation"]
    assert len(convs) == 1955, f"expected 1955 Conversations, got {len(convs)}"

    headers = []
    missing_audio = 0
    missing_name = 0
    for e in convs:
        eb = pkg.read_export_bytes(e)
        h = parse_conversation(eb, pkg.names)
        headers.append(h)
        if h.con_name is None:
            missing_name += 1
        if h.audio_package_name is None:
            missing_audio += 1

    # Not every Conversation declares audioPackageName (some use defaults) — allow up to 5%.
    assert missing_audio / len(convs) < 0.05
    assert missing_name == 0

    ids = {h.conversation_id for h in headers}
    assert len(ids) > 400

    eventlists = sum(1 for h in headers if h.event_list_objref != 0)
    assert eventlists > 1900


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_parse_all_conversations_unique_audio_packages():
    pkg = Package(STOCK_CONTEX)
    convs = [e for e in pkg.exports if pkg.resolve_class(e["class_ref"]) == "Conversation"]
    audio_names = set()
    for e in convs:
        h = parse_conversation(pkg.read_export_bytes(e), pkg.names)
        if h.audio_package_name:
            audio_names.add(h.audio_package_name)
    assert len(audio_names) == 18, f"expected 18 unique audio package names, got {len(audio_names)}"
    assert "Intro" in audio_names
    assert "Mission01" in audio_names


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_walk_event_list_returns_ordered_events():
    pkg = Package(STOCK_CONTEX)
    convs = [e for e in pkg.exports if pkg.resolve_class(e["class_ref"]) == "Conversation"]

    for e in convs:
        h = parse_conversation(pkg.read_export_bytes(e), pkg.names)
        if h.audio_package_name == "Intro" and h.event_list_objref > 0:
            events = walk_event_list(pkg, h.event_list_objref)
            assert len(events) > 10
            for ei in events:
                assert 0 <= ei < len(pkg.exports)
                cls = pkg.resolve_class(pkg.exports[ei]["class_ref"])
                assert cls.startswith("Con")
            return

    pytest.skip("no Intro conversation with valid eventList found")


@pytest.mark.skipif(not HAS_STOCK, reason="DX1_TEST_STOCK_DEUSEXCONTEXT not set")
def test_walk_event_list_no_duplicates():
    pkg = Package(STOCK_CONTEX)
    convs = [e for e in pkg.exports if pkg.resolve_class(e["class_ref"]) == "Conversation"]

    checked = 0
    for e in convs[:50]:
        h = parse_conversation(pkg.read_export_bytes(e), pkg.names)
        if h.event_list_objref > 0:
            events = walk_event_list(pkg, h.event_list_objref)
            assert len(events) == len(set(events))
            checked += 1

    assert checked > 0
