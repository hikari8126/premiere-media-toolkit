#!/usr/bin/env bash
# Cài / cập nhật skill "chuyển nhà" cho Claude Code.
# Dùng:  curl -fsSL https://raw.githubusercontent.com/hikari8126/premiere-media-toolkit/main/install.sh | bash
# Mặc định: tự tìm mọi bản cũ và THAY THẾ (bản cũ được chuyển vào thư mục
#            backup, không xoá thẳng — xem đường dẫn in ra cuối màn hình).
# Giữ bản cũ:  thêm --keep-old
# Gỡ hẳn:      xoá ~/.claude/skills/premiere-media-toolkit

set -euo pipefail

REPO="hikari8126/premiere-media-toolkit"
NAME="premiere-media-toolkit"
DEST="$HOME/.claude/skills/$NAME"
CFG_DIR="$HOME/.claude/$NAME"
REPLACE_OLD=1        # mặc định: thay thế bản cũ
for a in "$@"; do
  [ "$a" = "--keep-old" ] && REPLACE_OLD=0
  [ "$a" = "--remove-old" ] && REPLACE_OLD=1   # giữ tương thích lệnh cũ
done
BACKUP="$HOME/.claude/premiere-media-toolkit/backup-ban-cu/$(date +%Y%m%d-%H%M%S)"
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

# 4. tìm bản cũ cài bằng đường khác (file .skill, app tự quản lý)
OLD=()
while IFS= read -r d; do
  [ "$d" = "$DEST" ] && continue
  OLD+=("$d")
done < <(find "$HOME/.claude" "$HOME/Library/Application Support/Claude" \
           -maxdepth 9 -type d -name "$NAME" 2>/dev/null \
           | grep -v "^$CFG_DIR$" || true)

if [ ${#OLD[@]} -gt 0 ]; then
  echo
  if [ "$REPLACE_OLD" = "1" ]; then
    echo "Tìm thấy ${#OLD[@]} bản cũ cài bằng đường khác → thay thế:"
    mkdir -p "$BACKUP"
    moved=0
    for d in "${OLD[@]}"; do
      # chuyển vào backup thay vì xoá, để còn đường lùi
      tgt="$BACKUP/$(echo "$d" | tr '/' '_')"
      if mv "$d" "$tgt" 2>/dev/null; then
        say "đã chuyển đi: $d"
        moved=$((moved+1))
      else
        say "KHÔNG chuyển được (bỏ qua): $d"
      fi
    done
    if [ "$moved" -gt 0 ]; then
      echo
      say "bản cũ nằm ở: $BACKUP"
      say "yên tâm rồi thì xoá thư mục đó đi"
    else
      rmdir "$BACKUP" 2>/dev/null || true
    fi
  else
    echo "⚠️  Tìm thấy ${#OLD[@]} bản cũ, ĐANG GIỮ LẠI theo --keep-old:"
    for d in "${OLD[@]}"; do say "$d"; done
    echo
    echo "   Hai bản trùng tên khác scope có thể làm Claude nạp nhầm bản cũ."
  fi
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
