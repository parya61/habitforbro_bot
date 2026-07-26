#!/bin/bash
set -u
OUT=/var/www/sovanisova/works
LOG=/root/requality.log
: > "$LOG"

names_for() { case "$1" in 1) echo hybrid ;; 2) echo fullai ;; 3) echo cinema ;; esac; }

for d in 1 2 3; do
  cat_name=$(names_for "$d")
  mapfile -t FILES < <(find "/root/works_raw/$d" -name '*.MOV' | sort)
  i=0
  for f in "${FILES[@]}"; do
    i=$((i + 1))
    n=$(printf '%02d' "$i")
    dst="$OUT/$cat_name-$n.mp4"
    tmp="$OUT/.$cat_name-$n.tmp.mp4"
    echo "[$(date +%H:%M:%S)] $cat_name-$n" >> "$LOG"
    # 1080x1920 вместо 720x1280, crf 23 вместо 28
    ffmpeg -nostdin -y -loglevel error -i "$f" \
      -vf "scale=trunc(min(1080\,iw)/2)*2:trunc(min(1920\,ih)/2)*2:force_original_aspect_ratio=decrease" \
      -c:v libx264 -preset veryfast -crf 23 -profile:v high -level 4.1 -pix_fmt yuv420p \
      -c:a aac -b:a 128k -movflags +faststart "$tmp" >> "$LOG" 2>&1 \
      && mv "$tmp" "$dst" && echo "   ok $(du -h "$dst" | cut -f1)" >> "$LOG" \
      || { echo "   FAIL" >> "$LOG"; rm -f "$tmp"; }
    # постер покрупнее
    ffmpeg -nostdin -y -loglevel error -ss 1 -i "$dst" -frames:v 1 -vf scale=540:-2 -q:v 4 "$OUT/$cat_name-$n.jpg" >/dev/null 2>&1
  done
done

# шоурил тоже в 1080
ffmpeg -nostdin -y -loglevel error -i /var/www/sovanisova/video-reel.mp4 \
  -vf scale=1080:1920 -c:v libx264 -preset veryfast -crf 23 -profile:v high -pix_fmt yuv420p \
  -c:a aac -b:a 128k -movflags +faststart /var/www/sovanisova/.reel.tmp.mp4 >> "$LOG" 2>&1 \
  && mv /var/www/sovanisova/.reel.tmp.mp4 /var/www/sovanisova/reel.mp4 \
  && echo "   reel ok $(du -h /var/www/sovanisova/reel.mp4 | cut -f1)" >> "$LOG"
ffmpeg -nostdin -y -loglevel error -ss 1 -i /var/www/sovanisova/reel.mp4 -frames:v 1 -vf scale=720:-2 -q:v 4 /var/www/sovanisova/reel.jpg >/dev/null 2>&1

chmod -R 755 "$OUT"; chmod 755 /var/www/sovanisova/reel.mp4 /var/www/sovanisova/reel.jpg
echo "DONE $(date +%H:%M:%S)" >> "$LOG"
