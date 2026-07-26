#!/bin/bash
set -u
OUT=/var/www/sovanisova/works
rm -rf "$OUT"; mkdir -p "$OUT"
LOG=/root/transcode.log
: > "$LOG"

names_for() {
  case "$1" in
    1) echo hybrid ;;
    2) echo fullai ;;
    3) echo cinema ;;
  esac
}

for d in 1 2 3; do
  cat_name=$(names_for "$d")
  mapfile -t FILES < <(find "/root/works_raw/$d" -name '*.MOV' | sort)
  echo "== $cat_name : ${#FILES[@]} files" >> "$LOG"
  i=0
  for f in "${FILES[@]}"; do
    i=$((i + 1))
    n=$(printf '%02d' "$i")
    dst="$OUT/$cat_name-$n.mp4"
    echo "[$(date +%H:%M:%S)] $cat_name-$n <- $(basename "$f")" >> "$LOG"
    # -nostdin обязателен: иначе ffmpeg съедает список файлов из цикла
    ffmpeg -nostdin -y -loglevel error -i "$f" \
      -vf "scale=trunc(min(720\,iw)/2)*2:trunc(min(1280\,ih)/2)*2:force_original_aspect_ratio=decrease" \
      -c:v libx264 -preset veryfast -crf 28 -profile:v high -pix_fmt yuv420p \
      -c:a aac -b:a 96k -movflags +faststart "$dst" >> "$LOG" 2>&1 \
      && echo "   ok $(du -h "$dst" | cut -f1)" >> "$LOG" \
      || echo "   FAIL" >> "$LOG"
    ffmpeg -nostdin -y -loglevel error -ss 1 -i "$dst" -frames:v 1 -q:v 6 "$OUT/$cat_name-$n.jpg" >/dev/null 2>&1
  done
done

echo "DONE $(date +%H:%M:%S)" >> "$LOG"
chmod -R 755 "$OUT"
