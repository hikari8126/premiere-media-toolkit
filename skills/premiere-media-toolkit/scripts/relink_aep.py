#!/usr/bin/env python3
"""relink_aep.py — relink After Effects .aep file based on a rename manifest CSV.

After Effects .aep is a RIFX (big-endian RIFF) binary format. Each footage item
is stored as an `Item` LIST chunk containing:
  - `Utf8` chunk: display basename (e.g. "2.MOV")
  - `LIST` (form=`Pin `) chunk → contains `LIST` (form=`Als2`) → `alas` chunk
    holding JSON: {"ascendcount_base":N, "ascendcount_target":M,
                   "fullpath":"/abs/path/...", ...}

Strategy:
  - Parse RIFX tree recursively.
  - For each `Item` LIST: extract fullpath from alas JSON. Match suffix
    against manifest old paths. If match:
      - Replace fullpath in JSON.
      - Adjust `ascendcount_target` for path depth delta.
      - Replace the paired `Utf8` chunk content with new basename.
  - Rebuild file with recalculated chunk sizes (RIFX big-endian uint32).

Usage:
    python3 relink_aep.py <project.aep> <manifest.csv> [--apply] [-v]

Outputs:
  - <project>.RELINKED.aep
  - <project>.ORIGINAL.BACKUP.aep
  - <project>.aep_relink_report.csv
"""
import argparse, csv, json, re, struct, sys, unicodedata
from collections import defaultdict
from pathlib import Path

LIST_TAGS = (b'RIFX', b'LIST')

# === Manifest ===

def normalize_for_compare(p):
    return unicodedata.normalize('NFC', p.replace('\\', '/'))

def basename(p):
    p = p.replace('\\', '/').rstrip('/')
    return p.rsplit('/', 1)[-1]

def load_manifest(csv_path):
    rows = []
    with open(csv_path, encoding='utf-8') as f:
        r = csv.reader(f)
        next(r, None)  # header
        for row in r:
            if len(row) >= 2 and row[0].strip() and row[1].strip():
                rows.append((row[0].strip(), row[1].strip()))
    return rows

def match_manifest_suffix(current_path, manifest_norm):
    """Find longest manifest entry where current_path ends with old_rel."""
    cur = normalize_for_compare(current_path)
    cur_lower = cur.lower()
    best, best_len = None, -1
    for old_rel, new_rel, old_norm, old_norm_lower in manifest_norm:
        if cur_lower.endswith(old_norm_lower) and len(old_norm) > best_len:
            idx = len(cur) - len(old_norm)
            if idx == 0 or cur[idx - 1] in ('/', '\\'):
                best = (old_rel, new_rel)
                best_len = len(old_norm)
    return best

def replace_suffix(current_path, old_rel, new_rel):
    cur = normalize_for_compare(current_path)
    old = normalize_for_compare(old_rel)
    new = normalize_for_compare(new_rel)
    if not cur.lower().endswith(old.lower()):
        return current_path
    return cur[:len(cur) - len(old)] + new

# === RIFX chunk IO ===

def parse_chunk_at(data, offset):
    if offset + 8 > len(data):
        return None
    tag = bytes(data[offset:offset+4])
    size = struct.unpack('>I', data[offset+4:offset+8])[0]
    cs = offset + 8
    ce = cs + size
    next_off = ce + (size & 1)  # pad to even
    return tag, size, cs, ce, next_off

def build_chunk(tag, content):
    """Build a chunk: tag + size(BE) + content + pad-to-even."""
    out = bytearray()
    out.extend(tag)
    out.extend(struct.pack('>I', len(content)))
    out.extend(content)
    if len(content) & 1:
        out.append(0)
    return bytes(out)

# === Item LIST handling ===

def find_alas_in_pin(data, pin_offset):
    """Return (alas_offset, alas_size, alas_cs, alas_ce) or None."""
    info = parse_chunk_at(data, pin_offset)
    if info is None: return None
    tag, size, cs, ce, _ = info
    if tag != b'LIST' or data[cs:cs+4] != b'Pin ':
        return None
    sub_off = cs + 4
    while sub_off < ce:
        sub = parse_chunk_at(data, sub_off)
        if sub is None: break
        s_tag, s_size, s_cs, s_ce, s_next = sub
        if s_tag == b'LIST' and data[s_cs:s_cs+4] == b'Als2':
            # Find alas inside
            inner_off = s_cs + 4
            while inner_off < s_ce:
                inner = parse_chunk_at(data, inner_off)
                if inner is None: break
                i_tag, i_size, i_cs, i_ce, i_next = inner
                if i_tag == b'alas':
                    return (inner_off, i_size, i_cs, i_ce)
                inner_off = i_next
        sub_off = s_next
    return None

# Stats (filled during rewrite)
class Stats:
    def __init__(self):
        self.items_scanned = 0
        self.items_matched = 0
        self.utf8_updated = 0
        self.alas_updated = 0
        self.report = []  # (old, new, basename_updated, alas_updated)

def rewrite_alas_json(alas_content_bytes, manifest_norm, stats):
    """If JSON's fullpath matches manifest, return (new_bytes, old_rel, new_rel, new_basename).
    Else return (alas_content_bytes, None, None, None)."""
    try:
        s = alas_content_bytes.decode('utf-8')
        obj = json.loads(s)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return alas_content_bytes, None, None, None
    if 'fullpath' not in obj:
        return alas_content_bytes, None, None, None
    old_full = obj['fullpath']
    match = match_manifest_suffix(old_full, manifest_norm)
    if not match:
        return alas_content_bytes, None, None, None
    old_rel, new_rel = match
    new_full = replace_suffix(old_full, old_rel, new_rel)
    # Adjust ascendcount_target by component delta
    old_components = old_rel.replace('\\', '/').strip('/').count('/') + 1
    new_components = new_rel.replace('\\', '/').strip('/').count('/') + 1
    delta = new_components - old_components
    obj['fullpath'] = new_full
    if 'ascendcount_target' in obj and isinstance(obj['ascendcount_target'], int):
        obj['ascendcount_target'] = obj['ascendcount_target'] + delta
    # Re-serialize: keep compact JSON (matches AE format: no spaces after :,)
    new_s = json.dumps(obj, separators=(',', ':'), ensure_ascii=False)
    return new_s.encode('utf-8'), old_rel, new_rel, basename(new_rel)

def rewrite_item_list_content(data, list_offset, manifest_norm, stats, verbose=False):
    """Return new content bytes for an Item LIST (just the content, not the LIST header)."""
    info = parse_chunk_at(data, list_offset)
    tag, size, cs, ce, _ = info
    assert tag == b'LIST' and data[cs:cs+4] == b'Item'
    stats.items_scanned += 1

    # Pass 1: scan to find alas match
    new_basename = None
    old_rel_for_log = None
    new_rel_for_log = None
    new_alas_content = None
    sub_off = cs + 4
    while sub_off < ce:
        sub = parse_chunk_at(data, sub_off)
        if sub is None: break
        s_tag, s_size, s_cs, s_ce, s_next = sub
        if s_tag == b'LIST' and data[s_cs:s_cs+4] == b'Pin ':
            alas_info = find_alas_in_pin(data, sub_off)
            if alas_info:
                _, _, a_cs, a_ce = alas_info
                alas_bytes = bytes(data[a_cs:a_ce])
                new_alas_bytes, old_rel, new_rel, nb = rewrite_alas_json(
                    alas_bytes, manifest_norm, stats
                )
                if old_rel:
                    new_basename = nb
                    old_rel_for_log = old_rel
                    new_rel_for_log = new_rel
                    new_alas_content = new_alas_bytes
                    break
        sub_off = s_next

    if not new_basename:
        # No match in this Item — return content as-is
        return bytes(data[cs:ce])

    stats.items_matched += 1
    if verbose:
        print(f"  Item @{list_offset:,}: {old_rel_for_log} → {new_rel_for_log}")

    # Pass 2: rebuild content with updates
    out = bytearray(b'Item')  # form-type
    basename_updated = False
    alas_updated = False
    sub_off = cs + 4
    while sub_off < ce:
        sub = parse_chunk_at(data, sub_off)
        if sub is None: break
        s_tag, s_size, s_cs, s_ce, s_next = sub
        if s_tag == b'Utf8' and s_size > 0 and not basename_updated:
            # First non-empty Utf8 is the basename
            old_bn = bytes(data[s_cs:s_ce]).decode('utf-8', errors='replace')
            new_bn_bytes = new_basename.encode('utf-8')
            out.extend(build_chunk(b'Utf8', new_bn_bytes))
            basename_updated = True
            stats.utf8_updated += 1
        elif s_tag == b'LIST' and data[s_cs:s_cs+4] == b'Pin ':
            out.extend(rewrite_pin_list(data, sub_off, new_alas_content, stats))
            alas_updated = True
        else:
            # Copy this chunk verbatim (including padding)
            out.extend(bytes(data[sub_off:s_next]))
        sub_off = s_next

    stats.report.append((old_rel_for_log, new_rel_for_log, basename_updated, alas_updated))
    return bytes(out)

def rewrite_pin_list(data, pin_offset, new_alas_content, stats):
    """Return full Pin LIST chunk (tag + size + content + pad) with alas content replaced."""
    info = parse_chunk_at(data, pin_offset)
    tag, size, cs, ce, _ = info
    out = bytearray(b'Pin ')
    sub_off = cs + 4
    while sub_off < ce:
        sub = parse_chunk_at(data, sub_off)
        if sub is None: break
        s_tag, s_size, s_cs, s_ce, s_next = sub
        if s_tag == b'LIST' and data[s_cs:s_cs+4] == b'Als2':
            # Rebuild Als2 LIST with new alas content
            als_out = bytearray(b'Als2')
            inner_off = s_cs + 4
            while inner_off < s_ce:
                inner = parse_chunk_at(data, inner_off)
                if inner is None: break
                i_tag, i_size, i_cs, i_ce, i_next = inner
                if i_tag == b'alas':
                    als_out.extend(build_chunk(b'alas', new_alas_content))
                    stats.alas_updated += 1
                else:
                    als_out.extend(bytes(data[inner_off:i_next]))
                inner_off = i_next
            out.extend(build_chunk(b'LIST', bytes(als_out)))
        else:
            out.extend(bytes(data[sub_off:s_next]))
        sub_off = s_next
    return build_chunk(b'LIST', bytes(out))

def rewrite_chunk(data, offset, manifest_norm, stats, verbose=False):
    """Recursively rewrite a chunk. Return full chunk bytes (tag + size + content + pad)."""
    info = parse_chunk_at(data, offset)
    if info is None:
        return bytes(data[offset:])
    tag, size, cs, ce, next_off = info

    if tag not in LIST_TAGS:
        # Leaf: copy verbatim
        return bytes(data[offset:next_off])

    form = bytes(data[cs:cs+4])
    if form == b'Item':
        new_content = rewrite_item_list_content(data, offset, manifest_norm, stats, verbose)
        return build_chunk(tag, new_content)

    # Generic LIST: recurse into children
    new_content = bytearray(form)
    sub_off = cs + 4
    while sub_off < ce:
        sub = parse_chunk_at(data, sub_off)
        if sub is None: break
        new_content.extend(rewrite_chunk(data, sub_off, manifest_norm, stats, verbose))
        sub_off = sub[4]
    return build_chunk(tag, bytes(new_content))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('aep')
    ap.add_argument('manifest')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    src = Path(args.aep).resolve()
    manifest_p = Path(args.manifest).resolve()
    if not src.exists():
        print(f"ERROR: {src} not found", file=sys.stderr); sys.exit(1)
    if not manifest_p.exists():
        print(f"ERROR: {manifest_p} not found", file=sys.stderr); sys.exit(1)

    print(f"AE project: {src}")
    print(f"Manifest:   {manifest_p}")

    with open(src, 'rb') as f:
        data = f.read()
    print(f"Loaded: {len(data):,} bytes")

    # Verify RIFX
    if data[:4] != b'RIFX':
        print(f"ERROR: not a RIFX file (got {data[:4]!r})", file=sys.stderr)
        sys.exit(1)

    # AE files have RIFX + optional XMP metadata trailer. Preserve trailer.
    rifx_size = struct.unpack('>I', data[4:8])[0]
    rifx_end = 8 + rifx_size
    trailer = bytes(data[rifx_end:])
    if trailer:
        print(f"XMP/trailer: {len(trailer):,} bytes (preserved)")

    manifest = load_manifest(manifest_p)
    manifest_norm = [
        (o, n, normalize_for_compare(o), normalize_for_compare(o).lower())
        for o, n in manifest
    ]
    print(f"Manifest entries: {len(manifest)}")

    stats = Stats()
    new_rifx = rewrite_chunk(data[:rifx_end], 0, manifest_norm, stats, verbose=args.verbose)
    new_data = new_rifx + trailer

    print(f"\nItems scanned: {stats.items_scanned}")
    print(f"Items matched: {stats.items_matched}")
    print(f"Utf8 basename updates: {stats.utf8_updated}")
    print(f"alas JSON updates: {stats.alas_updated}")
    print(f"Size delta: {len(new_data) - len(data):+,} bytes ({len(data):,} → {len(new_data):,})")

    # Report
    report_path = src.parent / (src.stem + '.aep_relink_report.csv')
    try:
        with report_path.open('w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['old_rel', 'new_rel', 'basename_updated', 'alas_updated'])
            for row in stats.report:
                w.writerow(row)
        print(f"Report: {report_path}")
    except OSError as e:
        print(f"WARN: could not write report: {e}", file=sys.stderr)

    if not args.apply:
        print("\nDry-run. Pass --apply to write RELINKED .aep.")
        return

    if stats.items_matched == 0:
        print("No matches — nothing to apply.")
        return

    backup = src.parent / (src.stem + '.ORIGINAL.BACKUP.aep')
    relinked = src.parent / (src.stem + '.RELINKED.aep')
    if not backup.exists():
        try:
            with open(backup, 'wb') as f:
                f.write(data)
            print(f"Backup: {backup}")
        except OSError as e:
            print(f"WARN: backup failed: {e}", file=sys.stderr)
    try:
        with open(relinked, 'wb') as f:
            f.write(new_data)
        print(f"Wrote:  {relinked}")
    except OSError as e:
        print(f"ERROR: write failed: {e}", file=sys.stderr); sys.exit(1)

if __name__ == '__main__':
    main()
