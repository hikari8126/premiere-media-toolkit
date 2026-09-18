#!/usr/bin/env python3
"""apply_copy.py — thực thi copy_plan.csv. Dừng giữa đường chạy lại được.

An toàn:
  - KHÔNG bao giờ ghi đè file đã có nội dung khác: dest tồn tại mà size khác
    → báo CONFLICT và bỏ qua (trừ khi --overwrite).
  - dest tồn tại cùng size → coi như đã copy, skip.
  - copy qua file tạm .part rồi rename → không để lại file nửa vời nếu ngắt.
  - verify size sau copy.

Usage:
    python3 apply_copy.py copy_plan.csv            # dry-run
    python3 apply_copy.py copy_plan.csv --apply
    python3 apply_copy.py copy_plan.csv --apply --bucket other
"""

import argparse
import csv
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import guard
import os
import shutil
import sys
import time
from pathlib import Path


def human(n):
    for u in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024:
            return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}PB"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('plan')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--bucket', action='append', default=[],
                    help='chỉ copy bucket này (lặp được)')
    ap.add_argument('--overwrite', action='store_true',
                    help='ghi đè cả khi dest đã có size khác (mặc định: KHÔNG)')
    ap.add_argument('--no-delete-dest', action='store_true',
                    help='đích KHÔNG cho xoá (vd Google Drive role Contributor): '
                         'ghi trực tiếp vào tên cuối, không dùng file tạm .part, '
                         'không dọn file lỗi. Bắt buộc dùng cờ này khi đích là '
                         'shared drive mà ta chỉ có quyền thêm/sửa.')
    ap.add_argument('--log', default='copy_result.csv')
    ap.add_argument('--guard-config', default=None,
                    help='config.json chứa guards.* (mặc định tự tìm)')
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.plan, encoding='utf-8')))
    if args.bucket:
        rows = [r for r in rows if r['bucket'] in args.bucket]

    # GUARD: kiểm TOÀN BỘ đích trước, không ghi byte nào nếu có dòng bị chặn
    gcfg = guard.load_cfg(args.guard_config)
    blocked = guard.check_plan([r['dest'] for r in rows], gcfg)
    if blocked:
        print(f"\nGUARD CHẶN {len(blocked)} đích — KHÔNG ghi gì cả:")
        for d, why in blocked[:10]:
            print(f"  {d}\n    → {why}")
        raise SystemExit(3)

    todo, done, conflict, missing = [], [], [], []
    for r in rows:
        src, dest = r['src'], r['dest']
        if not os.path.exists(src):
            missing.append(r); continue
        if os.path.exists(dest):
            if os.path.getsize(dest) == os.path.getsize(src):
                done.append(r)
            else:
                conflict.append(r)
            continue
        todo.append(r)

    total = sum(os.path.getsize(r['src']) for r in todo)
    print(f"plan: {len(rows):,} dòng")
    print(f"  cần copy:        {len(todo):,}  ({human(total)})")
    print(f"  đã có sẵn (skip):{len(done):,}")
    print(f"  XUNG ĐỘT size:   {len(conflict):,}")
    print(f"  src không tồn tại:{len(missing):,}")
    for r in conflict[:10]:
        print(f"    ! {r['dest']}")
    if not args.apply:
        print("\nDry-run. Thêm --apply để copy thật.")
        return

    log = open(args.log, 'w', newline='', encoding='utf-8')
    w = csv.writer(log); w.writerow(['status', 'src', 'dest', 'bytes', 'sec'])
    for r in done:
        w.writerow(['SKIP_EXISTS', r['src'], r['dest'], r['size'], 0])
    for r in conflict if not args.overwrite else []:
        w.writerow(['CONFLICT', r['src'], r['dest'], r['size'], 0])
    if args.overwrite:
        if args.no_delete_dest:
            print("CHÚ Ý: --overwrite cần quyền xoá/ghi đè, mà --no-delete-dest "
                  "nói là không có. Bỏ qua các dòng CONFLICT.")
        else:
            todo += conflict

    copied = failed = 0
    moved_bytes = 0
    t_all = time.time()
    for i, r in enumerate(todo, 1):
        src, dest = r['src'], r['dest']
        d = Path(dest)
        try:
            guard.assert_writable(dest, gcfg, 'copy')
            d.parent.mkdir(parents=True, exist_ok=True)
            t0 = time.time()
            if args.no_delete_dest:
                # Không có quyền xoá: ghi thẳng tên cuối. Nếu ngắt giữa đường,
                # file dở dang sẽ bị phát hiện ở lần chạy sau (size lệch →
                # CONFLICT) chứ không âm thầm coi là xong.
                shutil.copy2(src, dest)
                ssz, tsz = os.path.getsize(src), os.path.getsize(dest)
                if ssz != tsz:
                    raise IOError(f"size lệch sau copy: {ssz} != {tsz} "
                                  f"(KHÔNG xoá được file dở — cần người có "
                                  f"quyền Content manager dọn: {dest})")
            else:
                tmp = d.with_name(d.name + '.part')
                shutil.copy2(src, tmp)
                ssz, tsz = os.path.getsize(src), os.path.getsize(tmp)
                if ssz != tsz:
                    tmp.unlink(missing_ok=True)
                    raise IOError(f"size lệch sau copy: {ssz} != {tsz}")
                os.replace(tmp, dest)
            dt = time.time() - t0
            copied += 1; moved_bytes += ssz
            w.writerow(['COPIED', src, dest, ssz, f"{dt:.1f}"])
        except Exception as e:
            failed += 1
            w.writerow(['FAILED', src, dest, r['size'], str(e)])
            print(f"  LỖI {Path(src).name}: {e}", file=sys.stderr)
        if i % 25 == 0 or i == len(todo):
            el = time.time() - t_all
            rate = moved_bytes / el if el else 0
            print(f"  [{i}/{len(todo)}] {human(moved_bytes)} / {human(total)}"
                  f"  {human(rate)}/s", flush=True)
        log.flush()
    log.close()
    print(f"\nxong: copy {copied}, lỗi {failed}, bỏ qua {len(done)}")
    print(f"log: {args.log}")


if __name__ == '__main__':
    main()
