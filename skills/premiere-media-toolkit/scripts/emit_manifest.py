#!/usr/bin/env python3
"""emit_manifest.py — relink_map.csv → manifest old,new cho script của skill.

relink_premiere_v2.py và relink_aep.py đều nhận CSV 2 cột (old, new) và khớp
theo suffix, nên manifest absolute path dùng trực tiếp được.

Bỏ các dòng DEAD / SKIP_CACHE (không có đích) và các dòng RelativePath
(giá trị tương đối, sẽ được tính lại từ path tuyệt đối).

Usage:
    python3 emit_manifest.py relink_map.csv -o manifest_relink.csv [--include-rel]
"""

import argparse
import csv
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('relink_map')
    ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--include-rel', action='store_true',
                    help='giữ cả dòng chỉ xuất hiện ở RelativePath')
    ap.add_argument('--exclude', action='append', default=[],
                    help='loại dòng có old_path chứa chuỗi này (lặp được) — '
                         'dùng cho các khớp suy đoán mà ta không tin')
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.relink_map, encoding='utf-8')))
    out, skipped, renames, excluded = [], 0, 0, 0
    for r in rows:
        if any(x in r['old_path'] for x in args.exclude):
            excluded += 1
            continue
        if not r['new_path'] or r['status'] in ('DEAD', 'SKIP_CACHE'):
            skipped += 1
            continue
        if not args.include_rel and r['seen_in'] == 'prproj:RelativePath':
            skipped += 1
            continue
        if r['old_path'] == r['new_path']:
            continue
        out.append((r['old_path'], r['new_path']))
        if os.path.basename(r['old_path']) != os.path.basename(r['new_path']):
            renames += 1

    seen = set(); uniq = []
    for o, n in out:
        if o in seen:
            continue
        seen.add(o); uniq.append((o, n))

    with open(args.out, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['old_path', 'new_path'])
        w.writerows(uniq)
    print(f"manifest: {args.out}")
    print(f"  entry:            {len(uniq):,}")
    print(f"  trong đó đổi tên: {renames:,}  (pname sẽ được cập nhật theo B)")
    print(f"  bỏ qua:           {skipped:,}")
    if excluded:
        print(f"  loại theo --exclude: {excluded:,}")


if __name__ == '__main__':
    main()
