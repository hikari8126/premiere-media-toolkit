#!/usr/bin/env python3
"""find_project.py — dò thư mục nguồn/đích của một sản phẩm theo TÊN.

Để user chỉ cần gõ "chuyển nhà sản phẩm X" là đủ.

Vì sao cần script: `find` đệ quy trên Google Drive rất chậm (timeout cả phút).
Script chỉ liệt kê ở ĐỘ SÂU CỐ ĐỊNH (drive → project) nên xong trong vài giây.

Usage:
    python3 find_project.py "CurvyFlex"
    python3 find_project.py "CurvyFlex" --json
"""

import argparse
import json
import os
import re
import sys
import unicodedata

DEFAULT_MARKERS = ['samx']
SRC_NAMES = ['Source', 'Sources']
EDIT_NAMES = ['Editing File', 'Editing Files', 'Project', 'Editing']
WRAPPERS = ['Videos', 'Video', '']


def slug(s):
    """Bỏ dấu, bỏ ký tự không phải chữ/số, về chữ thường — để so tên lỏng."""
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]', '', s.lower())


# macOS để lại mount Google Drive cũ mỗi lần đăng nhập lại:
#   GoogleDrive-a@b.com
#   GoogleDrive-a@b.com (17-8-26 10:09)   ← cũ, còn sót
# Máy thật đã thấy 8 mount cho CÙNG một tài khoản. Không lọc thì mỗi project
# bị đếm 8 lần và không chốt được nguồn/đích.
STALE_MOUNT = re.compile(r' \(\d{1,2}-\d{1,2}-\d{2,4} \d{1,2}:\d{2}\)$')


def drive_roots():
    base = os.path.expanduser('~/Library/CloudStorage')
    if not os.path.isdir(base):
        return []
    live, stale = [], []
    for d in sorted(os.listdir(base)):
        sd = os.path.join(base, d, 'Shared drives')
        if not os.path.isdir(sd):
            continue
        (stale if STALE_MOUNT.search(d) else live).append(sd)
    # ưu tiên mount không có hậu tố ngày; chỉ dùng mount cũ khi không còn gì khác
    return live or stale


def listdirs(p):
    try:
        with os.scandir(p) as it:
            return [e for e in it if e.is_dir() and not e.name.startswith('.')]
    except OSError:
        return []


def find_candidates(query, roots, markers):
    q = slug(query)
    hits = []
    seen = set()
    for root in roots:
        for drive in listdirs(root):
            for proj in listdirs(drive.path):
                if q and q not in slug(proj.name):
                    continue
                low = proj.path.lower()
                role = 'ĐÍCH' if any(m in low for m in markers) else 'nguồn'
                key = (drive.name.lower(), proj.name.lower())
                if key in seen:
                    continue
                seen.add(key)
                hits.append({'role': role, 'drive': drive.name,
                             'name': proj.name, 'path': proj.path})
    return hits


def find_subdir(root, names):
    for wrap in WRAPPERS:
        base = os.path.join(root, wrap) if wrap else root
        entries = {e.name.lower(): e.path for e in listdirs(base)}
        for n in names:
            if n.lower() in entries:
                return entries[n.lower()]
    return None


# File do chính skill này sinh ra — không bao giờ là bản gốc để relink.
OURS = ('.relinked.', '.original.backup.', '.fixed.', '.rebased.')


def project_files(root):
    """Tìm .prproj/.aep, tách CHÍNH và PHỤ.

    CHÍNH = nằm NGAY trong thư mục editing. PHỤ = nằm sâu hơn (Auto-Save/,
    Archive/, Element/...).

    Lọc theo VỊ TRÍ chứ không theo TÊN: đã gặp project mà bản đang dùng tên là
    'ZipLacy FX auto-save 2.aep' nhưng nằm ngay gốc Editing File (editor khôi
    phục từ autosave rồi dùng tiếp). Lọc theo tên sẽ bỏ sót đúng file quan
    trọng nhất; lọc theo vị trí thì không.
    """
    edit = find_subdir(root, EDIT_NAMES)
    out = {'editing_dir': edit, 'prproj': [], 'aep': [],
           'prproj_phu': [], 'aep_phu': []}
    if not edit:
        return out
    for dp, dn, fn in os.walk(edit):
        dn[:] = [d for d in dn if not d.startswith('.')
                 and 'previews' not in d.lower()]
        depth = dp[len(edit):].count(os.sep)
        if depth > 2:
            dn[:] = []
        main = (depth == 0)
        for f in fn:
            low = f.lower()
            if any(t in low for t in OURS):
                continue
            if low.endswith('.prproj'):
                out['prproj' if main else 'prproj_phu'].append(os.path.join(dp, f))
            elif low.endswith('.aep'):
                out['aep' if main else 'aep_phu'].append(os.path.join(dp, f))
    def newest(paths):
        return sorted(paths, key=lambda p: -(os.path.getmtime(p)
                                             if os.path.exists(p) else 0))
    for k in ('prproj', 'aep', 'prproj_phu', 'aep_phu'):
        out[k] = newest(out[k])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('query', help='tên sản phẩm, gõ gần đúng cũng được')
    ap.add_argument('--markers', default=','.join(DEFAULT_MARKERS),
                    help='dấu hiệu nhận ra workspace ĐÍCH (mặc định: samx)')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    markers = [m.strip().lower() for m in args.markers.split(',') if m.strip()]
    roots = drive_roots()
    if not roots:
        print("Không thấy thư mục Shared drives nào trong ~/Library/CloudStorage")
        sys.exit(1)

    hits = find_candidates(args.query, roots, markers)
    if args.json:
        print(json.dumps(hits, ensure_ascii=False, indent=2))
        return

    if not hits:
        print(f"Không tìm thấy sản phẩm nào khớp '{args.query}'.")
        print("Thử tên ngắn hơn, hoặc đưa thẳng đường dẫn 2 thư mục.")
        sys.exit(2)

    print(f"=== Tìm '{args.query}' — {len(hits)} kết quả ===")
    for h in hits:
        print(f"  [{h['role']}] {h['drive']} / {h['name']}")

    dests = [h for h in hits if h['role'] == 'ĐÍCH']
    srcs = [h for h in hits if h['role'] == 'nguồn']

    if len(dests) != 1 or len(srcs) != 1:
        print()
        print("KHÔNG tự chốt được cặp nguồn/đích "
              f"({len(srcs)} nguồn, {len(dests)} đích).")
        print("→ Hỏi user chọn, đừng đoán.")
        sys.exit(3)

    a, b = srcs[0]['path'], dests[0]['path']
    print(f"\nNGUỒN : {a}\nĐÍCH  : {b}")

    pf = project_files(a)
    print(f"\nthư mục editing: {pf['editing_dir'] or 'KHÔNG THẤY'}")
    for k, label in (('prproj', '.prproj'), ('aep', '.aep')):
        if pf[k]:
            print(f"  {label} — dùng ({len(pf[k])}, mới nhất trước):")
            for f in pf[k]:
                print(f"    {os.path.basename(f)}")
        else:
            print(f"  {label}: không có file nào ở gốc thư mục editing")
    nphu = len(pf['prproj_phu']) + len(pf['aep_phu'])
    if nphu:
        print(f"  (bỏ qua {nphu} file trong Auto-Save/Archive — nếu bản đang "
              f"dùng nằm trong đó thì phải chỉ định tay)")

    if pf['prproj']:
        print("\n=== Lệnh chạy ===")
        cmd = ['python3 scripts/plan_relink_b.py',
               f'  --root "{b}"', f'  --root "{a}"']
        for f in pf['prproj']:
            cmd.append(f'  --prproj "{f}"')
        for f in pf['aep']:
            cmd.append(f'  --aep "{f}"')
        cmd.append('  --dedupe --outdir <thư mục tạm>')
        print(' \\\n'.join(cmd))


if __name__ == '__main__':
    main()
