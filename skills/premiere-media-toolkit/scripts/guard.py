#!/usr/bin/env python3
"""guard.py — chặn mọi thao tác ghi vào source đã được chuẩn hoá của workspace.

Vì sao cần: `<workspace>/<project>/Sources` là bản source chuẩn dùng chung của
doanh nghiệp. Skill chỉ được ĐỌC nó. Rủi ro lớn nhất KHÔNG phải copy sai đích,
mà là script đổi tên TẠI CHỖ (luồng rename, hiện đóng băng) trỏ nhầm vào đó —
trên Shared Drive thì gần như không cứu được.

Guard chặn theo path, không theo ý định của script, nên không thể lách bằng
cờ `--apply`/`--overwrite` hay bằng cách gọi script khác.

Dùng:
    import guard
    cfg = guard.load_cfg()                      # đọc config.json nếu có
    guard.assert_writable(dest, cfg, 'copy')    # raise SystemExit nếu bị chặn
    guard.assert_tree_writable(root, cfg, 'rename in place')
"""

import json
import os
import sys
import unicodedata

USER_CONFIG_PATH = os.path.expanduser('~/.claude/premiere-media-toolkit/config.json')

DEFAULT_PROTECT_MARKERS = ['samx']
DEFAULT_PROTECT_SUBDIRS = ['sources', 'source']
# Thư mục output của chính skill — mọi thứ bên trong luôn ghi được, kể cả khi
# bên trong có thư mục con tên 'Source' copy từ cây thư mục nguồn.
DEFAULT_OUTPUT_DIRS = ['asset', 'assets', 'output']
# Thư mục source phải nằm SÁT gốc project của workspace mới được coi là source
# chuẩn: <...marker.../><project>/Sources/... → cách marker tối đa 2 cấp.
MAX_DEPTH_FROM_MARKER = 2


def norm(p):
    return unicodedata.normalize('NFC', str(p).replace('\\', '/'))


def load_cfg(path=None):
    if not path:
        here = os.path.dirname(os.path.abspath(__file__))
        # THỨ TỰ QUAN TRỌNG: config của người dùng nằm NGOÀI thư mục plugin.
        # Plugin cài theo version (.../plugin/5.5.0/), update là sang thư mục
        # mới → config để trong đó sẽ mất sau mỗi lần update.
        for guess in ('config.json',
                      USER_CONFIG_PATH,
                      os.path.join(here, 'config.json'),
                      os.path.join(here, '..', 'config.json')):
            if os.path.exists(guess):
                path = guess
                break
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _settings(cfg):
    g = (cfg or {}).get('guards', {})
    markers = [m.lower() for m in g.get('protect_markers',
               (cfg or {}).get('role_detection', {}).get('b_markers',
                                                          DEFAULT_PROTECT_MARKERS))]
    subdirs = [d.lower().strip('/') for d in g.get('protect_subdirs',
                                                   DEFAULT_PROTECT_SUBDIRS)]
    extra = [norm(x).lower().rstrip('/') for x in g.get('protect_paths', [])]
    outdirs = [d.lower().strip('/') for d in g.get('output_dirs', DEFAULT_OUTPUT_DIRS)]
    enabled = g.get('enabled', True)
    return enabled, markers, subdirs, extra, outdirs


def why_protected(path, cfg):
    """Trả lý do bị chặn (str) hoặc None nếu ghi được.

    Chặn khi: path nằm dưới một thư mục source CỦA workspace có marker
    (vd .../SAMX_WORKSPACE/<project>/Sources/...), hoặc nằm dưới một path
    trong guards.protect_paths.
    """
    enabled, markers, subdirs, extra, outdirs = _settings(cfg)
    if not enabled:
        return None
    p = norm(os.path.abspath(path))
    low = p.lower()

    for e in extra:
        if low == e or low.startswith(e + '/'):
            return f"nằm trong guards.protect_paths: {e}"

    parts = low.split('/')
    marker_idx = next((i for i, seg in enumerate(parts)
                       if any(m in seg for m in markers)), None)
    if marker_idx is None:
        return None
    hit_marker = next(m for m in markers if m in parts[marker_idx])

    for j in range(marker_idx + 1,
                   min(marker_idx + 1 + MAX_DEPTH_FROM_MARKER, len(parts))):
        if parts[j] not in subdirs:
            continue
        # nằm trong thư mục output của skill thì không phải source chuẩn
        if any(seg in outdirs for seg in parts[marker_idx + 1:j]):
            continue
        return (f"là source chuẩn của workspace '{hit_marker}' "
                f"(thư mục '{parts[j]}' ngay dưới gốc project) — chỉ được ĐỌC")
    return None


def assert_writable(path, cfg, action='ghi'):
    reason = why_protected(path, cfg)
    if reason:
        sys.stderr.write(
            "\n" + "=" * 70 + "\n"
            f"CHẶN BỞI GUARD: không được {action} vào đây\n"
            f"  path: {path}\n"
            f"  lý do: {reason}\n"
            "Source chuẩn của workspace là bản gốc dùng chung, skill chỉ được đọc.\n"
            "Muốn ghi thì đổi đích (vd sang Asset/), hoặc — nếu thật sự cần —\n"
            "tắt bằng config: guards.enabled = false. KHÔNG nên tắt.\n"
            + "=" * 70 + "\n")
        raise SystemExit(3)


def assert_tree_writable(root, cfg, action='sửa tại chỗ'):
    """Dùng cho script sửa file TẠI CHỖ trong cả cây (organize, rollback)."""
    assert_writable(root, cfg, action)
    # chặn cả khi root là workspace có marker mà bên trong có thư mục source
    enabled, markers, subdirs, _extra, _outdirs = _settings(cfg)
    if not enabled:
        return
    low = norm(os.path.abspath(root)).lower()
    if any(m in low for m in markers):
        try:
            children = [d.lower() for d in os.listdir(root)
                        if os.path.isdir(os.path.join(root, d))]
        except OSError:
            children = []
        inter = [d for d in children if d in subdirs]
        if inter:
            assert_writable(os.path.join(root, inter[0]), cfg, action)


def check_plan(dests, cfg):
    """Kiểm TOÀN BỘ danh sách đích TRƯỚC khi ghi byte đầu tiên.

    Trả list (dest, reason) bị chặn. Gọi hàm này để fail fast, tránh trường hợp
    copy được một nửa rồi mới phát hiện.
    """
    return [(d, r) for d in dests for r in [why_protected(d, cfg)] if r]
