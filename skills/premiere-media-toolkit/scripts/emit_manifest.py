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
    ap.add_argument('--project-out', default=None,
                    help='file riêng cho tham chiếu .aep/.prproj. Chúng PHẢI '
                         'relink bằng --paths-only vì <Title> ở đó là tên comp, '
                         'không phải tên file. Không truyền thì các dòng này bị '
                         'LOẠI khỏi manifest chính cho an toàn.')
    ap.add_argument('--include-rel', action='store_true',
                    help='giữ cả dòng chỉ xuất hiện ở RelativePath')
    ap.add_argument('--exclude', action='append', default=[],
                    help='loại dòng có old_path chứa chuỗi này (lặp được) — '
                         'dùng cho các khớp suy đoán mà ta không tin')
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.relink_map, encoding='utf-8')))
    out, skipped, renames, excluded = [], 0, 0, 0
    project_rows = []
    for r in rows:
        if r['status'] == 'PROJECT_FILE':
            if r['new_path'] and r['old_path'] != r['new_path']:
                project_rows.append((r['old_path'], r['new_path']))
            continue
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
    if args.project_out:
        seen_p = set(); uniq_p = []
        for o, n in project_rows:
            if o in seen_p:
                continue
            seen_p.add(o); uniq_p.append((o, n))
        with open(args.project_out, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['old_path', 'new_path'])
            w.writerows(uniq_p)
        print(f"manifest file project: {args.project_out}  ({len(uniq_p)} entry)")
        print("  → chạy relink_premiere_v2.py với --paths-only cho file này")
    elif project_rows:
        print(f"CHÚ Ý: bỏ {len(project_rows)} tham chiếu .aep/.prproj khỏi manifest "
              f"chính. Dùng --project-out để relink chúng bằng --paths-only.")

    print(f"manifest: {args.out}")
    print(f"  entry:            {len(uniq):,}")
    print(f"  trong đó đổi tên: {renames:,}  (pname sẽ được cập nhật theo B)")
    print(f"  bỏ qua:           {skipped:,}")
    if excluded:
        print(f"  loại theo --exclude: {excluded:,}")


if __name__ == '__main__':
    main()
