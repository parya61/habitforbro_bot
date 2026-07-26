#!/bin/bash
set -u
OUT=/var/www/sovanisova/works
LOG=/root/previews.log
: > "$LOG"

# лёгкие копии для автозапуска прямо на странице:
# 720p, без звука, не длиннее 12 секунд — полное качество остаётся в галерее
for f in "$OUT"/*.mp4; do
  b=$(basename "$f" .mp4)
  case "$b" in *-p) continue ;; esac
  dst="$OUT/$b-p.mp4"
  ffmpeg -nostdin -y -loglevel error -t 12 -i "$f" \
    -vf "scale=trunc(min(720\,iw)/2)*2:trunc(min(1280\,ih)/2)*2:force_original_aspect_ratio=decrease" \
    -an -c:v libx264 -preset veryfast -crf 26 -profile:v high -pix_fmt yuv420p \
    -movflags +faststart "$dst" >> "$LOG" 2>&1 \
    && echo "$b-p $(du -h "$dst" | cut -f1)" >> "$LOG" || echo "$b-p FAIL" >> "$LOG"
done

# шоурил тоже облегчаем для первого экрана (звук оставляем — там есть кнопка)
ffmpeg -nostdin -y -loglevel error -i /var/www/sovanisova/reel.mp4 \
  -vf scale=720:1280 -c:v libx264 -preset veryfast -crf 26 -profile:v high -pix_fmt yuv420p \
  -c:a aac -b:a 96k -movflags +faststart /var/www/sovanisova/reel-p.mp4 >> "$LOG" 2>&1 \
  && echo "reel-p $(du -h /var/www/sovanisova/reel-p.mp4 | cut -f1)" >> "$LOG"

chmod -R 755 "$OUT"; chmod 755 /var/www/sovanisova/reel-p.mp4
echo "DONE" >> "$LOG"
