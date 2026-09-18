#!/usr/bin/env python3
"""relink_premiere_v2.py — Premiere Pro project relink (LOGIC v5, FORCEFUL UID-chain, streaming).

Updates a .prproj file based on a rename manifest CSV (old_spath, new_spath):
  - ppath (đường dẫn): update <ActualMediaFilePath>, <FilePath>, <RelativePath>
  - pname (tên hiển thị): update <Title> + <Name> (MasterClip + ClipProjectItem)

Behavior:
  - FORCEFUL: luôn đổi Title + Name thành new_sname, kể cả khi user đã
    rename thủ công trong Premiere.
  - Scope: cả 3 chỗ — Title, MasterClip Name, ClipProjectItem Name.
  - v5: dùng UID chain (MasterClip → Clip → MediaSource → Media) thay vì
    basename matching → KHÔNG còn skip cho ambiguous basenames (1.MOV trùng
    giữa Nora/Tara/Stu vẫn rename đúng theo path mỗi clip trỏ tới).

Strategy: streaming bytes-based (NO XML DOM — handles 700MB+ .prproj):
  - Read prproj as bytes (auto-gunzip).
  - Regex finditer on bytes to find <Media>/<MasterClip>/<ClipProjectItem> blocks.
  - For each block: detect references (ObjectUID/ObjectURef), plan replacements.
  - Apply all replacements in one pass using offset-based segment join.

UID topology (Premiere XML 3-cấp indirection):
  MasterClip <Clips><Clip ObjectRef="N"/></Clips>
    → VideoClip/AudioClip ObjectID=N has <Source ObjectRef="M"/>
    → VideoMediaSource/AudioMediaSource ObjectID=M has <Media ObjectURef="UID"/>
    → Media ObjectUID=UID has <FilePath>, <Title>, etc.
  ClipProjectItem has <MasterClip ObjectURef="MC_UID"/>
    → MC_UID resolves via above.

Handles:
  - gzip'd .prproj (auto-detect + preserve in output)
  - XML encoding (& ↔ &amp;, < ↔ &lt;, etc.)
  - Unicode NFC/NFD (matches both)
  - Path separators (/ vs \\) — preserved per-element

Usage:
    python3 relink_premiere_v2.py <project.prproj> <manifest.csv> [--apply] [-v]

Outputs (same folder as project):
  - <project>.RELINKED.prproj  (only with --apply)
  - <project>.ORIGINAL.BACKUP.prproj  (only with --apply, if not exists)
  - <project>.relink_report.csv  (always)
"""

import argparse
import csv
import gzip
import re
import shutil
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

PATH_TAGS = ('ActualMediaFilePath', 'FilePath', 'RelativePath')

# === I/O ===

def is_gzipped(path):
    with open(path, 'rb') as f:
        return f.read(2) == b'\x1f\x8b'

def read_prproj(path):
    gz = is_gzipped(path)
    if gz:
        with gzip.open(path, 'rb') as f:
            return f.read(), True
    with open(path, 'rb') as f:
        return f.read(), False

def write_prproj(path, data, gz):
    if gz:
        with gzip.open(path, 'wb', compresslevel=6) as f:
            f.write(data)
    else:
        with open(path, 'wb') as f:
            f.write(data)

# === Manifest ===

def load_manifest(csv_path):
    rows = []
    with open(csv_path, encoding='utf-8') as f:
        r = csv.reader(f)
        next(r, None)  # header
        for row in r:
            if len(row) >= 2:
                rows.append((row[0].strip(), row[1].strip()))
    return rows

# === Path utils ===

def normalize_for_compare(p):
    if not p:
        return p
    return unicodedata.normalize('NFC', p.replace('\\', '/'))

def basename(p):
    p = p.replace('\\', '/')
    return p.rsplit('/', 1)[-1] if '/' in p else p

def match_manifest_suffix(current_path, manifest_norm):
    """Find longest manifest entry where current_path ends with old_rel."""
    if not current_path:
        return None
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

def apply_path_replacement(current_text, old_rel, new_rel):
    """Replace suffix old_rel in current_text with new_rel."""
    cur_norm = normalize_for_compare(current_text)
    old_norm = normalize_for_compare(old_rel)
    new_norm = normalize_for_compare(new_rel)
    if not cur_norm.lower().endswith(old_norm.lower()):
        return current_text
    idx = len(cur_norm) - len(old_norm)
    uses_backslash = ('\\' in current_text[idx:])
    prefix = current_text[:idx]
    new_tail = new_norm.replace('/', '\\') if uses_backslash else new_norm
    return prefix + new_tail

# === XML entity utils ===

XML_UNESCAPE_TABLE = (
    ('&amp;amp;', '&amp;'),
    ('&amp;', '&'),
    ('&lt;', '<'),
    ('&gt;', '>'),
    ('&quot;', '"'),
    ('&apos;', "'"),
)

def xml_unescape(s):
    for k, v in XML_UNESCAPE_TABLE:
        s = s.replace(k, v)
    return s

XML_ESCAPE_TABLE = str.maketrans({'&': '&amp;', '<': '&lt;', '>': '&gt;'})

def xml_escape(s):
    return s.translate(XML_ESCAPE_TABLE)

# === Bytes-based block scanners ===

# Find element block opening tag and capture UID + content range
# Using DOTALL to match across newlines.
MEDIA_BLOCK_RE = re.compile(
    rb'<Media\b[^>]*\bObjectUID="([^"]+)"[^>]*>(.*?)</Media>',
    re.DOTALL,
)
MASTERCLIP_BLOCK_RE = re.compile(
    rb'<MasterClip\b[^>]*\bObjectUID="([^"]+)"[^>]*>(.*?)</MasterClip>',
    re.DOTALL,
)
CLIPPROJECTITEM_BLOCK_RE = re.compile(
    rb'<ClipProjectItem\b[^>]*\bObjectUID="([^"]+)"[^>]*>(.*?)</ClipProjectItem>',
    re.DOTALL,
)
OBJECTUREF_RE = re.compile(rb'ObjectURef="([^"]+)"')

# UID-chain scanners (v5 — forceful rename via topology, not basename)
CLIP_OBJ_RE = re.compile(
    rb'<(?:Video|Audio)Clip\b[^>]*\bObjectID="(\d+)"[^>]*>(.*?)</(?:Video|Audio)Clip>',
    re.DOTALL,
)
MEDIASOURCE_OBJ_RE = re.compile(
    rb'<(?:Video|Audio)MediaSource\b[^>]*\bObjectID="(\d+)"[^>]*>(.*?)</(?:Video|Audio)MediaSource>',
    re.DOTALL,
)
SOURCE_REF_RE = re.compile(rb'<Source\s+ObjectRef="(\d+)"\s*/>')
MEDIA_OBJURF_RE = re.compile(rb'<Media\s+ObjectURef="([^"]+)"\s*/>')
# Inside MasterClip → <Clips><Clip Index="N" ObjectRef="M"/></Clips>
MC_CLIPREF_RE = re.compile(rb'<Clip\s+Index="\d+"\s+ObjectRef="(\d+)"\s*/>')
# Inside ClipProjectItem → <MasterClip ObjectURef="MC_UID"/>
CPI_MCREF_RE = re.compile(rb'<MasterClip\s+ObjectURef="([^"]+)"\s*/>')

def find_path_tag_in_block(block_bytes, tag_name):
    """Find <tag>...</tag> in block_bytes. Returns (start, end, content_bytes) or None."""
    pat = re.compile(rb'<' + tag_name.encode() + rb'>([^<]*)</' + tag_name.encode() + rb'>')
    m = pat.search(block_bytes)
    if not m:
        return None
    return (m.start(), m.end(), m.group(1))

# === Main ===

def relink(prproj_path, manifest_path, apply_changes=False, verbose=False,
           paths_only=False):
    src = Path(prproj_path).resolve()
    if not src.exists():
        print(f"ERROR: project not found: {src}", file=sys.stderr)
        sys.exit(1)
    manifest_p = Path(manifest_path).resolve()
    if not manifest_p.exists():
        print(f"ERROR: manifest not found: {manifest_p}", file=sys.stderr)
        sys.exit(1)

    print(f"Project:  {src}")
    print(f"Manifest: {manifest_p}")

    raw, gz = read_prproj(src)
    print(f"Loaded: {'gzip' if gz else 'plain'} ({len(raw):,} bytes raw / decompressed)")

    manifest = load_manifest(manifest_p)
    manifest_norm = [
        (o, n, normalize_for_compare(o), normalize_for_compare(o).lower())
        for o, n in manifest
    ]
    print(f"Manifest entries: {len(manifest)}")

    # =====================================================================
    # PHASE A: Walk all <Media> blocks, plan path-tag + Title replacements.
    # =====================================================================
    matched_media = {}  # uid → {'old_bn', 'new_bn'}
    # changes: list of (absolute_offset_in_raw, old_bytes, new_bytes)
    changes = []
    media_count = 0
    path_updates_planned = 0
    title_updates_planned = 0

    for m in MEDIA_BLOCK_RE.finditer(raw):
        media_count += 1
        uid = m.group(1).decode('utf-8', errors='replace')
        block = m.group(2)
        block_offset = m.start(2)

        last_match = None
        # Path tags
        for tag in PATH_TAGS:
            tag_b = tag.encode()
            pat = re.compile(rb'<' + tag_b + rb'>([^<]*)</' + tag_b + rb'>')
            for em in pat.finditer(block):
                val_enc = em.group(1).decode('utf-8', errors='replace')
                val = xml_unescape(val_enc)
                match = match_manifest_suffix(val, manifest_norm)
                if not match:
                    continue
                old_rel, new_rel = match
                new_val = apply_path_replacement(val, old_rel, new_rel)
                if new_val == val:
                    continue
                # Build old/new bytes
                old_node = f'<{tag}>{val_enc}</{tag}>'.encode('utf-8')
                new_val_enc = xml_escape(new_val)
                new_node = f'<{tag}>{new_val_enc}</{tag}>'.encode('utf-8')
                abs_offset = block_offset + em.start()
                changes.append((abs_offset, old_node, new_node))
                path_updates_planned += 1
                last_match = match

        if last_match:
            old_rel, new_rel = last_match
            old_bn = basename(old_rel)
            new_bn = basename(new_rel)
            matched_media[uid] = {'old_bn': old_bn, 'new_bn': new_bn}
            # Title FORCEFUL update — replace whatever current Title is.
            # paths_only: KHÔNG đụng tên. Bắt buộc dùng cho tham chiếu .aep
            # (Dynamic Link): <Title> ở đó là TÊN COMP dạng
            # "AeriSoft Linked Comp 03/FX.aep", ghi đè bằng basename file sẽ
            # biến mọi comp thành "FX.aep" và mất sạch tên comp.
            if paths_only:
                continue
            title_re = re.compile(rb'<Title>([^<]*)</Title>')
            tm = title_re.search(block)
            if tm:
                title_old_enc = tm.group(1).decode('utf-8', errors='replace')
                new_title_enc = xml_escape(new_bn)
                old_title_node = f'<Title>{title_old_enc}</Title>'.encode('utf-8')
                new_title_node = f'<Title>{new_title_enc}</Title>'.encode('utf-8')
                if old_title_node != new_title_node:
                    abs_offset = block_offset + tm.start()
                    changes.append((abs_offset, old_title_node, new_title_node))
                    title_updates_planned += 1

    print(f"  Scanned <Media> blocks:       {media_count:,}")
    print(f"  Matched Media (by path):      {len(matched_media):,}")
    print(f"  Path-tag updates planned:     {path_updates_planned:,}")
    print(f"  Title updates planned:        {title_updates_planned:,}")

    if paths_only:
        print('  (paths-only: bỏ qua đổi tên hiển thị, bỏ qua Phase B)')
        mc_name_updates = cpi_name_updates = 0

    if not paths_only:
        # =====================================================================
        # PHASE B (v5 — UID-chain): rename MC/CPI display names forceful via topology.
        # Build chain: MC UID → Clip ObjID → MediaSource ObjID → Media UID → new_bn.
        # No basename matching → no ambiguous skip. Each clip resolves to exactly one
        # Media regardless of name collisions (1.MOV in Nora vs Tara vs Stu).
        # =====================================================================

        # Step 1: MediaSource ObjectID → Media UID
        ms_to_media = {}
        for mm in MEDIASOURCE_OBJ_RE.finditer(raw):
            obj_id = mm.group(1).decode()
            mref = MEDIA_OBJURF_RE.search(mm.group(2))
            if mref:
                ms_to_media[obj_id] = mref.group(1).decode('utf-8', errors='replace')

        # Step 2: Clip ObjectID → MediaSource ObjectID
        clip_to_ms = {}
        for mm in CLIP_OBJ_RE.finditer(raw):
            obj_id = mm.group(1).decode()
            sref = SOURCE_REF_RE.search(mm.group(2))
            if sref:
                clip_to_ms[obj_id] = sref.group(1).decode()

        if verbose:
            print(f"  UID chain: MediaSource={len(ms_to_media):,}, Clip={len(clip_to_ms):,}")

        # Step 3: walk MasterClips, resolve to Media UID, plan Name update
        # (bỏ qua hoàn toàn khi paths_only)
        name_re = re.compile(rb'<Name>([^<]*)</Name>')
        mc_uid_to_newbn = {}  # MC UID → new_basename (for CPI lookup)
        mc_count = 0
        mc_name_updates_planned = 0
        mc_unresolved = 0
        for m in MASTERCLIP_BLOCK_RE.finditer(raw):
            mc_count += 1
            mc_uid = m.group(1).decode('utf-8', errors='replace')
            block = m.group(2)
            block_offset = m.start(2)
            cref = MC_CLIPREF_RE.search(block)
            if not cref:
                mc_unresolved += 1
                continue
            clip_id = cref.group(1).decode()
            ms_id = clip_to_ms.get(clip_id)
            if not ms_id:
                mc_unresolved += 1
                continue
            media_uid = ms_to_media.get(ms_id)
            if not media_uid:
                mc_unresolved += 1
                continue
            info = matched_media.get(media_uid)
            if not info:
                # Media not in manifest scope (BGMs, voiceover, etc.) — skip.
                continue
            new_bn = info['new_bn']
            mc_uid_to_newbn[mc_uid] = new_bn
            nm = name_re.search(block)
            if not nm:
                continue
            name_old_enc = nm.group(1).decode('utf-8', errors='replace')
            new_name_enc = xml_escape(new_bn)
            old_node = f'<Name>{name_old_enc}</Name>'.encode('utf-8')
            new_node = f'<Name>{new_name_enc}</Name>'.encode('utf-8')
            if old_node != new_node:
                abs_offset = block_offset + nm.start()
                changes.append((abs_offset, old_node, new_node))
                mc_name_updates_planned += 1

        print(f"  Scanned <MasterClip> blocks:  {mc_count:,}")
        print(f"  MC resolved to Media:         {len(mc_uid_to_newbn):,}")
        print(f"  MC Name updates planned:      {mc_name_updates_planned:,}")
        if mc_unresolved and verbose:
            print(f"  MC unresolved chain:          {mc_unresolved:,}")

        # Step 4: walk ClipProjectItems, resolve via MC UID, plan Name update
        cpi_count = 0
        cpi_name_updates_planned = 0
        for m in CLIPPROJECTITEM_BLOCK_RE.finditer(raw):
            cpi_count += 1
            block = m.group(2)
            block_offset = m.start(2)
            mcref = CPI_MCREF_RE.search(block)
            if not mcref:
                continue
            mc_uid = mcref.group(1).decode('utf-8', errors='replace')
            new_bn = mc_uid_to_newbn.get(mc_uid)
            if not new_bn:
                continue
            nm = name_re.search(block)
            if not nm:
                continue
            name_old_enc = nm.group(1).decode('utf-8', errors='replace')
            new_name_enc = xml_escape(new_bn)
            old_node = f'<Name>{name_old_enc}</Name>'.encode('utf-8')
            new_node = f'<Name>{new_name_enc}</Name>'.encode('utf-8')
            if old_node != new_node:
                abs_offset = block_offset + nm.start()
                changes.append((abs_offset, old_node, new_node))
                cpi_name_updates_planned += 1

        print(f"  Scanned <ClipProjectItem>:    {cpi_count:,}")
        print(f"  CPI Name updates planned:     {cpi_name_updates_planned:,}")

    # =====================================================================
    # Report
    # =====================================================================
    print(f"\n=== Total planned changes: {len(changes):,} ===")

    report_path = src.parent / (src.stem + '.relink_report.csv')
    try:
        with report_path.open('w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['old_rel', 'new_rel', 'matched_media_count'])
            # Reverse lookup: count how many Media matched per manifest entry
            counts = defaultdict(int)
            for uid, info in matched_media.items():
                counts[(info['old_bn'], info['new_bn'])] += 1
            for old, new in manifest:
                ob, nb = basename(old), basename(new)
                w.writerow([old, new, counts.get((ob, nb), 0)])
        print(f"Report: {report_path}")
    except OSError as e:
        print(f"WARN: could not write report: {e}", file=sys.stderr)

    if not apply_changes:
        print("\nDry-run. Pass --apply to write RELINKED .prproj.")
        return

    if not changes:
        print("Nothing to apply.")
        return

    # =====================================================================
    # APPLY — single-pass segment join (memory-friendly)
    # =====================================================================
    print(f"\nApplying {len(changes)} replacements...")
    t0 = time.time()
    # Sort by offset, drop overlaps
    changes.sort(key=lambda c: c[0])
    out = []
    prev_end = 0
    applied = 0
    failed = 0
    for offset, old_b, new_b in changes:
        if offset < prev_end:
            continue  # overlapping (shouldn't happen with our spans)
        # Verify at this offset, raw bytes equal old_b
        if raw[offset:offset+len(old_b)] != old_b:
            failed += 1
            continue
        out.append(raw[prev_end:offset])
        out.append(new_b)
        prev_end = offset + len(old_b)
        applied += 1
    out.append(raw[prev_end:])
    new_raw = b''.join(out)
    print(f"  applied={applied}, failed_locate={failed}, elapsed={time.time()-t0:.1f}s")

    # =====================================================================
    # Write output (backup + new file, may need unique name in sandbox)
    # =====================================================================
    backup = src.parent / (src.stem + '.ORIGINAL.BACKUP.prproj')
    rebased = src.parent / (src.stem + '.RELINKED.prproj')
    if not backup.exists():
        try:
            shutil.copy2(src, backup)
            print(f"Backup:   {backup}")
        except OSError as e:
            print(f"WARN: could not create backup: {e}", file=sys.stderr)
    if rebased.exists():
        stamp = time.strftime('%H%M%S')
        rebased = src.parent / (src.stem + f'.RELINKED.{stamp}.prproj')
    try:
        write_prproj(rebased, new_raw, gz=gz)
        print(f"Wrote:    {rebased}")
    except OSError as e:
        print(f"ERROR: could not write output: {e}", file=sys.stderr)
        sys.exit(1)

def main():
    p = argparse.ArgumentParser(description='Relink Premiere project (forceful, streaming).')
    p.add_argument('prproj')
    p.add_argument('manifest')
    p.add_argument('--apply', action='store_true')
    p.add_argument('--paths-only', action='store_true',
                   help='CHỈ đổi đường dẫn, KHÔNG đụng tên hiển thị. Bắt buộc '
                        'cho tham chiếu .aep/.prproj (Dynamic Link) vì Title ở '
                        'đó là tên comp, không phải tên file.')
    p.add_argument('--verbose', '-v', action='store_true')
    args = p.parse_args()
    relink(args.prproj, args.manifest, apply_changes=args.apply,
           verbose=args.verbose, paths_only=args.paths_only)

if __name__ == '__main__':
    main()
