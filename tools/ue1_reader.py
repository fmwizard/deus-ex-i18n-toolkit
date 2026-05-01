"""UE1 package reader — minimal, just enough to locate UFont exports and dump bytes."""
import struct
from pathlib import Path


def read_compact_index(data: bytes, off: int):
    b0 = data[off]
    sign = -1 if (b0 & 0x80) else 1
    v = b0 & 0x3F
    cont = b0 & 0x40
    consumed = 1
    shift = 6
    while cont:
        b = data[off + consumed]
        consumed += 1
        v |= (b & 0x7F) << shift
        shift += 7
        cont = b & 0x80
    return sign * v, consumed


def write_compact_index(v: int) -> bytes:
    out = bytearray()
    sign = 0x80 if v < 0 else 0
    v = abs(v)
    b0 = sign | (v & 0x3F)
    v >>= 6
    if v:
        b0 |= 0x40
    out.append(b0)
    while v:
        b = v & 0x7F
        v >>= 7
        if v:
            b |= 0x80
        out.append(b)
    return bytes(out)


def read_fstring(data: bytes, off: int):
    n, k = read_compact_index(data, off)
    s = data[off + k : off + k + n - 1].decode("latin-1", "replace")
    return s, k + n


# UE1 name-entry flags: RF_LoadForClient | RF_LoadForServer | RF_LoadForEdit.
# Set on fresh names; the engine won't resolve cross-package references
# to a name without at least one LoadFor* flag.
DEFAULT_NEW_NAME_FLAGS = 0x00070000

# UE1 export-entry ObjectFlags. UObject serialization skips any export whose
# ObjectFlags lack RF_LoadFor*; such objects exist in the export table but are
# never instantiated, so ObjRef resolution yields NULL at runtime.
# Matches stock Texture export flags in DeusExUI.u (Palette adds RF_Public=0x4).
DEFAULT_NEW_EXPORT_FLAGS = 0x00070000
DEFAULT_NEW_PALETTE_FLAGS = 0x00070004


class Package:
    def __init__(self, path):
        self.path = Path(path)
        self.buf = self.path.read_bytes()
        self._parse_header()
        self._parse_names()
        self._parse_imports()
        self._parse_exports()

    def _parse_header(self):
        b = self.buf
        sig = struct.unpack_from("<I", b, 0)[0]
        assert sig == 0x9E2A83C1, f"bad signature {sig:x}"
        self.ver = struct.unpack_from("<H", b, 4)[0]
        self.licensee = struct.unpack_from("<H", b, 6)[0]
        self.flags = struct.unpack_from("<I", b, 8)[0]
        self.name_count = struct.unpack_from("<I", b, 12)[0]
        self.name_offset = struct.unpack_from("<I", b, 16)[0]
        self.export_count = struct.unpack_from("<I", b, 20)[0]
        self.export_offset = struct.unpack_from("<I", b, 24)[0]
        self.import_count = struct.unpack_from("<I", b, 28)[0]
        self.import_offset = struct.unpack_from("<I", b, 32)[0]

    def _parse_names(self):
        self.names = []
        self.name_flags = []
        off = self.name_offset
        for _ in range(self.name_count):
            s, k = read_fstring(self.buf, off)
            off += k
            flags = struct.unpack_from("<I", self.buf, off)[0]
            off += 4
            self.names.append(s)
            self.name_flags.append(flags)

    def _parse_imports(self):
        self.imports = []
        off = self.import_offset
        for _ in range(self.import_count):
            cp, k = read_compact_index(self.buf, off); off += k
            cn, k = read_compact_index(self.buf, off); off += k
            pkg = struct.unpack_from("<i", self.buf, off)[0]; off += 4
            on, k = read_compact_index(self.buf, off); off += k
            self.imports.append({
                "class_package": self.names[cp],
                "class_name": self.names[cn],
                "package_ref": pkg,
                "object_name": self.names[on],
            })

    def _parse_exports(self):
        self.exports = []
        off = self.export_offset
        for i in range(self.export_count):
            start = off
            cls, k = read_compact_index(self.buf, off); off += k
            sup, k = read_compact_index(self.buf, off); off += k
            grp = struct.unpack_from("<i", self.buf, off)[0]; off += 4
            on, k = read_compact_index(self.buf, off); off += k
            flags = struct.unpack_from("<I", self.buf, off)[0]; off += 4
            size, k = read_compact_index(self.buf, off); off += k
            if size > 0:
                soff, k = read_compact_index(self.buf, off); off += k
            else:
                soff = 0
            self.exports.append({
                "idx": i,
                "class_ref": cls,
                "super_ref": sup,
                "group_ref": grp,
                "name_idx": on,
                "name": self.names[on],
                "flags": flags,
                "size": size,
                "offset": soff,
                "entry_offset": start,
            })

    def resolve_class(self, ref: int) -> str:
        if ref == 0:
            return "(Class)"
        if ref > 0:
            return self.exports[ref - 1]["name"]
        return self.imports[(-ref) - 1]["object_name"]

    def find_exports_by_class(self, class_name: str):
        return [e for e in self.exports if self.resolve_class(e["class_ref"]) == class_name]

    def read_export_bytes(self, exp) -> bytes:
        return self.buf[exp["offset"] : exp["offset"] + exp["size"]]

    def _serialize_import_table(self) -> bytes:
        out = bytearray()
        for imp in self.imports:
            out += write_compact_index(self.names.index(imp["class_package"]))
            out += write_compact_index(self.names.index(imp["class_name"]))
            out += struct.pack("<i", imp["package_ref"])
            out += write_compact_index(self.names.index(imp["object_name"]))
        return bytes(out)

    def _serialize_export_table(self, new_exports) -> bytes:
        out = bytearray()
        for e in new_exports:
            out += write_compact_index(e["class_ref"])
            out += write_compact_index(e["super_ref"])
            out += struct.pack("<i", e["group_ref"])
            out += write_compact_index(e["name_idx"])
            out += struct.pack("<I", e["flags"])
            out += write_compact_index(e["size"])
            if e["size"] > 0:
                out += write_compact_index(e["offset"])
        return bytes(out)

    def rewrite(self, replacements: dict, add_exports: list[dict] | None = None) -> bytes:
        """Serialize a new package.

        replacements: {export_name: new_binary_bytes}  (replace existing export data)
        add_exports: list of {class_ref, super_ref, group_ref, name, flags, blob} dicts
            for brand-new exports appended to the export table.

        Append-only strategy. The original binary region is preserved verbatim
        so absolute-offset pointers inside unchanged exports (e.g. FMipmap.WidthOffset)
        remain valid. Replaced exports and added exports are written at the end of
        the binary region (before the import/export tables), with their SerialOffset
        pointing to their final location.
        """
        add_exports = add_exports or []
        binary_start = min(e["offset"] for e in self.exports if e["offset"] > 0)
        # Original binary region ends where the import table begins in the source package.
        binary_end = self.import_offset

        # Ensure any new names required by add_exports are in the name table.
        # Stock name table is reused as-is; new names are appended.
        # Flags are preserved per-name — UE1 uses RF_LoadFor* to gate cross-package
        # name resolution; zeroing them breaks stock class lookups like
        # DeusExUI.UserInterface.
        working_names = list(self.names)
        working_flags = list(self.name_flags)
        for add in add_exports:
            if add["name"] not in working_names:
                working_names.append(add["name"])
                working_flags.append(DEFAULT_NEW_NAME_FLAGS)

        # Decide new offsets for existing exports (same logic as before)
        new_exports = []
        appended_blobs = []
        append_cursor = binary_end
        for e in self.exports:
            if e["size"] == 0:
                new_exports.append({**e, "offset": 0})
                continue
            if e["name"] in replacements:
                blob = replacements[e["name"]]
                if len(blob) == e["size"]:
                    # Same size — safe to overwrite in place at original offset.
                    new_exports.append({**e})
                else:
                    appended_blobs.append(("replace", e, blob))
                    new_exports.append({**e, "size": len(blob), "offset": append_cursor})
                    append_cursor += len(blob)
            else:
                new_exports.append({**e})

        # Append brand-new exports
        for add in add_exports:
            blob = add["blob"]
            entry = {
                "class_ref": add["class_ref"],
                "super_ref": add["super_ref"],
                "group_ref": add["group_ref"],
                "name_idx": working_names.index(add["name"]),
                "name": add["name"],
                "flags": add["flags"],
                "size": len(blob),
                "offset": append_cursor if len(blob) > 0 else 0,
            }
            new_exports.append(entry)
            if len(blob) > 0:
                appended_blobs.append(("add", None, blob))
                append_cursor += len(blob)

        new_name_count = len(working_names)

        # Always re-serialize and place the name table at the tail of the output.
        # `self.name_offset` is only valid for the input package's layout. On a
        # rebuild-of-rebuild, the previous build put its names at the file tail,
        # so `self.name_offset` now points inside the new build's grown binary
        # region — reusing it lands the header-declared name table on top of
        # freshly-appended atlas bytes and corrupts the package.
        name_bytes = self._serialize_name_table(working_names, working_flags)
        layout_new_names_at_end = True

        new_import_offset = append_cursor
        import_bytes = self._serialize_import_table()
        new_export_offset = new_import_offset + len(import_bytes)
        export_bytes = self._serialize_export_table(new_exports)

        # Assemble output
        out = bytearray(self.buf[:binary_end])  # header + names + entire original binary region
        # Patch same-size replacements in place
        for e in self.exports:
            if e["size"] > 0 and e["name"] in replacements:
                blob = replacements[e["name"]]
                if len(blob) == e["size"]:
                    out[e["offset"] : e["offset"] + e["size"]] = blob
        # Append size-changed replacements and new exports
        for _, _, blob in appended_blobs:
            out += blob
        out += import_bytes
        out += export_bytes
        if layout_new_names_at_end:
            new_name_offset = len(out)
            out += name_bytes
        else:
            new_name_offset = self.name_offset

        # Patch summary header
        struct.pack_into("<I", out, 12, new_name_count)
        struct.pack_into("<I", out, 16, new_name_offset)
        struct.pack_into("<I", out, 20, len(new_exports))
        struct.pack_into("<I", out, 24, new_export_offset)
        struct.pack_into("<I", out, 28, self.import_count)
        struct.pack_into("<I", out, 32, new_import_offset)
        return bytes(out)

    def _serialize_name_table(self, names: list[str], flags: list[int]) -> bytes:
        assert len(names) == len(flags), "names/flags length mismatch"
        out = bytearray()
        for n, f in zip(names, flags):
            encoded = n.encode("latin-1") + b"\x00"
            out += write_compact_index(len(encoded))
            out += encoded
            out += struct.pack("<I", f)
        return bytes(out)


if __name__ == "__main__":
    import sys
    pkg = Package(Path(sys.argv[1]))
    target = sys.argv[2] if len(sys.argv) > 2 else "Font"
    print(f"pkg ver={pkg.ver} names={pkg.name_count} imports={pkg.import_count} exports={pkg.export_count}")
    hits = pkg.find_exports_by_class(target)
    print(f"{len(hits)} '{target}' exports:")
    for e in hits:
        print(f"  [{e['idx']:4d}] {e['name']:<32} offset=0x{e['offset']:08x}  size=0x{e['size']:x}")
