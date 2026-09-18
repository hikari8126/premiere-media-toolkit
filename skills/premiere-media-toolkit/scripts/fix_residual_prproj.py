#!/usr/bin/env python3
"""fix_residual_prproj.py — vá 3 chỗ relink_premiere_v2.py chưa chạm tới.

relink_premiere_v2.py đổi ppath + pname ở 3 chỗ chính (Title, MasterClip/Name,
ClipProjectItem/Name). Còn sót:

  1. <SubClip><Name>            — subclip hiện trong Project panel với tên
                                  riêng, KHÔNG đi qua UID chain của MasterClip.
  2. <ClipLoggingInfo><ClipName>— trường metadata logging, nên khớp cho nhất quán.
  3. <RelativePath>             — tính lại theo vị trí MỚI của file project.
                                  Nếu để nguyên, giá trị cũ trỏ vào cấu trúc
                                  không còn tồn tại.

Cách làm: map basename cũ → basename mới lấy từ manifest. Chỉ đổi khi map
KHÔNG mơ hồ (1 tên cũ → đúng 1 tên mới). <RelativePath> tính từ
<ActualMediaFilePath> trong cùng <Media> block.

Usage:
    python3 fix_residual_prproj.py <project.prproj> <manifest.csv> \\
        --project-dir <thư mục project SẼ nằm ở> [--apply] [-v]
"""

import argparse
import collections
import csv
import gzip
import os
import re
import sys
import unicodedata
from pathlib import Path

SUBCLIP_NAME = re.compile(rb'(<SubClip\b[^>]*>)(.*?)(</SubClip>)', re.DOTALL)
NAME_TAG = re.compile(rb'<Name>([^<]*)</Name>')
CLIPNAME_TAG = re.compile(rb'<ClipName>([^<]*)</ClipName>')
MEDIA_BLOCK = re.compile(rb'<Media\b[^>]*\bObjectUID="[^"]+"[^>]*>(.*?)</Media>', re.DOTALL)
ACTUAL_TAG = re.compile(rb'<ActualMediaFilePath>([^<]*)</ActualMediaFilePath>')
RELPATH_TAG = re.compile(rb'<RelativePath>([^<]*)</RelativePath>')

ESC = str.maketrans({'&': '&amp;', '<': '&lt;', '>': '&gt;'})


def esc(s):
    return s.translate(ESC)


def unesc(s):
    return (s.replace('&amp;amp;', '&amp;').replace('&amp;', '&')
             .replace('&lt;', '<').replace('&gt;', '>'))


def norm(s):
    return unicodedata.normalize('NFC', s.replace('\\', '/'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('prproj')
    ap.add_argument('manifest')
    ap.add_argument('--project-dir', required=True,
                    help='thư mục mà file .prproj SẼ nằm ở (để tính RelativePath)')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    src = Path(args.prproj)
    raw = open(src, 'rb').read()
    gz = raw[:2] == b'\x1f\x8b'
    if gz:
        raw = gzip.decompress(raw)
    print(f"Project: {src}  ({len(raw):,} bytes)")

    # map basename cũ → basename mới, bỏ các map mơ hồ
    cand = collections.defaultdict(set)
    for r in csv.DictReader(open(args.manifest, encoding='utf-8')):
        o, n = os.path.basename(r['old_path']), os.path.basename(r['new_path'])
        if o != n:
            cand[norm(o)].add(norm(n))
    bmap = {o: next(iter(v)) for o, v in cand.items() if len(v) == 1}
    ambiguous = {o: v for o, v in cand.items() if len(v) > 1}
    print(f"map tên: {len(bmap):,} rõ ràng, {len(ambiguous)} mơ hồ (bỏ qua)")
    for o, v in list(ambiguous.items())[:5]:
        print(f"    ? {o} → {sorted(v)}")

    proj_dir = norm(str(Path(args.project_dir)))
    n_sub = n_clipname = n_rel = 0
    out = raw

    # 1. <SubClip><Name>
    def fix_subclip(m):
        nonlocal n_sub
        head, body, tail = m.group(1), m.group(2), m.group(3)

        def rep(mm):
            nonlocal n_sub
            cur = norm(unesc(mm.group(1).decode('utf-8')))
            new = bmap.get(cur)
            if not new:
                return mm.group(0)
            n_sub += 1
            return b'<Name>' + esc(new).encode('utf-8') + b'</Name>'
        return head + NAME_TAG.sub(rep, body) + tail
    out = SUBCLIP_NAME.sub(fix_subclip, out)

    # 2. <ClipName> (toàn cục — chỉ nằm trong ClipLoggingInfo)
    def fix_clipname(m):
        nonlocal n_clipname
        cur = norm(unesc(m.group(1).decode('utf-8')))
        new = bmap.get(cur)
        if not new:
            return m.group(0)
        n_clipname += 1
        return b'<ClipName>' + esc(new).encode('utf-8') + b'</ClipName>'
    out = CLIPNAME_TAG.sub(fix_clipname, out)

    # 3. <RelativePath> tính lại từ ActualMediaFilePath trong cùng Media block
    def fix_media(m):
        nonlocal n_rel
        body = m.group(1)
        am = ACTUAL_TAG.search(body)
        if not am:
            return m.group(0)
        abs_path = norm(unesc(am.group(1).decode('utf-8')))
        if not abs_path.startswith('/'):
            return m.group(0)
        try:
            rel = os.path.relpath(abs_path, proj_dir)
        except ValueError:
            return m.group(0)
        # LƯU Ý: mỗi <Media> block có HAI tag <RelativePath> (một trước
        # <FilePath>, một trước <ActualMediaFilePath>). Phải thay CẢ HAI —
        # dùng sub() chứ không phải search().
        new_rel_node = b'<RelativePath>' + esc(rel).encode('utf-8') + b'</RelativePath>'

        def rep_rel(mm):
            nonlocal n_rel
            if norm(unesc(mm.group(1).decode('utf-8'))) == norm(rel):
                return mm.group(0)
            n_rel += 1
            return new_rel_node
        new_body, n_sub_rel = RELPATH_TAG.subn(rep_rel, body)
        if not n_sub_rel:
            return m.group(0)
        whole = m.group(0)
        return whole[:m.start(1) - m.start()] + new_body + whole[m.end(1) - m.start():]
    out = MEDIA_BLOCK.sub(fix_media, out)

    print(f"\n  <SubClip><Name>          đổi: {n_sub:,}")
    print(f"  <ClipName>               đổi: {n_clipname:,}")
    print(f"  <RelativePath>      tính lại: {n_rel:,}")
    print(f"  kích thước: {len(raw):,} → {len(out):,}")

    if not args.apply:
        print("\nDry-run. Thêm --apply để ghi.")
        return
    dest = src.with_name(src.stem + '.FIXED' + src.suffix)
    data = gzip.compress(out, 6) if gz else out
    open(dest, 'wb').write(data)
    print(f"\nWrote: {dest}")


if __name__ == '__main__':
    main()
