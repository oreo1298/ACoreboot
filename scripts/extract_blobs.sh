#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
#
# Extract IFD / ME / GbE / VBT for the ASUS PRIME B360M-C build into blobs/.
#
# Source priority (first match wins):
#   1. board-data/vendor/*.bin|*.rom that is exactly 16 MiB and starts with
#      an Intel flash descriptor -> your own external-programmer dump.
#      ALWAYS prefer this: its GbE region holds the board's real MAC address
#      and its ME region holds this board's ME state.
#   2. board-data/vendor/*.CAP (ASUS update capsule: 0x800-byte AMI capsule
#      header + full 16 MiB image). Its GbE region carries the ASUS
#      placeholder MAC 88:88:88:88:87:88 (see scripts/gbe_mac.py).
#
# Usage: scripts/extract_blobs.sh [--force]
set -euo pipefail

TOP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="$TOP/board-data/vendor"
BLOBS="$TOP/blobs"
CB="$TOP/coreboot"
IFDTOOL="$CB/util/ifdtool/ifdtool"
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

if [ $FORCE -eq 0 ] && [ -f "$BLOBS/SOURCE.txt" ] && \
   (cd "$BLOBS" && sha256sum -c --quiet SHA256SUMS 2>/dev/null); then
	echo "blobs/ up to date ($(head -1 "$BLOBS/SOURCE.txt"))"
	exit 0
fi

if [ ! -x "$IFDTOOL" ]; then
	make -C "$CB/util/ifdtool" >/dev/null
fi

is_ifd_image() {
	# 16 MiB and flash descriptor signature 0x0FF0A55A at offset 0x10
	[ "$(stat -c %s "$1")" -eq 16777216 ] || return 1
	[ "$(od -An -tx4 -j 16 -N 4 "$1" | tr -d ' ')" = "0ff0a55a" ]
}

SRC=""
KIND=""
for f in "$VENDOR"/*.bin "$VENDOR"/*.rom "$VENDOR"/*.BIN "$VENDOR"/*.ROM; do
	[ -f "$f" ] || continue
	case "$f" in *-spi.bin) continue ;; esac	# our own derived file
	if is_ifd_image "$f"; then SRC="$f"; KIND="spi-dump"; break; fi
done
if [ -z "$SRC" ]; then
	for f in "$VENDOR"/*.CAP "$VENDOR"/*.cap; do
		[ -f "$f" ] || continue
		SRC="$f"; KIND="capsule"; break
	done
fi
[ -n "$SRC" ] || { echo "no vendor image found in $VENDOR" >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
IMG="$WORK/image.bin"
if [ "$KIND" = "capsule" ]; then
	# AMI capsule: header size is the 32-bit value at offset 0x10 (0x800)
	HDR=$((16#$(od -An -tx4 -j 16 -N 4 "$SRC" | tr -d ' ')))
	tail -c +$((HDR + 1)) "$SRC" > "$IMG"
	is_ifd_image "$IMG" || { echo "capsule payload is not a 16 MiB IFD image" >&2; exit 1; }
	cp "$IMG" "$VENDOR/$(basename "${SRC%.*}")-spi.bin"
else
	cp "$SRC" "$IMG"
fi

(cd "$WORK" && "$IFDTOOL" -p cnl -x image.bin >/dev/null)
mkdir -p "$BLOBS"
cp "$WORK/flashregion_0_flashdescriptor.bin" "$BLOBS/descriptor.bin"
cp "$WORK/flashregion_2_intel_me.bin" "$BLOBS/me.bin"
cp "$WORK/flashregion_3_gbe.bin" "$BLOBS/gbe.bin"
python3 -I "$TOP/scripts/extract_vbt.py" "$WORK/flashregion_1_bios.bin" "$BLOBS/vbt.bin"
"$IFDTOOL" -p cnl -d "$IMG" > "$BLOBS/descriptor.txt" 2>&1

{
	echo "source: $(basename "$SRC") ($KIND)"
	echo "source sha256: $(sha256sum "$SRC" | cut -d' ' -f1)"
	echo "gbe mac: $(python3 -I "$TOP/scripts/gbe_mac.py" "$BLOBS/gbe.bin")"
	echo "extracted: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$BLOBS/SOURCE.txt"
(cd "$BLOBS" && sha256sum descriptor.bin me.bin gbe.bin vbt.bin > SHA256SUMS)
cat "$BLOBS/SOURCE.txt"
if grep -q '88:88:88:88:87:88' "$BLOBS/SOURCE.txt"; then
	echo "WARNING: blobs/gbe.bin has the ASUS placeholder MAC. Full-image ROMs" \
	     "will overwrite the board's MAC unless you build with MAC=xx:xx:..." \
	     "or put your own SPI dump into board-data/vendor/." >&2
fi
