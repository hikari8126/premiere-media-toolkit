#!/usr/bin/env bash
# Cài / cập nhật skill "chuyển nhà" cho Claude Code.
# Dùng:  curl -fsSL https://raw.githubusercontent.com/hikari8126/premiere-media-toolkit/main/install.sh | bash
# Gỡ:    ~/.claude/skills/premiere-media-toolkit  → xoá thư mục này là xong.

set -euo pipefail

REPO="hikari8126/premiere-media-toolkit"
NAME="premiere-media-toolkit"
DEST="$HOME/.claude/skills/$NAME"
CFG_DIR="$HOME/.claude/$NAME"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

say() { printf "  %s\n" "$*"; }

echo
echo "Cài skill: $NAME"
echo

# 1. tải về
if command -v git >/dev/null 2>&1; then
  git clone -q --depth 1 "https://github.com/$REPO.git" "$TMP/repo"
else
  command -v curl >/dev/null 2>&1 || { echo "Cần git hoặc curl. Dừng."; exit 1; }
  curl -fsSL "https://github.com/$REPO/archive/refs/heads/main.tar.gz" -o "$TMP/r.tgz"
  mkdir -p "$TMP/repo"
  tar xzf "$TMP/r.tgz" -C "$TMP/repo" --strip-components=1
fi

SRC="$TMP/repo/skills/$NAME"
[ -d "$SRC" ] || { echo "Không tìm thấy skill trong repo. Dừng."; exit 1; }

# 2. cài / cập nhật (giữ nguyên config cá nhân vì nó nằm ngoài thư mục này)
if [ -d "$DEST" ]; then
  say "đã có bản cũ → cập nhật"
  rm -rf "$DEST"
else
  say "cài mới"
fi
mkdir -p "$(dirname "$DEST")"
cp -R "$SRC" "$DEST"
find "$DEST" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

# 3. config cá nhân — KHÔNG ghi đè nếu đã có
mkdir -p "$CFG_DIR"
if [ -f "$CFG_DIR/config.json" ]; then
  say "giữ nguyên cấu hình cũ: $CFG_DIR/config.json"
else
  cp "$DEST/config.example.json" "$CFG_DIR/config.json"
  say "tạo cấu hình mặc định: $CFG_DIR/config.json"
fi

VER="$(python3 -c "import json,sys;print(json.load(open('$TMP/repo/.claude-plugin/plugin.json'))['version'])" 2>/dev/null || echo "?")"

echo
echo "Xong. Đã cài $NAME v$VER"
echo
say "Skill:  $DEST"
say "Config: $CFG_DIR/config.json"
echo
echo "Cách dùng: mở Claude Code, kéo 2 thư mục project (cũ và mới) vào ô chat"
echo "rồi gõ: chuyển nhà"
echo
echo "Cập nhật sau này: chạy lại đúng lệnh cài ở trên."
echo
