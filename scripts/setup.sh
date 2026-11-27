#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
#
# Prepare ./coreboot for the ASUS PRIME B360M-C port. Idempotent.
#
#  1. host packages (apt, only if something is missing and we are root)
#  2. coreboot at the pinned commit (shallow), branch asus-prime-b360m-c
#  3. only the needed submodules (shallow)
#  4. patches/*.patch applied with git am (re-applied only if they changed)
#  5. toolchain: coreboot crossgcc i386 + nasm + iasl (coreboot tarball mirror)
#  6. blobs/ from board-data/vendor (scripts/extract_blobs.sh)
#
# Environment:
#   TOOLCHAIN=crossgcc (default) | system   system = distro gcc/gnat/iasl,
#                                            build.sh then sets CONFIG_ANY_TOOLCHAIN
#   FORCE=1   discard local changes in ./coreboot when (re)applying patches
set -euo pipefail

TOP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CB="$TOP/coreboot"
COREBOOT_COMMIT=c49935a44f99585488dec654bd4f3eefe262160c	# main, 2026-11-26
COREBOOT_URLS="https://review.coreboot.org/coreboot.git https://github.com/coreboot/coreboot.git"
BRANCH=asus-prime-b360m-c
SUBMODULES="3rdparty/fsp 3rdparty/intel-microcode 3rdparty/libgfxinit 3rdparty/libhwbase 3rdparty/vboot"
TOOLCHAIN="${TOOLCHAIN:-crossgcc}"
JOBS="${JOBS:-$(nproc)}"
mkdir -p "$TOP/logs"

log() { echo "==> $*"; }

# ---------------------------------------------------------------- 1. packages
PKGS="git make gcc g++ gnat bison flex m4 pkg-config zlib1g-dev libssl-dev uuid-dev
      libncurses-dev libelf-dev curl xz-utils bzip2 unzip python3 acpica-tools nasm
      libpci-dev golang-go"
need_pkgs=0
for c in git make gcc gnat bison flex m4 pkg-config curl python3 xz; do
	command -v "$c" >/dev/null || need_pkgs=1
done
[ -f /usr/include/zlib.h ] || need_pkgs=1
if [ $need_pkgs -eq 1 ]; then
	if [ "$(id -u)" -eq 0 ] && command -v apt-get >/dev/null; then
		log "installing host packages"
		apt-get update -qq
		# shellcheck disable=SC2086
		DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $PKGS
	else
		echo "missing host tools; install: $PKGS" >&2
		exit 1
	fi
fi

# --------------------------------------------------------------- 2. coreboot
if [ ! -d "$CB/.git" ]; then
	log "creating coreboot checkout"
	git init -q "$CB"
fi
if ! git -C "$CB" cat-file -e "$COREBOOT_COMMIT^{commit}" 2>/dev/null; then
	ok=0
	for url in $COREBOOT_URLS; do
		log "fetching coreboot $COREBOOT_COMMIT from $url"
		if git -C "$CB" fetch -q --depth 1 "$url" "$COREBOOT_COMMIT"; then
			git -C "$CB" remote remove origin 2>/dev/null || true
			git -C "$CB" remote add origin "$url"
			ok=1
			break
		fi
	done
	[ $ok -eq 1 ] || { echo "could not fetch coreboot" >&2; exit 1; }
fi

# -------------------------------------------------------------- 4. patches
STAMP_FILE="$CB/.git/acoreboot-patches.sha256"
STAMP="$( (echo "$COREBOOT_COMMIT"; cat "$TOP"/patches/*.patch) | sha256sum | cut -d' ' -f1)"
cur_branch="$(git -C "$CB" symbolic-ref -q --short HEAD || true)"
if [ "$cur_branch" = "$BRANCH" ] && [ -f "$STAMP_FILE" ] && \
   [ "$(cat "$STAMP_FILE")" = "$STAMP" ] && [ -z "$(git -C "$CB" status --porcelain -uno)" ]; then
	log "patches already applied ($(git -C "$CB" rev-parse --short HEAD))"
else
	if [ -n "$(git -C "$CB" status --porcelain -uno 2>/dev/null)" ] && [ "${FORCE:-0}" != 1 ]; then
		echo "coreboot/ has local changes; commit them, or rerun with FORCE=1" >&2
		exit 1
	fi
	log "applying patches/*.patch on $COREBOOT_COMMIT"
	git -C "$CB" -c advice.detachedHead=false checkout -q -f -B "$BRANCH" "$COREBOOT_COMMIT"
	git -C "$CB" -c user.name="ACoreboot setup" -c user.email="setup@localhost" \
		am -q --committer-date-is-author-date "$TOP"/patches/*.patch
	echo "$STAMP" > "$STAMP_FILE"
fi

# ------------------------------------------------------------ 3. submodules
for s in $SUBMODULES; do
	if [ -z "$(ls -A "$CB/$s" 2>/dev/null)" ]; then
		log "submodule $s"
		git -C "$CB" submodule update --init --checkout --depth 1 "$s"
	fi
done

# ------------------------------------------------------------- 5. toolchain
XGCC="$CB/util/crossgcc/xgcc/bin"
if [ "$TOOLCHAIN" = "crossgcc" ]; then
	if [ ! -x "$XGCC/i386-elf-gcc" ] || [ ! -x "$XGCC/nasm" ]; then
		log "building crossgcc-i386 (log: logs/toolchain.log, ~10-30 min)"
		make -C "$CB" crossgcc-i386 CPUS="$JOBS" BUILDGCC_OPTIONS=-m \
			>> "$TOP/logs/toolchain.log" 2>&1 || {
			echo "crossgcc build failed, see logs/toolchain.log;" \
			     "retry with TOOLCHAIN=system" >&2; exit 1; }
	fi
	if [ ! -x "$XGCC/iasl" ]; then
		log "building iasl"
		make -C "$CB" iasl CPUS="$JOBS" BUILDGCC_OPTIONS=-m >> "$TOP/logs/toolchain.log" 2>&1
	fi
	"$XGCC/i386-elf-gcc" --version | head -1
else
	log "using system toolchain (CONFIG_ANY_TOOLCHAIN)"
	gcc --version | head -1
	gnat --version | head -1
	iasl -v | grep -i version || true
fi
echo "$TOOLCHAIN" > "$TOP/logs/toolchain-method"

# ----------------------------------------------------------------- 6. blobs
"$TOP/scripts/extract_blobs.sh"
log "setup done"
