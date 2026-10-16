#!/usr/bin/env bash
# 并行拉取 rembg ONNX 模型到 pooch 缓存目录（~/.u2net/models/<name>/<name>.onnx）
set -u
BASE="https://github.com/danielgatis/rembg/releases/download/v0.0.0"
HOME_DIR="${REMBG_HOME:-$HOME/.rembg}/models"

fetch () {  # $1=session名  $2=release文件名
  local name="$1" remote="$2"
  local dir="$HOME_DIR/$name"
  mkdir -p "$dir"
  local dest="$dir/$name.onnx"
  if [ -s "$dest" ]; then echo "[skip] $name 已存在"; return 0; fi
  curl -L --retry 5 --retry-delay 3 -C - -o "$dest.part" "$BASE/$remote" \
    && mv "$dest.part" "$dest" && echo "[done] $name"
}

fetch u2net_cloth_seg      u2net_cloth_seg.onnx &
fetch isnet-general-use    isnet-general-use.onnx &
fetch birefnet-general-lite BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx &
wait
echo "ALL FETCH DONE"
