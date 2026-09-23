#!/usr/bin/env python3
"""audit_relink.py — soát relink nhầm file: khớp tên nhưng KHÁC dung lượng.

Với mỗi tham chiếu đã relink, so size file nguồn với file đích. Lệch size =
gần như chắc chắn là hai file khác nhau, chỉ trùng tên → relink SAI.

Dùng để soát lại các job ĐÃ CHẠY, kể cả job chạy bằng bản skill cũ:

    python3 scripts/audit_relink.py <relink_map.csv>

Bỏ qua .aep/.prproj (bản relink khác size bản gốc là đương nhiên), đường dẫn
tương đối, và thư mục.

⚠️ CHẠY SAU KHI COPY XONG. Chạy giữa lúc đang copy sẽ thấy file dở dang và
báo lệch size nhầm.
"""
import csv, os, sys, collections

m = sys.argv[1]
rows = list(csv.DictReader(open(m, encoding='utf-8')))
ok = mismatch = nocheck = skipped = 0
bad = []
for r in rows:
    new = r.get('new_path') or ''
    old = r.get('old_path') or ''
    st = r.get('status', '')
    if r.get('ext', '').lower() in ('.aep', '.prproj'):
        skipped += 1
        continue
    if not new or st.startswith(('DEAD', 'SKIP', 'PROJECT_FILE')):
        skipped += 1
        continue
    # Bỏ qua các ca KHÔNG kiểm chứng được, tránh báo động giả:
    #  - đường dẫn tương đối: getsize sẽ giải theo thư mục làm việc hiện tại
    #  - thư mục (vd Fills/000000 mà Premiere coi như image sequence):
    #    getsize trả kích thước THƯ MỤC, lệch nhau là bình thường
    if not old.startswith('/'):
        nocheck += 1
        continue
    if os.path.isdir(old) or os.path.isdir(new):
        skipped += 1
        continue
    try:
        so = os.path.getsize(old)
    except OSError:
        nocheck += 1           # nguồn không còn → không kiểm chứng được
        continue
    try:
        sn = os.path.getsize(new)
    except OSError:
        continue
    if so == sn:
        ok += 1
    else:
        mismatch += 1
        bad.append((old, new, so, sn, st))

print(f"  khớp size (an toàn)      : {ok:,}")
print(f"  LỆCH SIZE (nghi sai)     : {mismatch:,}")
print(f"  không kiểm chứng được    : {nocheck:,}  (file nguồn không còn)")
print(f"  bỏ qua (dead/cache/khác) : {skipped:,}")
if bad:
    print("\n  === CHI TIẾT LỆCH SIZE ===")
    for old, new, so, sn, st in bad[:15]:
        print(f"    [{st}] {os.path.basename(old)[:44]}")
        print(f"       nguồn {so/2**20:9.1f} MB  {old.split('Shared drives/')[-1][:66]}")
        print(f"       đích  {sn/2**20:9.1f} MB  {new.split('Shared drives/')[-1][:66]}")
    if len(bad) > 15:
        print(f"    ... và {len(bad)-15} file nữa")
