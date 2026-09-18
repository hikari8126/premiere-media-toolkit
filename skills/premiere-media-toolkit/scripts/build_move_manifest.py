#!/usr/bin/env python3
"""build_move_manifest.py — dựng manifest A→B khi folder B là bản organize lại của A.

Tiền đề: basename KHÔNG đổi, chỉ cấu trúc folder đổi. A vẫn còn trên máy.

Chiến lược ghép (theo thứ tự ưu tiên):
  1. relative path trùng hệt        → EXACT_REL
  2. basename duy nhất ở cả A và B  → BASENAME
  3. basename trùng nhiều file      → phân giải bằng size; nếu size cũng
                                      trùng thì dùng longest common path
                                      suffix; vẫn bất phân → AMBIGUOUS
  4. không thấy trong B             → MISSING

Chỉ đọc metadata (os.stat), KHÔNG đọc nội dung file — an toàn với Google Drive
stub (không kích hoạt download hàng trăm GB).

Usage:
    python3 build_move_manifest.py <A_root> <B_root> -o manifest.csv [-v]
    tuỳ chọn: --ext mov,mp4   (default: mov,mp4)
"""

import argparse
import csv
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

DEFAULT_EXT = 'mov,mp4'


def norm(s):
    return unicodedata.normalize('NFC', s.replace('\\', '/'))


def scan(root, exts, verbose=False):
    """Trả về list dict: rel, abspath, basename, size."""
    root = Path(root)
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith('.')]
        for fn in filenames:
            if fn.startswith('.') or fn.startswith('._'):
                continue
            if exts and Path(fn).suffix.lower().lstrip('.') not in exts:
                continue
            full = Path(dirpath) / fn
            try:
                size = full.stat().st_size
            except OSError:
                size = -1
            out.append({
                'rel': norm(str(full.relative_to(root))),
                'abs': norm(str(full)),
                'bn': norm(fn),
                'size': size,
            })
    if verbose:
        print(f"  scanned {root}: {len(out)} files", file=sys.stderr)
    return out


ID_SUFFIX_RE = re.compile(r'\s*\[[0-9a-z]{4,12}\]\s*$', re.I)
SEP_RE = re.compile(r'[\s_\-.]+')


def loose_key(bn):
    """Khoá khớp lỏng: bỏ ext, bỏ hậu tố ' [assetid]', đồng nhất mọi separator.

    'A B 场景23-1.mp4'  và  'A_B_场景23-1 [mtb83wi2].mp4'  →  cùng khoá.
    """
    stem = bn.rsplit('.', 1)[0] if '.' in bn else bn
    stem = ID_SUFFIX_RE.sub('', stem)
    return SEP_RE.sub(' ', stem).strip().lower()


def common_suffix_len(a_rel, b_rel):
    """Số path component trùng nhau tính từ phải sang."""
    a = a_rel.lower().split('/')
    b = b_rel.lower().split('/')
    n = 0
    while n < len(a) and n < len(b) and a[-1 - n] == b[-1 - n]:
        n += 1
    return n


def build(a_root, b_root, out_csv, exts, verbose=False):
    a_files = scan(a_root, exts, verbose)
    b_files = scan(b_root, exts, verbose)

    b_by_rel = {f['rel'].lower(): f for f in b_files}
    b_by_bn = defaultdict(list)
    b_by_loose = defaultdict(list)
    for f in b_files:
        b_by_bn[f['bn'].lower()].append(f)
        b_by_loose[loose_key(f['bn'])].append(f)

    rows = []
    stats = defaultdict(int)

    for af in a_files:
        cands = b_by_bn.get(af['bn'].lower(), [])
        loose = False
        if not cands:
            cands = b_by_loose.get(loose_key(af['bn']), [])
            loose = bool(cands)
        status = None
        pick = None

        if not cands:
            status = 'MISSING'
        elif af['rel'].lower() in b_by_rel and b_by_rel[af['rel'].lower()]['bn'].lower() == af['bn'].lower():
            status, pick = 'EXACT_REL', b_by_rel[af['rel'].lower()]
        elif len(cands) == 1:
            status, pick = ('LOOSE' if loose else 'BASENAME'), cands[0]
        else:
            # nhiều ứng viên: lọc theo size trước
            same_size = [c for c in cands if c['size'] == af['size'] and af['size'] >= 0]
            pool = same_size if same_size else cands
            if len(pool) == 1:
                base = 'SIZE' if same_size else 'BASENAME'
                status, pick = (('LOOSE_' + base) if loose else base), pool[0]
            else:
                # phân giải bằng path suffix dài nhất
                scored = sorted(pool, key=lambda c: common_suffix_len(af['rel'], c['rel']), reverse=True)
                top = common_suffix_len(af['rel'], scored[0]['rel'])
                runner = common_suffix_len(af['rel'], scored[1]['rel']) if len(scored) > 1 else -1
                if top > runner:
                    status, pick = ('LOOSE_SUFFIX' if loose else 'SUFFIX'), scored[0]
                else:
                    status = 'AMBIGUOUS'
                    pick = None

        stats[status] += 1
        rows.append({
            'status': status,
            'old_abs': af['abs'],
            'new_abs': pick['abs'] if pick else '',
            'old_rel': af['rel'],
            'new_rel': pick['rel'] if pick else '',
            'size_a': af['size'],
            'size_b': pick['size'] if pick else '',
            'size_match': (('Y' if pick['size'] == af['size'] else 'N') if pick else ''),
            'candidates': '' if pick else ' | '.join(c['rel'] for c in cands[:6]),
        })

    # file chỉ có ở B (không tham chiếu từ A) — thông tin, không đưa vào manifest
    matched_b = {r['new_rel'].lower() for r in rows if r['new_rel']}
    b_only = [f['rel'] for f in b_files if f['rel'].lower() not in matched_b]

    out_csv = Path(out_csv)
    with out_csv.open('w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=[
            'status', 'old_abs', 'new_abs', 'old_rel', 'new_rel',
            'size_a', 'size_b', 'size_match', 'candidates'])
        w.writeheader()
        w.writerows(rows)

    print(f"A: {a_root}")
    print(f"B: {b_root}")
    print(f"\nA files: {len(a_files):,}   B files: {len(b_files):,}")
    print("\n=== Kết quả ghép ===")
    order = ('EXACT_REL', 'BASENAME', 'SIZE', 'SUFFIX',
             'LOOSE', 'LOOSE_SIZE', 'LOOSE_BASENAME', 'LOOSE_SUFFIX',
             'AMBIGUOUS', 'MISSING')
    for k in order:
        if stats[k]:
            print(f"  {k:<10} {stats[k]:>6,}")
    resolved = sum(v for k, v in stats.items() if k not in ('AMBIGUOUS', 'MISSING'))
    print(f"  {'--':<10}")
    print(f"  {'GHÉP ĐƯỢC':<10} {resolved:>6,} / {len(a_files):,}")
    mism = [r for r in rows if r['size_match'] == 'N']
    if mism:
        print(f"\n⚠️  {len(mism)} file ghép được nhưng SIZE LỆCH (nghi bị re-encode / khác bản):")
        for r in mism[:10]:
            print(f"    {r['old_rel']}  ({r['size_a']:,}) → {r['new_rel']}  ({r['size_b']:,})")
    if stats['AMBIGUOUS']:
        print(f"\n⚠️  {stats['AMBIGUOUS']} file bất phân (cần bạn quyết) — xem status=AMBIGUOUS trong CSV")
    print(f"\nChỉ có ở B, không được A tham chiếu: {len(b_only):,}")
    print(f"\nManifest: {out_csv}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument('a_root')
    p.add_argument('b_root')
    p.add_argument('-o', '--out', required=True)
    p.add_argument('--ext', default=DEFAULT_EXT,
                   help=f'phần mở rộng, phẩy phân cách (default: {DEFAULT_EXT}); "all" = mọi file')
    p.add_argument('-v', '--verbose', action='store_true')
    a = p.parse_args()
    exts = None if a.ext.strip().lower() == 'all' else {
        e.strip().lower().lstrip('.') for e in a.ext.split(',') if e.strip()}
    build(a.a_root, a.b_root, a.out, exts, a.verbose)


if __name__ == '__main__':
    main()
