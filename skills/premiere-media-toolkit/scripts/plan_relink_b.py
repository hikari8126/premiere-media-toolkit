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
    """NFC + dấu / + rút gọn '..' và './'.

    Bắt buộc rút gọn: .prproj chứa cả path tương đối kiểu
    'Voice Over/8x/../../../Sources/Douyin/x.mp4'. Ghép thẳng vào đích sẽ ra
    'Asset/project/Editing File/Voice Over/8x/../../../Sources/...' — hệ điều
    hành tự giải khi copy nên file rơi vào chỗ khác mà KHÔNG báo lỗi.
    """
    s = unicodedata.normalize('NFC', s.replace('\\', '/'))
    if '/./' in s or '/../' in s or s.endswith(('/.', '/..')):
        collapsed = os.path.normpath(s)
        # normpath làm mất '//' ở đầu (UNC) — không dùng ở đây, nhưng giữ an toàn
        s = collapsed.replace('\\', '/')
    return s


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

    link_unverifiable = False

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
        # ---- SIZE LÀ ĐIỀU KIỆN LOẠI TRỪ, KHÔNG PHẢI ĐIỂM CỘNG ----
        # Biết size nguồn mà KHÔNG ứng viên nào khớp → chúng là file KHÁC,
        # chỉ trùng tên. Trả None để file được COPY từ nguồn, thay vì link
        # bừa sang file lạ.
        #
        # Đây từng là lỗi nghiêm trọng nhất của skill: 'Fiverr/Emma P/1.MOV'
        # (111 MB) bị link sang 'model/Daniela Alvarado/1.mov' (153 MB) —
        # khác người, khác nội dung, sequence sai hoàn toàn mà không báo gì.
        if size is not None and size >= 0:
            same = [c for c in cands if self.size.get(c) == size]
            if not same:
                return None, 'SIZE_CONFLICT'
            if len(same) == 1:
                return same[0], kind + '_SIZE'
            cands = same
            kind += '_SIZE'
        elif len(cands) > 1 and not self.link_unverifiable:
            # Không biết size mà có nhiều ứng viên → không có cơ sở nào để
            # chọn. Đoán theo đường dẫn là cách sinh ra link sai.
            # Đổi hành vi bằng behavior.link_unverifiable = true (KHÔNG khuyến
            # nghị): khi đó vẫn link nhưng gắn nhãn _UNVERIFIED để soát tay.
            return None, 'UNVERIFIABLE'

        if len(cands) == 1:
            return cands[0], kind if size is not None else kind + '_UNVERIFIED'
        ranked = sorted(cands, key=lambda r: csuf(p, r), reverse=True)
        if csuf(p, ranked[0]) > csuf(p, ranked[1]):
            return ranked[0], kind + '_SUFFIX'
        return ranked[0], kind + '_AMBIGUOUS'

    def abs_of(self, rel):
        return norm(str(self.root / rel))


# Trên Google Drive, SEEK TỚI CUỐI file buộc Drive tải gần như cả file.
# Một file 1 GB ở ~700 KB/s = 25 phút cho MỘT file. Nên chỉ đọc đuôi với
# file nhỏ; file lớn thì đọc phần đầu dài hơn và đọc TUẦN TỰ.
TAIL_LIMIT = 64 << 20          # >64 MB thì không đọc đuôi nữa
HEAD_SMALL = 1 << 20
HEAD_LARGE = 4 << 20


def sig(path, verbose=False):
    """Chữ ký nội dung: sha256 của size + phần đầu (+ phần cuối nếu file nhỏ).

    Luôn gộp size vào hash, và chỉ so những file ĐÃ trùng size, nên rủi ro
    trùng chữ ký mà khác nội dung là rất thấp.
    """
    size = os.path.getsize(path)
    h = hashlib.sha256()
    h.update(str(size).encode())
    big = size > TAIL_LIMIT
    n = HEAD_LARGE if big else HEAD_SMALL
    with open(path, 'rb') as f:
        h.update(f.read(n))
        if not big and size > 2 * n:
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
                 b_index=None, label='', alias_map=None, subdirs_only=False):
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
            if subdirs_only and '/' not in rel:
                # file lẻ ngay gốc (vd .prin, .prproj) thuộc về thư mục
                # project, không phải asset — để pass kia lo
                continue
            rel = apply_alias(rel, alias_map)
            if b_index is not None and b_index.find(src)[0]:
                continue          # B đã có rồi, không copy lại
            out.append((src, f"{dest_root}/{rel}", label))
    return out


# Thư mục "vỏ" — chỉ để tổ chức, không mang thông tin nhận dạng file.
GENERIC_DIRS = {'video', 'videos', 'source', 'sources', 'editing file',
                'editing files', 'project', 'projects', 'output', 'outputs',
                'asset', 'assets'}


def find_subdir(root, names, wrappers=('Videos', 'Video', '')):
    """Dò thư mục con theo danh sách tên, không phân biệt hoa thường.

    Mỗi team đặt tên một kiểu: Videos/Source, Video/Sources, Source/,
    Footage/... Hardcode một kiểu là trượt ở project tiếp theo.
    Trả về đường dẫn thật (giữ nguyên hoa thường trên đĩa) hoặc None.
    """
    for wrap in wrappers:
        base = os.path.join(root, wrap) if wrap else root
        if not os.path.isdir(base):
            continue
        try:
            entries = os.listdir(base)
        except OSError:
            continue
        low = {e.lower(): e for e in entries}
        for n in names:
            hit = low.get(n.lower())
            if hit and os.path.isdir(os.path.join(base, hit)):
                return norm(os.path.join(base, hit))
    return None


# Thư mục do Premiere/AE TỰ SINH — đồ nghề, không phải source. Giữ trong thư
# mục project. Mọi thứ CÒN LẠI trong Editing File đều coi là asset và được đưa
# ra Asset/ như thể nó nằm trong Source.
DEFAULT_SYSTEM_SUBDIRS = [
    "Adobe Premiere Pro Audio Previews",
    "Adobe Premiere Pro Video Previews",
    "Adobe Premiere Pro Auto-Save",
    "Adobe Premiere Pro Preview Files",
    "Adobe After Effects Auto-Save",
    "Animation Composer",
    "Premiere Composer Files",
    "Motion Graphics Template Media",
    "Fills",
    "xmlcut",
]

DEFAULT_ALIAS_GROUPS = {
    "BGM":   ["BGM", "BGMs", "Music", "Musics", "Nhac", "Nhạc", "AI BGM"],
    "VO":    ["VO", "Voice", "Voices", "Voice Over", "Voice Overs",
              "Voiceover", "Voiceovers", "VoiceOver"],
    "SFX":   ["SFX", "Sound Effect", "Sound Effects", "SoundFX"],
    "Image": ["Image", "Images", "Anh", "Ảnh", "PNG"],
}


def build_alias_map(roots, cfg, verbose=True):
    """Map 'tên thư mục viết thường' → 'tên chuẩn', CHỈ cho nhóm thực sự trùng.

    Cùng một khái niệm hay nằm ở nhiều thư mục tên khác nhau (BGM / BGMs /
    Music), và mỗi người trong team lại để ở chỗ khác nhau (Source hay
    Editing File). Mặc định `always`: luôn đổi về tên chuẩn, để MỌI project
    sau chuyển nhà đều ra cùng một kiểu thư mục.

    `on_conflict` chỉ gộp khi có từ 2 biến thể cùng tồn tại — dùng khi muốn
    giữ nguyên tên gốc của từng project.

    Bảng alias do NGƯỜI DÙNG khai trong config — skill không tự suy ra nhóm.
    """
    ma = cfg.get('structure', {}).get('merge_aliases', {})
    if ma.get('enabled', True) is False:
        return {}
    mode = ma.get('mode', 'always')
    groups = ma.get('groups', DEFAULT_ALIAS_GROUPS)
    if isinstance(roots, str):
        roots = [roots]
    present = []
    for r in roots:
        if not r:
            continue
        try:
            present += [d for d in os.listdir(r)
                        if os.path.isdir(os.path.join(r, d)) and not d.startswith('.')]
        except OSError:
            continue
    present_low = {d.lower(): d for d in present}

    out = {}
    for canon, variants in groups.items():
        hits = [present_low[v.lower()] for v in variants if v.lower() in present_low]
        if not hits:
            continue
        if mode == 'on_conflict' and len(hits) < 2:
            continue                       # chỉ 1 biến thể → giữ nguyên tên gốc
        changed = [h for h in hits if h != canon]
        if not changed:
            continue                       # đã đúng tên chuẩn, không cần đổi
        for h in changed:
            out[h.lower()] = canon
        if verbose:
            print(f"[gộp thư mục] {', '.join(sorted(hits))} → {canon}")
    return out


def apply_alias(rel, alias_map):
    """Đổi segment ĐẦU của đường dẫn tương đối theo bảng alias."""
    if not alias_map:
        return rel
    parts = rel.split('/')
    parts[0] = alias_map.get(parts[0].lower(), parts[0])
    return '/'.join(parts)


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
    return norm('/'.join([b_root, shared_root] + keep + [fname]))


def dest_for(src, ext, a_root, a_source, b_root, cfg, a_edit=None,
             alias_map=None):
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

    # Trong Editing File có LẪN hai thứ:
    #   - đồ nghề Premiere/AE tự sinh (auto-save, previews, composer...) → giữ
    #     trong thư mục project
    #   - asset thật mà người dùng để ở đó (BGM, VO, Element...) → đưa ra
    #     Asset/ y như thể nó nằm trong Source
    # Nhờ vậy dù team để asset ở Source hay ở Editing File, sau chuyển nhà
    # cũng ra CÙNG MỘT kiểu thư mục.
    if a_edit and src.startswith(a_edit + '/'):
        rel_e = src[len(a_edit) + 1:]
        first = rel_e.split('/')[0]
        sysdirs = [d.lower() for d in cfg.get('editing_file', {}).get(
            'system_subdirs', DEFAULT_SYSTEM_SUBDIRS)]
        if '/' not in rel_e or first.lower() in sysdirs:
            ed = cfg.get('editing_file', {}).get('dest', 'Asset/project/Editing File')
            return norm(f"{b_root}/{ed}/{rel_e}")
        rel_e = apply_alias(rel_e, alias_map)
        root = extra_video_dest if ext in VIDEO else non_video_dest
        return norm(f"{b_root}/{root}/{rel_e}")

    if src.startswith(a_source + '/'):
        rel = src[len(a_source) + 1:]
    else:
        rel = src[len(a_root) + 1:]
        for lead in ('videos/', 'video/'):
            if rel.lower().startswith(lead):
                rel = rel[len(lead):]
                break

    rel = apply_alias(rel, alias_map)
    root = extra_video_dest if ext in VIDEO else non_video_dest
    return norm(f"{b_root}/{root}/{rel}")


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
    ps = cfg.get('project_structure', {})
    src_names = ps.get('source_dir_names', ['Source', 'Sources'])
    edit_names = ps.get('editing_dir_names',
                        ['Editing File', 'Editing Files', 'Project', 'Editing'])
    a_source = find_subdir(a_root, src_names)
    if not a_source:
        raise SystemExit(
            f"ERROR: không tìm thấy thư mục source trong A.\n"
            f"  A = {a_root}\n"
            f"  đã thử: {src_names} (trong A, A/Videos, A/Video)\n"
            f"  → thêm tên thư mục vào config project_structure.source_dir_names")
    print(f"source của A: {a_source}")
    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)

    print(f"A = {a_root}\nB = {b_root}\n")
    Index.link_unverifiable = bool(
        cfg.get('behavior', {}).get('link_unverifiable', False))
    bi = Index(b_root, 'B'); print(f"B index: {bi.n:,} file")
    if Index.link_unverifiable:
        print("  CHÚ Ý: link_unverifiable=true — vẫn link khi không đối chiếu "
              "được size. Rủi ro nhầm nội dung.")
    ai = Index(a_root, 'A'); print(f"A index: {ai.n:,} file\n")

    a_edit = find_subdir(a_root, edit_names)
    if a_edit:
        print(f"editing của A: {a_edit}")
    alias_map = build_alias_map([a_source, a_edit], cfg)

    our_projects = {os.path.basename(x).lower()
                    for x in list(args.prproj) + list(args.aep)}

    name_clash = []   # tham chiếu trùng tên ở đích nhưng khác file
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
        if kind in ('SIZE_CONFLICT', 'UNVERIFIABLE'):
            # Đích CÓ file trùng tên nhưng không xác minh được là cùng nội
            # dung → KHÔNG link. Cho xuống nhánh copy từ nguồn bên dưới.
            stats['TRÙNG TÊN KHÁC FILE' if kind == 'SIZE_CONFLICT'
                  else 'TRÙNG TÊN KHÔNG KIỂM ĐƯỢC'] += 1
            name_clash.append((p, kind))
        elif rel_b:
            stats['IN_B_' + kind.split('_')[0]] += 1
            relink_rows.append([p, bi.abs_of(rel_b), 'IN_B:' + kind, ext, srcs]); continue

        if not src:
            stats['DEAD'] += 1
            relink_rows.append([p, '', 'DEAD', ext, srcs]); continue

        # 3. đích trong B/Asset
        dest = dest_for(src, ext, a_root, a_source, b_root, cfg, a_edit,
                        alias_map)
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
                              only_non_video=True, b_index=bi, label='sweep:source',
                              alias_map=alias_map)

    if ef.get('copy', True):
        if a_edit:
            skip = ef.get('skip_subdirs', [
                'Adobe Premiere Pro Audio Previews',
                'Adobe Premiere Pro Video Previews'])
            sysdirs = ef.get('system_subdirs', DEFAULT_SYSTEM_SUBDIRS)
            # đồ nghề → giữ trong thư mục project
            swept += sweep_folder(a_edit,
                                  f"{b_root}/{ef.get('dest','Asset/project/Editing File')}",
                                  skip_subdirs=skip + [d for d in
                                                       os.listdir(a_edit)
                                                       if os.path.isdir(os.path.join(a_edit, d))
                                                       and d.lower() not in
                                                       [x.lower() for x in sysdirs]],
                                  label='sweep:editing')
            # asset để nhầm trong Editing File → ra Asset/ như source
            swept += sweep_folder(a_edit,
                                  f"{b_root}/{st.get('non_video_dest','Asset')}",
                                  skip_subdirs=skip + list(sysdirs),
                                  only_non_video=True, b_index=bi,
                                  label='sweep:editing-asset', alias_map=alias_map,
                                  subdirs_only=True)
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
        n_need = sum(1 for r in copy_rows if by_size.get(r[3]))
        if n_need:
            print(f"[dedupe] cần đối chiếu {n_need} file có trùng size trong đích "
                  f"(đọc phần đầu, file >64MB không đọc đuôi)")
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

    # ---- Gộp file TRÙNG NỘI DUNG ngay trong kế hoạch ----
    # Dedupe ở trên chỉ so nguồn với ĐÍCH. Trong chính kế hoạch cũng có thể có
    # nhiều file cùng nội dung: hay gặp nhất là cặp '.MP4' và '.mp4' cùng tên
    # cùng size nằm cạnh nhau (Drive phân biệt hoa thường nên cả hai cùng tồn
    # tại). Copy cả hai là nhân đôi dung lượng vô ích.
    if len(copy_rows) > 1:
        by_sz = collections.defaultdict(list)
        for r in copy_rows:
            if r[3] > 0:
                by_sz[r[3]].append(r)
        drop_map = {}          # dest bị bỏ -> dest giữ lại
        for sz, group in by_sz.items():
            if len(group) < 2:
                continue
            seen_sig = {}
            for r in sorted(group, key=lambda x: x[0]):
                try:
                    g = sig(r[0])
                except OSError:
                    continue
                if g in seen_sig:
                    drop_map[r[1]] = seen_sig[g]
                else:
                    seen_sig[g] = r[1]
        if drop_map:
            freed = sum(r[3] for r in copy_rows if r[1] in drop_map)
            copy_rows = [r for r in copy_rows if r[1] not in drop_map]
            for row in relink_rows:
                if row[1] in drop_map:
                    row[1] = drop_map[row[1]]
                    row[2] = row[2] + '+DUP'
            bucket_bytes.clear(); bucket_files.clear()
            for r in copy_rows:
                bucket_bytes[r[2]] += r[3]; bucket_files[r[2]] += 1
            print(f"[trùng trong kế hoạch] bỏ {len(drop_map)} bản sao cùng nội dung "
                  f"→ tiết kiệm {freed/2**30:.2f} GB")

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

    # =====================================================================
    # BÁO CÁO CHUẨN — Claude dán NGUYÊN VĂN khối này, không viết lại.
    # Mục đích: mọi session cho ra cùng một câu chữ, user đọc quen mắt và
    # so sánh được giữa các lần chạy. Diễn giải lại bằng văn model thì mỗi
    # lần một kiểu.
    # =====================================================================
    resolved = sum(v for k, v in stats.items()
                   if k.startswith('IN_B') or k in ('COPY', 'PROJECT_FILE'))
    total_refs = sum(stats.values())
    dead = stats.get('DEAD', 0)
    amb = len([r for r in relink_rows if 'AMBIGUOUS' in r[2]])
    gb = sum(r[3] for r in copy_rows) / 2 ** 30
    maxdepth = max((r[1][len(b_root) + 1:].count('/') for r in copy_rows), default=0)

    print("\n" + "=" * 68)
    print("BÁO CÁO CHUYỂN NHÀ")
    print("=" * 68)
    print(f"Nguồn : {a_root}")
    print(f"Đích  : {b_root}")
    print(f"Tham chiếu : {total_refs:,}   giải được {resolved:,}   "
          f"chết {dead:,}")
    print(f"Sẽ copy    : {len(copy_rows):,} file   {gb:.2f} GB   "
          f"sâu nhất {maxdepth} cấp")
    print("Phân bổ    : " + (", ".join(
        f"{b} {bucket_files[b]}" for b in sorted(bucket_bytes,
                                                 key=lambda x: -bucket_bytes[x])[:5])
        or "(không có gì để copy)"))

    flags = []
    if dead:
        flags.append(("MEDIA CHẾT", f"{dead:,} tham chiếu không tìm thấy file ở bất kỳ đâu",
                      "Những file này đã offline TỪ TRƯỚC, không phải do lần chuyển này. "
                      "Muốn cứu phải lấy từ Drive trash / version history."))
    if amb:
        flags.append(("KHỚP MƠ HỒ", f"{amb} tham chiếu trùng tên, đã chọn ứng viên gần nhất",
                      "Kiểm cột status=*AMBIGUOUS* trong relink_map.csv nếu thấy nghi."))
    n_clash = stats.get('TRÙNG TÊN KHÁC FILE', 0)
    n_unver = stats.get('TRÙNG TÊN KHÔNG KIỂM ĐƯỢC', 0)
    if n_clash:
        flags.append(("TRÙNG TÊN KHÁC FILE",
                      f"{n_clash:,} tham chiếu có file TRÙNG TÊN ở đích nhưng "
                      f"KHÁC dung lượng",
                      "Đã KHÔNG link sang đó — copy bản đúng từ nguồn. Nếu link "
                      "bừa thì sequence sẽ chạy nhầm nội dung."))
    if n_unver:
        flags.append(("TRÙNG TÊN KHÔNG KIỂM ĐƯỢC",
                      f"{n_unver:,} tham chiếu trùng tên nhưng file nguồn không "
                      f"còn để đối chiếu",
                      "Đã KHÔNG link. Kiểm cột status trong relink_map.csv."))
    if maxdepth >= 8:
        flags.append(("CÂY SÂU", f"đích sâu tới {maxdepth} cấp",
                      "Xem lại structure.shared_max_dirs nếu thấy thừa."))
    if not copy_rows:
        flags.append(("KHÔNG CÓ GÌ ĐỂ COPY", "mọi thứ đã có sẵn ở đích", ""))

    if flags:
        print("-" * 68)
        print("CẦN LƯU Ý")
        for name, what, note in flags:
            print(f"  [{name}] {what}")
            if note:
                print(f"      → {note}")
    else:
        print("-" * 68)
        print("KHÔNG CÓ BẤT THƯỜNG")

    print("-" * 68)
    print("CHƯA GHI GÌ. Xác nhận để chạy apply (copy → relink → đặt file vào đích).")
    print("=" * 68)


if __name__ == '__main__':
    main()
