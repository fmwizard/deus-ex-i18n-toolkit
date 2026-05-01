"""Verify Package.rewrite() can add new exports (not just replace existing ones)."""
import os
import pytest
from pathlib import Path
from ue1_reader import Package

STOCK_DEUSEX_UI = os.environ.get("DX1_TEST_STOCK_DEUSEXUI")
HAS_STOCK = bool(STOCK_DEUSEX_UI) and Path(STOCK_DEUSEX_UI).exists()


@pytest.mark.skipif(not HAS_STOCK, reason="stock DeusExUI.u not available")
def test_add_single_utexture_export(tmp_path):
    pkg = Package(str(STOCK_DEUSEX_UI))
    original_export_count = len(pkg.exports)

    # A minimal dummy blob so round-trip succeeds. UTexture parsing details
    # are not required here; the test only checks the export-table entry.
    dummy_blob = b"\x00" * 128  # arbitrary placeholder bytes
    # Resolve UTexture class: it's an Engine import in DeusExUI.u
    tex_class_ref = None
    for i, imp in enumerate(pkg.imports):
        if imp["class_name"] == "Class" and imp["object_name"] == "Texture":
            tex_class_ref = -(i + 1)
            break
    assert tex_class_ref is not None, "Texture class import not found in stock pkg"

    new_pkg_bytes = pkg.rewrite(
        replacements={},
        add_exports=[{
            "class_ref": tex_class_ref,
            "super_ref": 0,
            "group_ref": 0,
            "name": "TestAtlas0",
            "flags": 0,
            "blob": dummy_blob,
        }],
    )
    out = tmp_path / "out.u"
    out.write_bytes(new_pkg_bytes)

    pkg2 = Package(str(out))
    assert len(pkg2.exports) == original_export_count + 1
    new_exp = pkg2.exports[-1]
    assert new_exp["name"] == "TestAtlas0"
    assert pkg2.read_export_bytes(new_exp) == dummy_blob


@pytest.mark.skipif(not HAS_STOCK, reason="stock DeusExUI.u not available")
def test_add_multiple_exports_with_new_names(tmp_path):
    pkg = Package(str(STOCK_DEUSEX_UI))
    tex_class_ref = next(
        -(i + 1) for i, imp in enumerate(pkg.imports)
        if imp["class_name"] == "Class" and imp["object_name"] == "Texture"
    )
    adds = [
        {"class_ref": tex_class_ref, "super_ref": 0, "group_ref": 0,
         "name": f"TestAtlas{i}", "flags": 0, "blob": bytes([i]) * 64}
        for i in range(3)
    ]
    new_pkg_bytes = pkg.rewrite(replacements={}, add_exports=adds)
    out = tmp_path / "out.u"
    out.write_bytes(new_pkg_bytes)
    pkg2 = Package(str(out))
    for i in range(3):
        exp = next(e for e in pkg2.exports if e["name"] == f"TestAtlas{i}")
        assert pkg2.read_export_bytes(exp) == bytes([i]) * 64


def test_existing_replace_behavior_unchanged(tmp_path):
    """Sanity: default rewrite (no add_exports) behaves exactly like before."""
    if not HAS_STOCK:
        pytest.skip("stock DeusExUI.u not available")
    pkg = Package(str(STOCK_DEUSEX_UI))
    # Just serialize unchanged
    out_bytes = pkg.rewrite(replacements={})
    pkg2 = Package.__new__(Package)
    pkg2.path = tmp_path / "out.u"
    pkg2.buf = out_bytes
    pkg2._parse_header()
    pkg2._parse_names()
    pkg2._parse_imports()
    pkg2._parse_exports()
    assert len(pkg2.exports) == len(pkg.exports)
    for e1, e2 in zip(pkg.exports, pkg2.exports):
        assert e1["name"] == e2["name"]
        assert e1["size"] == e2["size"]


@pytest.mark.skipif(not HAS_STOCK, reason="stock DeusExUI.u not available")
def test_name_flags_preserved_through_add_exports(tmp_path):
    """Stock name flags must survive rewrite() when the name table is rebuilt.

    UE1 RF_LoadFor* flags gate cross-package name resolution; zeroing them breaks
    stock class lookups like DeusExUI.UserInterface.
    """
    pkg = Package(str(STOCK_DEUSEX_UI))
    tex_class_ref = next(
        -(i + 1) for i, imp in enumerate(pkg.imports)
        if imp["class_name"] == "Class" and imp["object_name"] == "Texture"
    )
    # At least one stock name must have a nonzero flag for this test to be meaningful.
    assert any(f != 0 for f in pkg.name_flags), "stock pkg has no nonzero name flags?"

    new_pkg_bytes = pkg.rewrite(
        replacements={},
        add_exports=[{
            "class_ref": tex_class_ref, "super_ref": 0, "group_ref": 0,
            "name": "FlagsProbe", "flags": 0,
            "blob": b"\x00" * 16,
        }],
    )
    out = tmp_path / "out.u"
    out.write_bytes(new_pkg_bytes)
    pkg2 = Package(str(out))

    # Every original name keeps its original flag bits.
    for i, (orig_name, orig_flags) in enumerate(zip(pkg.names, pkg.name_flags)):
        assert pkg2.names[i] == orig_name
        assert pkg2.name_flags[i] == orig_flags, (
            f"name[{i}] '{orig_name}' flags drifted: "
            f"stock=0x{orig_flags:08x} rewritten=0x{pkg2.name_flags[i]:08x}"
        )
    # And the new name has the default new-name flags (RF_LoadFor* set).
    from ue1_reader import DEFAULT_NEW_NAME_FLAGS
    probe_idx = pkg2.names.index("FlagsProbe")
    assert pkg2.name_flags[probe_idx] == DEFAULT_NEW_NAME_FLAGS


@pytest.mark.skipif(not HAS_STOCK, reason="stock DeusExUI.u not available")
def test_double_rewrite_preserves_name_table(tmp_path):
    """Rebuilding on top of a previously-rebuilt package must keep names readable.

    Regression: previously `rewrite()` would only re-serialize the name table
    when new names were added; otherwise it reused `self.name_offset` verbatim.
    On a rebuild-of-rebuild where the first build placed names at the old file's
    tail, the second build's binary region grows past that offset — so the
    reused offset lands the header-declared name table on top of new atlas bytes.
    """
    pkg = Package(str(STOCK_DEUSEX_UI))
    tex_class_ref = next(
        -(i + 1) for i, imp in enumerate(pkg.imports)
        if imp["class_name"] == "Class" and imp["object_name"] == "Texture"
    )
    # First rewrite: add 3 fresh names + large-enough blobs to grow the file.
    adds1 = [
        {"class_ref": tex_class_ref, "super_ref": 0, "group_ref": 0,
         "name": f"FirstAtlas{i}", "flags": 0, "blob": bytes([i]) * 4096}
        for i in range(3)
    ]
    out1 = pkg.rewrite(replacements={}, add_exports=adds1)
    p1 = tmp_path / "rewrite1.u"
    p1.write_bytes(out1)
    pkg1 = Package(str(p1))
    assert "None" in pkg1.names

    # Second rewrite on pkg1's output: no new names, but append more blobs so
    # the binary region grows past pkg1's old name-table position.
    adds2 = [
        {"class_ref": tex_class_ref, "super_ref": 0, "group_ref": 0,
         "name": f"SecondAtlas{i}", "flags": 0, "blob": bytes([0xA0 | i]) * 8192}
        for i in range(3)
    ]
    out2 = pkg1.rewrite(replacements={}, add_exports=adds2)
    p2 = tmp_path / "rewrite2.u"
    p2.write_bytes(out2)
    pkg2 = Package(str(p2))

    # Name table must still parse to the expected set.
    assert "None" in pkg2.names
    assert "FirstAtlas0" in pkg2.names
    assert "SecondAtlas0" in pkg2.names
    # Every stock name still resolvable by its export name_idx.
    for e in pkg2.exports:
        assert 0 <= e["name_idx"] < len(pkg2.names)
        # Attempted lookup must not crash; name bytes are real latin-1 text.
        _ = pkg2.names[e["name_idx"]]
