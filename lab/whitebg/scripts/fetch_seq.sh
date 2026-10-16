#!/usr/bin/env bash
# 串行续传关键模型：并行 5 路把带宽打散了，反而都卡住
set -u
CLIP="lab/whitebg/models/clip-vit-base-patch32"
HF="https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main"
GH="https://github.com/danielgatis/rembg/releases/download/v0.0.0"
REMBG="$HOME/.rembg/models"

grab () {  # $1=url  $2=目标文件
  local dest="$2"
  [ -s "$dest" ] && { echo "[skip] $(basename "$dest")"; return 0; }
  mkdir -p "$(dirname "$dest")"
  curl -L --retry 8 --retry-delay 2 --retry-all-errors -C - --max-time 3000 \
       -o "$dest.part" "$1" && mv "$dest.part" "$dest" && echo "[done] $(basename "$dest")"
}

grab "$HF/onnx/vision_model_quantized.onnx" "$CLIP/vision_model_quantized.onnx"
grab "$HF/onnx/text_model_quantized.onnx"   "$CLIP/text_model_quantized.onnx"
grab "$GH/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx" "$REMBG/birefnet-general-lite/birefnet-general-lite.onnx"
echo "SEQ FETCH DONE"

# 追加：BiRefNet-general 全量版（MIT 许可，927MB），作为 bria-rmbg 的可商用替代
grab "$GH/BiRefNet-general-epoch_244.onnx" "$REMBG/birefnet-general/birefnet-general.onnx"
