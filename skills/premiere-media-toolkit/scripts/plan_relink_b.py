#!/usr/bin/env python3
"""plan_relink_b.py — dựng kế hoạch copy A→B và bản đồ relink cho prproj/aep.

Kịch bản: B là bản dup của A rồi organize lại. Cần:
  - video đã có trong B          → trỏ thẳng sang B
  - asset chưa có trong B        → copy vào B/Asset/<bucket>/
  - video trong A/Source, B chưa có → copy vào B/Asset/other/
  - asset của project khác       → copy vào B/Asset/shared/
  - file đã bị xoá khỏi đĩa      → không cứu được, báo DEAD

Khớp path KHÔNG dựa trên prefix (project đã bị di chuyển nhiều lần, tồn tại
nhiều biến thể prefix), mà dựa trên basename + loose key + longest path suffix.

Không ghi gì. Xuất: copy_plan.csv, relink_map.csv.
"""

import argparse
import collections
import csv
import json as _json
import gzip
import json
import os
import re
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import guard
import hashlib
import unicodedata
from pathlib import Path

VIDEO = {'.mov', '.mp4', '.webm'}
IMAGE = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.ai', '.psd', '.tif'}
AUDIO = {'.mp3', '.wav', '.aif', '.aiff', '.m4a'}
IGNORE_EXT = {'.cfa', '.pek'}           # cache Adobe, bỏ hẳn
PROJECT_EXT = {'.aep', '.prproj'}       # file project: xử lý riêng, xem bên dưới

ID_SUFFIX = re.compile(r'\s*\[[0-9a-z]{4,12}\]\s*$', re.I)
SEP = re.compile(r'[\s_\-.]+')
PATH_TAG = re.compile(rb'<(ActualMediaFilePath|FilePath|RelativePath)>([^<]+)</\1>')


def norm(s):
    return unicodedata.normalize('NFC', s.replace('\\', '/'))


def unescape(s):
    return (s.replace('&amp;amp;', '&amp;').replace('&amp;', '&')
             .replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
             .replace('&apos;', "'"))


def loose(bn):
    stem = bn.rsplit('.', 1)[0] if '.' in bn else bn
    return SEP.sub(' ', ID_SUFFIX.sub('', stem)).strip().lower()


def ext_class(p):
    e = os.path.splitext(p)[1].lower()
    if e in VIDEO: return 'V'
    if e in IMAGE: return 'I'
    if e in AUDIO: return 'A'
    return e


def csuf(a, b):
    a = a.lower().split('/'); b = b.lower().split('/'); n = 0
    while n < len(a) and n < len(b) and a[-1 - n] == b[-1 - n]:
        n += 1
    return n


class Index:
    """Index file trong 1 cây thư mục, tra theo basename / loose key."""

    def __init__(self, root, label):
        self.root = Path(root)
        self.label = label
        self.by_bn = collections.defaultdict(list)
        self.by_loose = collections.defaultdict(list)
        self.size = {}
        self.n = 0
        for dp, dn, fn in os.walk(self.root):
            dn[:] = [d for d in dn if not d.startswith('.')]
            for f in fn:
                if f.startswith('.'):
                    continue
                full = Path(dp) / f
                rel = norm(str(full.relative_to(self.root)))
                try:
                    self.size[rel] = full.stat().st_size
                except OSError:
                    self.size[rel] = -1
                self.by_bn[norm(f).lower()].append(rel)
                self.by_loose[loose(f)].append(rel)
                self.n += 1

    def find(self, p, size=None):
        """Trả (rel, kind) hoặc (None, None).

        Phân giải trùng tên theo thứ tự: size khớp → longest path suffix.
        """
        bn = p.rsplit('/', 1)[-1]
        cands, kind = self.by_bn.get(bn.lower()), 'EXACT'
        if not cands:
            kind = 'LOOSE'
            # khớp lỏng phải TRÙNG ĐÚNG phần mở rộng: cùng lớp media là không
            # đủ (png ≠ psd, Premiere xử lý khác nhau)
            want = os.path.splitext(bn)[1].lower()
            cands = [c for c in self.by_loose.get(loose(bn), [])
                     if os.path.splitext(c)[1].lower() == want]
        if not cands:
            return None, None
        if len(cands) == 1:
            return cands[0], kind
        if size is not None and size >= 0:
            same = [c for c in cands if self.size.get(c) == size]
            if len(same) == 1:
                return same[0], kind + '_SIZE'
            if same:
                cands = same
                kind += '_SIZE'
        ranked = sorted(cands, key=lambda r: csuf(p, r), reverse=True)
        if len(ranked) == 1:
            return ranked[0], kind
        if csuf(p, ranked[0]) > csuf(p, ranked[1]):
            return ranked[0], kind + '_SUFFIX'
        return ranked[0], kind + '_AMBIGUOUS'

    def abs_of(self, rel):
        return norm(str(self.root / rel))


def sig(path, n=1 << 20):
    """Chữ ký nội dung: sha256 của 1MB đầu + 1MB cuối."""
    size = os.path.getsize(path)
    h = hashlib.sha256()
    h.update(str(size).encode())
    with open(path, 'rb') as f:
        h.update(f.read(n))
        if size > 2 * n:
            f.seek(-n, 2)
            h.update(f.read(n))
    return h.hexdigest()


def prefix_variants(p):
    """Sinh các biến thể của path, CANONICAL TRƯỚC.

    Thứ tự rất quan trọng: `os.path.exists` trả True cho cả
    `/Volumes/Macintosh HD/Users/...` (mount trỏ về /) và path có `//`
    (POSIX coi `//` = `/`). Nếu yield dạng nguyên văn trước, ta sẽ nhận về
    path KHÔNG canonical, rồi `src.startswith(a_root)` fail và file của A bị
    xếp nhầm vào bucket `shared` với đường dẫn lồng nhau xấu xí — cùng một
    file bị copy 2-3 lần vào 2-3 đích khác nhau.
    """
    seen = set()
    cands = []
    q = p
    if q.startswith('/Volumes/Macintosh HD'):
        q = q[len('/Volumes/Macintosh HD'):] or '/'
    q = re.sub(r'(?<=.)//+', '/', q)          # gộp // nhưng giữ // ở đầu nếu có
    cands.append(q)                            # canonical nhất
    cands.append(re.sub(r'(?<=.)//+', '/', p)) # chỉ gộp //
    cands.append(p)                            # nguyên văn, cuối cùng
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            yield c


def on_disk(p):
    for v in prefix_variants(p):
        if os.path.exists(v):
            return norm(v)
    return None


def load_config(path):
    """Đọc config.json. Không có file → trả {} (dùng mặc định built-in)."""
    if not path:
        # config người dùng để NGOÀI thư mục plugin, xem guard.USER_CONFIG_PATH
        for guess in ('config.json',
                      os.path.expanduser('~/.claude/premiere-media-toolkit/config.json'),
                      os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   '..', 'config.json')):
            if os.path.exists(guess):
                path = guess
                break
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        cfg = _json.load(f)
    print(f"config: {os.path.abspath(path)}")
    return cfg


DEFAULT_B_MARKERS = ['samx']


def detect_roles(roots, cfg):
    """Nhận diện path nào là A (nguồn) và B (đích) theo marker trong config.

    Trả (a_root, b_root). Mơ hồ thì raise — KHÔNG đoán, vì nhận diện sai là
    copy ngược chiều: ghi dữ liệu cũ đè lên thư mục đã organize.
    """
    rd = cfg.get('role_detection', {})
    bm = [x.lower() for x in rd.get('b_markers', DEFAULT_B_MARKERS)]
    am = [x.lower() for x in rd.get('a_markers', [])]
    if len(roots) != 2:
        raise SystemExit(f"ERROR: --root cần đúng 2 đường dẫn, đang có {len(roots)}")
    if not bm and not am:
        raise SystemExit("ERROR: role_detection.b_markers rỗng trong config "
                         "→ không tự nhận diện được. Dùng --a-root/--b-root.")
    if not cfg:
        print(f"(chưa có config.json — dùng marker mặc định: {bm})")

    def hits(path, markers):
        low = path.lower()
        return [m for m in markers if m in low]

    tagged = []
    for r in roots:
        hb, ha = hits(r, bm), hits(r, am)
        if hb and ha:
            raise SystemExit(f"ERROR: path khớp CẢ HAI vai, không đoán được:\n  {r}\n"
                             f"  b_markers khớp: {hb}\n  a_markers khớp: {ha}\n"
                             f"→ chỉ rõ bằng --a-root/--b-root.")
        tagged.append(('B' if hb else ('A' if ha else None), r, hb or ha))

    bs = [t for t in tagged if t[0] == 'B']
    as_ = [t for t in tagged if t[0] == 'A']
    unknown = [t for t in tagged if t[0] is None]

    if len(bs) == 2:
        raise SystemExit("ERROR: CẢ HAI path đều trông như đích (B):\n  "
                         + "\n  ".join(t[1] for t in bs)
                         + "\n→ chỉ rõ bằng --a-root/--b-root.")
    if len(as_) == 2:
        raise SystemExit("ERROR: CẢ HAI path đều trông như nguồn (A):\n  "
                         + "\n  ".join(t[1] for t in as_)
                         + "\n→ chỉ rõ bằng --a-root/--b-root.")
    if len(bs) == 1 and len(unknown) == 1:
        a, b, why = unknown[0][1], bs[0][1], bs[0][2]
    elif len(as_) == 1 and len(unknown) == 1:
        a, b, why = as_[0][1], unknown[0][1], as_[0][2]
    elif len(bs) == 1 and len(as_) == 1:
        a, b, why = as_[0][1], bs[0][1], bs[0][2] + as_[0][2]
    else:
        raise SystemExit("ERROR: không path nào khớp marker nào:\n  "
                         + "\n  ".join(r for r in roots)
                         + "\n→ thêm marker vào config.role_detection, hoặc "
                           "dùng --a-root/--b-root.")

    if cfg.get('role_detection', {}).get('announce', True):
        print("=== Nhận diện vai tự động ===")
        print(f"  khớp marker {why}")
        print(f"  A (NGUỒN, chỉ đọc)      = {a}")
        print(f"  B (ĐÍCH, sẽ được ghi)   = {b}")
        print("  Sai thì Ctrl+C ngay, hoặc chạy lại với --a-root/--b-root.\n")
    return a, b


def group_of(dest, b_root):
    """Nhãn nhóm để thống kê: 2 cấp đầu của đích, tính từ gốc B."""
    rel = dest[len(b_root) + 1:] if dest.startswith(b_root + '/') else dest
    parts = rel.split('/')
    return '/'.join(parts[:2]) if len(parts) > 1 else parts[0]


def sweep_folder(root, dest_root, skip_subdirs=(), only_non_video=False,
                 b_index=None, label=''):
    """Quét NGUYÊN thư mục, sinh cặp (src, dest) giữ nguyên cấu trúc con.

    Khác với luồng theo tham chiếu: lấy cả file project không dùng tới, vì
    team muốn chuyển nguyên folder chứ không chỉ những gì đang online.
    """
    out = []
    root = str(root)
    skip_low = [s.lower() for s in skip_subdirs]
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn
                 if not d.startswith('.') and d.lower() not in skip_low]
        for f in fn:
            if f.startswith('.'):
                continue
            src = norm(os.path.join(dp, f))
            ext = os.path.splitext(f)[1].lower()
            if only_non_video and ext in VIDEO:
                continue
            if ext in IGNORE_EXT or ext in PROJECT_EXT:
                # file project bản gốc KHÔNG copy sang: bản đã relink được
                # ghi riêng vào thư mục project của workspace đích. Copy cả hai
                # sẽ để lại một bản .aep/.prproj cũ trỏ về đường dẫn cũ.
                continue
            rel = src[len(root) + 1:]
            if b_index is not None and b_index.find(src)[0]:
                continue          # B đã có rồi, không copy lại
            out.append((src, f"{dest_root}/{rel}", label))
    return out


# Thư mục "vỏ" — chỉ để tổ chức, không mang thông tin nhận dạng file.
GENERIC_DIRS = {'video', 'videos', 'source', 'sources', 'editing file',
                'editing files', 'project', 'projects', 'output', 'outputs',
                'asset', 'assets'}


def shared_dest(src, b_root, shared_root, max_dirs=2):
    """Đích cho file mượn từ project khác — NGẮN GỌN, không bê cả cây drive.

    Giữ nguyên đường dẫn từ 'Shared drives/' sẽ ra 8-9 cấp, phần lớn là tên
    drive và thư mục vỏ ('Video', 'Editing File') chẳng nhận dạng được gì:

        shared/CPM.Content Storage_Team 01/EaseMotions 2/Video/Editing File/Voice/34x/x.mp3

    Rút còn: <tên project nguồn> + tối đa `max_dirs` thư mục có nghĩa gần file nhất:

        shared/EaseMotions 2/Voice/34x/x.mp3
    """
    after = src.split('Shared drives/', 1)[-1] if 'Shared drives/' in src else src.lstrip('/')
    parts = [x for x in after.split('/') if x]
    fname = parts[-1]
    mid = [x for x in parts[:-1] if x.lower() not in GENERIC_DIRS]
    if len(mid) >= 2:
        mid = mid[1:]              # bỏ tên drive
    top = mid[:1]                  # project nguồn — giữ để biết mượn từ đâu
    tail = mid[1:][-max_dirs:] if len(mid) > 1 else []
    keep = [x for x in top + tail if x]
    return '/'.join([b_root, shared_root] + keep + [fname])


def dest_for(src, ext, a_root, a_source, b_root, cfg, a_edit=None):
    """Đích trong B cho 1 file chưa có trong B. GIỮ NGUYÊN cấu trúc thư mục.

    Không phân loại lại, không đoán bucket — taxonomy của team đã có sẵn trong
    tên thư mục, mọi bảng mapping tự nghĩ ra đều sẽ sai với thư mục chưa gặp
    (vd 'VO - MH' từng bị xếp nhầm vào Music).

      không phải video, trong A   → Asset/<đường dẫn con giữ nguyên>
      video thừa (B chưa có)      → Asset/shared/<đường dẫn con giữ nguyên>
      file của project khác       → Asset/shared/<đường dẫn từ Shared drives>
    """
    st = cfg.get('structure', {})
    non_video_dest = st.get('non_video_dest', 'Asset')
    extra_video_dest = st.get('extra_video_dest', 'Asset/shared')
    external_dest = st.get('external_dest', 'Asset/shared')

    inside_a = src.startswith(a_root + '/')
    if not inside_a:
        return shared_dest(src, b_root, external_dest,
                           max_dirs=st.get('shared_max_dirs', 2))

    # file trong Editing File → đi chung đích với phần quét Editing File,
    # không rải vào Asset/Videos/...
    if a_edit and src.startswith(a_edit + '/'):
        ed = cfg.get('editing_file', {}).get('dest', 'Asset/project/Editing File')
        return f"{b_root}/{ed}/{src[len(a_edit) + 1:]}"

    if src.startswith(a_source + '/'):
        rel = src[len(a_source) + 1:]
    else:
        rel = src[len(a_root) + 1:]
        for lead in ('videos/', 'video/'):
            if rel.lower().startswith(lead):
                rel = rel[len(lead):]
                break

    root = extra_video_dest if ext in VIDEO else non_video_dest
    return f"{b_root}/{root}/{rel}"


def strip_leading(rel, drops):
    parts = rel.split('/')
    while len(parts) > 1 and parts[0].lower() in drops:
        parts = parts[1:]
    return '/'.join(parts)


DROP_DIRS = {'source', 'sources', 'videos', 'editing file', 'voice over', 'voice',
             'bgms', 'bgm', 'ai bgm', 'images', 'image', 'element',
             'motion graphics template media', 'sound effect', 'sfx'}


def extract_prproj(path):
    raw = open(path, 'rb').read()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    out = collections.defaultdict(set)
    for m in PATH_TAG.finditer(raw):
        tag = m.group(1).decode()
        val = unescape(m.group(2).decode('utf-8'))
        if val.isdigit():
            continue
        out[tag].add(norm(val))
    return out, len(raw)


ALAS = re.compile(rb'alas')


def extract_aep(path):
    """Lấy fullpath trong các alas chunk JSON của .aep."""
    data = open(path, 'rb').read()
    found = set()
    for m in re.finditer(rb'\{"alias"', data):
        end = data.find(b'\x00', m.start())
        blob = data[m.start():end if end > 0 else m.start() + 4000]
        try:
            obj = json.loads(blob.decode('utf-8', 'ignore'))
        except Exception:
            continue
        fp = obj.get('fullpath')
        if fp:
            found.add(norm(fp))
    for m in re.finditer(rb'"fullpath"\s*:\s*"((?:[^"\\]|\\.)*)"', data):
        try:
            found.add(norm(json.loads('"' + m.group(1).decode('utf-8', 'ignore') + '"')))
        except Exception:
            pass
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--a-root', help='thư mục A/NGUỒN (chỉ định thẳng)')
    ap.add_argument('--b-root', help='thư mục B/ĐÍCH (chỉ định thẳng)')
    ap.add_argument('--root', action='append', default=[],
                    help='đưa 2 thư mục theo THỨ TỰ BẤT KỲ, skill tự nhận diện '
                         'đâu là nguồn/đích theo config.role_detection '
                         '(vd path chứa "samx" = đích). Lặp 2 lần.')
    ap.add_argument('--prproj', action='append', default=[])
    ap.add_argument('--aep', action='append', default=[])
    ap.add_argument('--outdir', default='.')
    ap.add_argument('--config', default=None,
                    help='config.json để tuỳ biến (bucket, tên thư mục...). '
                         'Không truyền thì tự tìm ./config.json rồi '
                         '<skill>/config.json.')
    ap.add_argument('--keep-source', action='store_true',
                    help='B read-only: KHÔNG copy gì: file B chưa có thì relink '
                         'về đúng path đang tồn tại ở A. Project sẽ phụ thuộc '
                         'cả A và B nhưng online ngay, không cần quyền ghi B.')
    ap.add_argument('--dedupe', action='store_true',
                    help='file sắp copy mà B đã có bản trùng nội dung (hash) → '
                         'relink thẳng vào B thay vì copy')
    args = ap.parse_args()

    cfg = load_config(args.config)

    # --a-root/--b-root chỉ định thẳng luôn thắng; nếu không thì nhận diện từ --root
    if args.a_root and args.b_root:
        a_in, b_in = args.a_root, args.b_root
    elif args.root:
        a_in, b_in = detect_roles([str(Path(r).resolve()) for r in args.root], cfg)
    else:
        raise SystemExit("ERROR: cần (--a-root và --b-root) HOẶC 2 lần --root "
                         "để tự nhận diện.")

    a_root = norm(str(Path(a_in).resolve()))
    b_root = norm(str(Path(b_in).resolve()))
    a_source = a_root + '/Videos/Source'
    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)

    print(f"A = {a_root}\nB = {b_root}\n")
    bi = Index(b_root, 'B'); print(f"B index: {bi.n:,} file")
    ai = Index(a_root, 'A'); print(f"A index: {ai.n:,} file\n")

    a_edit = None
    for name in ('Editing File', 'Editing Files', 'Project', 'Editing'):
        for cand in (os.path.join(a_root, 'Videos', name), os.path.join(a_root, name)):
            if os.path.isdir(cand):
                a_edit = norm(cand)
                break
        if a_edit:
            break

    our_projects = {os.path.basename(x).lower()
                    for x in list(args.prproj) + list(args.aep)}

    refs = {}   # path -> set(nguồn)
    for p in args.prproj:
        tags, size = extract_prproj(p)
        for tag, vals in tags.items():
            for v in vals:
                refs.setdefault(v, set()).add(f'prproj:{tag}')
        print(f"{Path(p).name}: {size:,} bytes, " +
              ", ".join(f"{t}={len(v)}" for t, v in tags.items()))
    for p in args.aep:
        vals = extract_aep(p)
        for v in vals:
            refs.setdefault(v, set()).add('aep')
        print(f"{Path(p).name}: {len(vals)} fullpath")

    print(f"\nTổng tham chiếu duy nhất: {len(refs):,}\n")

    copy_rows, relink_rows = [], []
    stats = collections.Counter()
    bucket_bytes = collections.Counter()
    bucket_files = collections.Counter()
    seen_dest = {}

    for p in sorted(refs):
        ext = os.path.splitext(p)[1].lower()
        srcs = ','.join(sorted(refs[p]))
        is_rel = p.startswith('.') or not p.startswith('/')
        if ext in IGNORE_EXT:
            stats['SKIP_CACHE'] += 1
            relink_rows.append([p, '', 'SKIP_CACHE', ext, srcs]); continue

        if ext in PROJECT_EXT:
            # Premiere link sang comp AE (Dynamic Link) bằng đường dẫn .aep.
            # File project của CHÍNH ta sẽ nằm ở thư mục project của đích sau
            # khi relink → trỏ sang đó. File project của project KHÁC thì để
            # nguyên: ta không relink nó, và nó vẫn nằm đúng chỗ cũ.
            bn = p.rsplit('/', 1)[-1].lower()
            if bn in our_projects:
                sub = cfg.get('output', {}).get('project_subdir', 'Asset/project')
                new_p = f"{b_root}/{sub}/{p.rsplit('/', 1)[-1]}"
                stats['PROJECT_FILE'] += 1
                relink_rows.append([p, new_p, 'PROJECT_FILE', ext, srcs])
            else:
                stats['SKIP_OTHER_PROJECT'] += 1
                relink_rows.append([p, '', 'SKIP_OTHER_PROJECT', ext, srcs])
            continue

        # 1. tìm file thật trên đĩa (để lấy size dùng cho phân giải trùng tên)
        src = None if is_rel else on_disk(p)
        origin = 'literal'
        if not src:
            rel_a, kind_a = ai.find(p)
            if rel_a:
                cand = ai.abs_of(rel_a)
                if os.path.exists(cand):
                    src, origin = cand, 'A:' + kind_a
        ref_size = None
        if src:
            try:
                ref_size = os.stat(src).st_size
            except OSError:
                ref_size = None

        # 2. đã có trong B?
        rel_b, kind = bi.find(p, size=ref_size)
        if rel_b:
            stats['IN_B_' + kind.split('_')[0]] += 1
            relink_rows.append([p, bi.abs_of(rel_b), 'IN_B:' + kind, ext, srcs]); continue

        if not src:
            stats['DEAD'] += 1
            relink_rows.append([p, '', 'DEAD', ext, srcs]); continue

        # 3. đích trong B/Asset
        dest = dest_for(src, ext, a_root, a_source, b_root, cfg, a_edit)
        bucket = group_of(dest, b_root)

        if dest in seen_dest and seen_dest[dest] != src:
            stem, e = os.path.splitext(dest)
            dest = f"{stem}~dup{e}"
        seen_dest[dest] = src

        size = ref_size if ref_size is not None else 0
        if args.keep_source:
            stats['KEEP_A'] += 1
            relink_rows.append([p, src, 'KEEP_A:' + bucket, ext, srcs])
            continue
        stats['COPY'] += 1
        copy_rows.append([src, dest, bucket, size, origin])
        relink_rows.append([p, dest, 'COPY:' + bucket, ext, srcs])

    # ---- Quét nguyên folder (không chỉ file được tham chiếu) ----
    st = cfg.get('structure', {})
    ef = cfg.get('editing_file', {})
    swept = []

    if st.get('sweep_non_video', True):
        swept += sweep_folder(a_source, f"{b_root}/{st.get('non_video_dest','Asset')}",
                              only_non_video=True, b_index=bi, label='sweep:source')

    if ef.get('copy', True):
        if a_edit:
            skip = ef.get('skip_subdirs', [
                'Adobe Premiere Pro Audio Previews',
                'Adobe Premiere Pro Video Previews'])
            swept += sweep_folder(a_edit,
                                  f"{b_root}/{ef.get('dest','Asset/project/Editing File')}",
                                  skip_subdirs=skip, label='sweep:editing')
            print(f"quét Editing File: {a_edit}")
            print(f"  bỏ qua cache: {', '.join(skip)}")

    if swept:
        known = {r[0] for r in copy_rows}
        added = 0
        for src, dest, label in swept:
            if src in known:
                continue
            try:
                sz = os.stat(src).st_size
            except OSError:
                sz = 0
            copy_rows.append([src, dest, group_of(dest, b_root), sz, 'sweep'])
            added += 1
        print(f"quét nguyên folder: thêm {added:,} file ngoài danh sách tham chiếu")

    # dedupe copy plan theo (src,dest)
    uniq = {}
    for r in copy_rows:
        uniq[(r[0], r[1])] = r
    copy_rows = sorted(uniq.values(), key=lambda r: (r[2], r[1]))
    bucket_bytes.clear(); bucket_files.clear()
    for r in copy_rows:
        bucket_bytes[r[2]] += r[3]; bucket_files[r[2]] += 1

    if args.dedupe:
        by_size = collections.defaultdict(list)
        for rel, sz in bi.size.items():
            if sz > 0:
                by_size[sz].append(rel)
        twin_of = {}      # src -> abs path bản trùng trong B
        bsig = {}         # cache chữ ký file B
        for r in copy_rows:
            src, size = r[0], r[3]
            cands = by_size.get(size)
            if not cands:
                continue
            try:
                ssig = sig(src)
            except OSError:
                continue
            for cand in cands:
                cb = bi.abs_of(cand)
                try:
                    if cb not in bsig:
                        bsig[cb] = sig(cb)
                except OSError:
                    continue
                if ssig == bsig[cb]:
                    twin_of[src] = cb
                    break
        if twin_of:
            freed = sum(r[3] for r in copy_rows if r[0] in twin_of)
            dest_to_twin = {r[1]: twin_of[r[0]] for r in copy_rows if r[0] in twin_of}
            copy_rows = [r for r in copy_rows if r[0] not in twin_of]
            for row in relink_rows:
                if row[2].startswith('COPY') and row[1] in dest_to_twin:
                    row[1] = dest_to_twin[row[1]]
                    row[2] = 'IN_B:DEDUPE'
            stats['COPY'] -= len(twin_of)
            stats['IN_B_DEDUPE'] = len(twin_of)
            bucket_bytes.clear(); bucket_files.clear()
            for r in copy_rows:
                bucket_bytes[r[2]] += r[3]; bucket_files[r[2]] += 1
            print(f"\n[dedupe] {len(twin_of)} file đã có bản trùng nội dung trong B "
                  f"→ relink thẳng, tiết kiệm {freed/2**30:.2f} GB\n")

    # GUARD: không được sinh ra đích nằm trong source chuẩn của workspace
    blocked = guard.check_plan([r[1] for r in copy_rows], cfg)
    if blocked:
        print(f"\nGUARD CHẶN {len(blocked)} đích trong kế hoạch:")
        for d, why in blocked[:10]:
            print(f"  {d}\n    → {why}")
        raise SystemExit(3)

    stats['COPY'] = len(copy_rows)   # tính lại sau sweep + dedupe

    cp = outdir / 'copy_plan.csv'
    with cp.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['src', 'dest', 'bucket', 'size', 'matched_via'])
        w.writerows(copy_rows)
    rm = outdir / 'relink_map.csv'
    with rm.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['old_path', 'new_path', 'status', 'ext', 'seen_in'])
        w.writerows(relink_rows)

    print("=== Phân loại tham chiếu ===")
    for k, v in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {k:<16}{v:>6,}")
    print(f"\n=== Kế hoạch copy: {len(copy_rows):,} file, "
          f"{sum(r[3] for r in copy_rows)/2**30:.2f} GB ===")
    for b in sorted(bucket_bytes, key=lambda x: -bucket_bytes[x]):
        print(f"  {b:<26} {bucket_files[b]:>5,} file   {bucket_bytes[b]/2**30:>7.2f} GB")
    amb = [r for r in relink_rows if 'AMBIGUOUS' in r[2]]
    if amb:
        print(f"\n⚠️  {len(amb)} tham chiếu khớp mơ hồ (đã chọn ứng viên gần nhất):")
        for r in amb[:8]:
            print(f"    {r[0].rsplit('/',1)[-1]}  →  {r[1][len(b_root)+1:] if r[1] else '?'}")
    dead = [r for r in relink_rows if r[2] == 'DEAD']
    if dead:
        print(f"\n❌ {len(dead)} tham chiếu KHÔNG cứu được (file đã bị xoá khỏi đĩa) — sẽ offline")
    print(f"\ncopy_plan:   {cp}\nrelink_map:  {rm}")


if __name__ == '__main__':
    main()
