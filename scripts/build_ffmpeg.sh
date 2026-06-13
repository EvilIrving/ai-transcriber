#!/usr/bin/env bash
#
# 编译 FFmpeg arm64 静态二进制（macOS）
#
# 产物: ffmpeg_bin/ffmpeg-arm64 (~3.3MB)
# 只链接 macOS 系统库，不依赖任何第三方 dylib，可在任意 Mac 上运行。
#
# 用法:  bash scripts/build_ffmpeg.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
cd "$ROOT"

FFMPEG_DIR="$ROOT/ffmpeg_bin"
mkdir -p "$FFMPEG_DIR"

FFMPEG_BIN="$FFMPEG_DIR/ffmpeg-arm64"
FFPROBE_BIN="$FFMPEG_DIR/ffprobe-arm64"
FFMPEG_VER="7.1.1"

echo "🔨 编译 FFmpeg $FFMPEG_VER arm64 静态二进制"
echo ""

# ── 检查架构 ──
ARCH="$(uname -m)"
if [ "$ARCH" != "arm64" ]; then
    echo "❌ 本脚本仅支持 Apple Silicon (arm64)，当前架构: $ARCH"
    exit 1
fi

# ── 跳过已存在的有效缓存 ──
_ffmpeg_arch_ok() {
    [ -f "$1" ] || return 1
    lipo -archs "$1" 2>/dev/null | tr ' ' '\n' | grep -qx "arm64"
}

_no_homebrew_deps() {
    ! otool -L "$1" 2>/dev/null | grep -q '/opt/homebrew\|/usr/local/Cellar'
}

if _ffmpeg_arch_ok "$FFMPEG_BIN" && _no_homebrew_deps "$FFMPEG_BIN" \
   && _ffmpeg_arch_ok "$FFPROBE_BIN" && _no_homebrew_deps "$FFPROBE_BIN"; then
    echo "✅ FFmpeg/FFprobe arm64 静态二进制已就绪，跳过编译"
    echo "   $FFMPEG_BIN ($(ls -lh "$FFMPEG_BIN" | awk '{print $5}'))"
    echo "   $FFPROBE_BIN ($(ls -lh "$FFPROBE_BIN" | awk '{print $5}'))"
    echo ""
    echo "如需重新编译，请先: rm $FFMPEG_BIN $FFPROBE_BIN"
    exit 0
fi

# ── 安装编译依赖 ──
echo "📦 检查编译依赖..."
MISSING_DEPS=""
command -v nasm &>/dev/null || MISSING_DEPS="$MISSING_DEPS nasm"
command -v pkg-config &>/dev/null || MISSING_DEPS="$MISSING_DEPS pkg-config"

if [ -n "$MISSING_DEPS" ]; then
    if ! command -v brew &>/dev/null; then
        echo "❌ 缺少编译依赖 ($MISSING_DEPS)，且未找到 Homebrew"
        echo "   请先安装 Homebrew: https://brew.sh"
        exit 1
    fi
    echo "   安装: $MISSING_DEPS"
    brew install $MISSING_DEPS
    echo ""
fi

# ── 下载源码 ──
FFMPEG_SRC="/tmp/ffmpeg-arm64-static-build/ffmpeg-$FFMPEG_VER"
export TMPDIR=/tmp/ffmpeg-arm64-static-build
mkdir -p "$TMPDIR"

if [ ! -d "$FFMPEG_SRC" ]; then
    echo "📥 下载 ffmpeg-$FFMPEG_VER 源码..."
    curl -sLo "$TMPDIR/ffmpeg-$FFMPEG_VER.tar.xz" \
        "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VER.tar.xz"
    tar xf "$TMPDIR/ffmpeg-$FFMPEG_VER.tar.xz" -C "$TMPDIR"
    echo ""
fi

# ── 编译 ──
cd "$FFMPEG_SRC"
make clean 2>/dev/null || true
rm -f ffbuild/config.mak ffbuild/config.h

echo "⚙️  configure..."
./configure \
    --enable-static \
    --disable-shared \
    --disable-debug \
    --disable-doc \
    --disable-ffplay \
    --disable-xlib \
    --disable-everything \
    --enable-demuxer=mov,m4a,3gp,mp4,m4v,matroska,avi,flv,webm,ogg,wav,aiff,mp3,aac,ac3,wma,flac,alac,pcm_s16le,pcm_s24le \
    --enable-decoder=aac,ac3,alac,flac,mp3,wma,wmav1,wmav2,opus,vorbis,pcm_s16le,pcm_s24le \
    --enable-parser=aac,ac3,flac,mpegaudio,opus,vorbis \
    --enable-protocol=file,pipe \
    --enable-muxer=mp4,m4a,wav,ipod,mp3,adts \
    --enable-encoder=aac,pcm_s16le \
    --enable-filter=aresample,volume,atempo,loudnorm \
    2>&1 | tail -2

echo "🔨 make (jobs: $(sysctl -n hw.ncpu 2>/dev/null || echo 4))..."
make -j"$(sysctl -n hw.ncpu 2>/dev/null || echo 4)" 2>&1 | tail -3

# ── 安装 ──
# ffprobe 默认随 ffmpeg 一起 make 产出（未 --disable-ffprobe）。时长探测/重封装
# 校验依赖它；缺失会让校验静默失效，损坏/截断音频会被直送 Whisper。
cp ffmpeg "$FFMPEG_BIN"
chmod +x "$FFMPEG_BIN"
if [ ! -f ffprobe ]; then
    echo "❌ 未产出 ffprobe，无法继续（时长校验依赖它）"
    exit 1
fi
cp ffprobe "$FFPROBE_BIN"
chmod +x "$FFPROBE_BIN"
cd "$ROOT"

# ── 验证 ──
echo ""
echo "🔍 验证..."
for _bin in "$FFMPEG_BIN" "$FFPROBE_BIN"; do
    echo "   $(basename "$_bin"): 架构 $(lipo -archs "$_bin"), 大小 $(ls -lh "$_bin" | awk '{print $5}')"
    if ! _no_homebrew_deps "$_bin"; then
        echo "❌ 编译产物仍有 Homebrew 依赖！"
        otool -L "$_bin"
        exit 1
    fi
done

echo ""
echo "✅ FFmpeg/FFprobe arm64 静态二进制编译完成"
echo "   路径: $FFMPEG_BIN"
echo "         $FFPROBE_BIN"
