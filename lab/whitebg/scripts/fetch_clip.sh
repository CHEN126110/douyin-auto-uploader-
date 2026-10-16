#!/usr/bin/env bash
# 拉取 CLIP ViT-B/32 的 ONNX（int8 量化版，体积可打包）
set -u
BASE="https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main"
DEST="${1:-lab/whitebg/models/clip-vit-base-patch32}"
mkdir -p "$DEST"

get () {  # $1=远端相对路径  $2=本地文件名
  local dest="$DEST/$2"
  if [ -s "$dest" ]; then echo "[skip] $2"; return 0; fi
  curl -L --retry 5 --retry-delay 3 -C - -o "$dest.part" "$BASE/$1" \
    && mv "$dest.part" "$dest" && echo "[done] $2"
}

get onnx/vision_model_quantized.onnx vision_model_quantized.onnx &
get onnx/text_model_quantized.onnx   text_model_quantized.onnx &
get tokenizer.json                   tokenizer.json &
get preprocessor_config.json         preprocessor_config.json &
get config.json                      config.json &
wait
echo "CLIP FETCH DONE"
