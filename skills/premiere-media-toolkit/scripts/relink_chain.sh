#!/usr/bin/env bash
# relink_chain.sh — chạy trọn chuỗi relink sau khi copy xong.
#
#   relink_chain.sh <plandir> <B_root> <A_prproj...> -- <A_aep...>
#
# Gồm: manifest → relink prproj → vá phần sót → đổi link .aep (paths-only,
# giữ tên comp) → relink .aep → đặt file vào <B>/Asset/project.
set -uo pipefail
S="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLAN="${1:?thiếu plandir}"; B="${2:?thiếu B_root}"; shift 2
PRPROJ=(); AEP=(); mode=p
for a in "$@"; do
  if [ "$a" = "--" ]; then mode=a; continue; fi
  if [ "$mode" = p ]; then PRPROJ+=("$a"); else AEP+=("$a"); fi
done
[ -f "$PLAN/relink_map.csv" ] || { echo "LỖI: không có $PLAN/relink_map.csv"; exit 1; }
W="$PLAN/work"; mkdir -p "$W"
DEST="$B/Asset/project"; mkdir -p "$DEST"

echo "### manifest ###"
python3 "$S/emit_manifest.py" "$PLAN/relink_map.csv" -o "$W/manifest_media.csv" \
        --project-out "$W/manifest_project.csv" || exit 1

for f in "${PRPROJ[@]:-}"; do
  [ -n "$f" ] && [ -f "$f" ] || { echo "BỎ QUA (không có): $f"; continue; }
  n=$(basename "$f"); echo "### $n ###"
  cp "$f" "$W/$n" || continue
  ( cd "$W" && python3 "$S/relink_premiere_v2.py" "$n" manifest_media.csv --apply ) || continue
  R="$W/${n%.prproj}.RELINKED.prproj"
  ( cd "$W" && python3 "$S/fix_residual_prproj.py" "$(basename "$R")" manifest_media.csv \
      --project-dir "$DEST" --apply ) || true
  F="$W/${n%.prproj}.RELINKED.FIXED.prproj"; [ -f "$F" ] || F="$R"
  if [ -s "$W/manifest_project.csv" ] && [ "$(wc -l < "$W/manifest_project.csv")" -gt 1 ]; then
    cp "$F" "$W/tmp_$n"
    ( cd "$W" && python3 "$S/relink_premiere_v2.py" "tmp_$n" manifest_project.csv --paths-only --apply ) || true
    P="$W/tmp_${n%.prproj}.RELINKED.prproj"; [ -f "$P" ] && F="$P"
  fi
  cp "$F" "$DEST/$n" && echo "  → đặt: $DEST/$n"
done

for f in "${AEP[@]:-}"; do
  [ -n "$f" ] && [ -f "$f" ] || continue
  n=$(basename "$f"); echo "### $n ###"
  cp "$f" "$W/$n"
  ( cd "$W" && python3 "$S/relink_aep.py" "$n" manifest_media.csv --apply ) || continue
  R="$W/${n%.aep}.RELINKED.aep"
  if [ -f "$R" ]; then cp "$R" "$DEST/$n"; else cp "$f" "$DEST/$n"; fi
  echo "  → đặt: $DEST/$n"
done
echo "### CHUỖI RELINK XONG ###"
