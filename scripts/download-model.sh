#!/usr/bin/env bash
set -euo pipefail

size="${1:-tiny}"
case "$size" in
  tiny)     file="ggml-tiny.bin" ;;
  base)     file="ggml-base.bin" ;;
  small)    file="ggml-small.bin" ;;
  medium)   file="ggml-medium.bin" ;;
  large-v3) file="ggml-large-v3.bin" ;;
  *) echo "Usage: $0 {tiny|base|small|medium|large-v3}" >&2; exit 64 ;;
esac

dest="${XDG_CONFIG_HOME:-$HOME/.config}/asit-ia/models"
mkdir -p "$dest"
target="$dest/$file"

if [[ -f "$target" ]]; then
  echo "Model already exists: $target"
  exit 0
fi

url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$file"
if command -v curl >/dev/null 2>&1; then
  curl -L --fail -o "$target" "$url"
elif command -v wget >/dev/null 2>&1; then
  wget -O "$target" "$url"
else
  echo "curl or wget is required to download $url" >&2
  exit 69
fi

echo "Downloaded $target"
