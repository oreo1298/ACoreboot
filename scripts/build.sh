#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
#
# Build the ASUS PRIME B360M-C coreboot variants into out/.
#
#   scripts/build.sh            build A B C D
#   scripts/build.sh A B        build only A and B
#
#   A  SeaBIOS + libgfxinit                (primary first-boot image)
#   B  SeaBIOS + FSP GOP                   (display fallback, VGA)
#   C  EDK2 (coreboot default fork) + FSP GOP   (needs GitHub access)
#   D  A + me_cleaner -S (HAP)             (modifies the IFD HAP strap!)
#
# Every variant produces:
#   out/<name>.rom              full 16 MiB image (IFD + GbE + ME + BIOS)
#   out/<name>.bios-region.bin  BIOS region only (13 MiB, 0x300000-0xffffff)
#   out/<name>.cbfs.txt         cbfstool print
#   out/<name>.ifd.txt          ifdtool dump of the result
#
# Environment:
#   MAC=xx:xx:xx:xx:xx:xx   put this MAC into the GbE region of the full images
#                           (default: keep blobs/gbe.bin as extracted)
#   JOBS=n                  parallel jobs (default: nproc)
set -euo pipefail

TOP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CB="$TOP/coreboot"
OUT="$TOP/out"
JOBS="${JOBS:-$(nproc)}"
TOOLCHAIN="$(cat "$TOP/logs/toolchain-method" 2>/dev/null || echo crossgcc)"
BOARD=asus_prime-b360m-c
VARIANTS="${*:-A B C D}"

declare -A CFG=(
	[A]=A_seabios_libgfxinit
	[B]=B_seabios_fspgop
	[C]=C_edk2_fspgop
	[D]=D_seabios_libgfxinit_me_cleaner
)
declare -A NAME=(
	[A]="${BOARD}_A_seabios_libgfxinit"
	[B]="${BOARD}_B_seabios_fspgop"
	[C]="${BOARD}_C_edk2_fspgop"
	[D]="${BOARD}_D_seabios_libgfxinit_ME_CLEANER_HAP"
)

log() { echo "==> $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

[ -d "$CB/.git" ] || die "run scripts/setup.sh first"
"$TOP/scripts/extract_blobs.sh" >/dev/null
mkdir -p "$OUT" "$TOP/build" "$TOP/logs"

GBE="$TOP/blobs/gbe.bin"
if [ -n "${MAC:-}" ]; then
	GBE="$TOP/build/gbe-${MAC//:/}.bin"
	python3 -I "$TOP/scripts/gbe_mac.py" "$TOP/blobs/gbe.bin" "$MAC" "$GBE"
fi

github_reachable() {
	timeout 20 git ls-remote https://github.com/mrchromebox/edk2 HEAD >/dev/null 2>&1
}

check_rom() {	# <variant> <rom>
	local v="$1" rom="$2" n="${NAME[$1]}" t
	local IFDTOOL="$TOP/build/$v/util/ifdtool/ifdtool"
	t="$(mktemp -d)"
	(cd "$t" && "$IFDTOOL" -p cnl -x "$rom" >/dev/null)
	"$IFDTOOL" -p cnl -d "$rom" > "$OUT/$n.ifd.txt" 2>&1
	"$TOP/build/$v/cbfstool" "$rom" print > "$OUT/$n.cbfs.txt"
	cmp -s "$t/flashregion_2_intel_me.bin" "$TOP/blobs/me.bin" || die "$v: ME region differs"
	cmp -s "$t/flashregion_3_gbe.bin" "$GBE" || die "$v: GbE region differs"
	if [ "$v" = D ]; then
		# me_cleaner -S may only flip the HAP strap in the descriptor
		local diffs
		diffs="$(cmp -l "$t/flashregion_0_flashdescriptor.bin" "$TOP/blobs/descriptor.bin" | wc -l)"
		[ "$diffs" -eq 1 ] || die "D: expected exactly 1 changed descriptor byte, got $diffs"
		cmp -l "$t/flashregion_0_flashdescriptor.bin" "$TOP/blobs/descriptor.bin" \
			> "$OUT/$n.ifd-diff.txt"
	else
		cmp -s "$t/flashregion_0_flashdescriptor.bin" "$TOP/blobs/descriptor.bin" ||
			die "$v: flash descriptor differs from vendor"
	fi
	grep -q 'fallback/payload' "$OUT/$n.cbfs.txt" || die "$v: no payload in CBFS"
	grep -q 'fallback/romstage' "$OUT/$n.cbfs.txt" || die "$v: no romstage in CBFS"
	cp "$t/flashregion_1_bios.bin" "$OUT/$n.bios-region.bin"
	rm -rf "$t"
}

for v in $VARIANTS; do
	[ -n "${CFG[$v]:-}" ] || die "unknown variant $v"
	n="${NAME[$v]}"
	if [ "$v" = C ] && ! github_reachable; then
		log "C: GitHub not reachable, skipping EDK2 (see BRINGUP.md, 'Building variant C')"
		cat > "$OUT/$n.SKIPPED.txt" <<-EOF
		Variant C (EDK2 + FSP GOP) was not built: github.com is not reachable from
		the build host. coreboot's EDK2 payload clones edk2 and its submodules
		(openssl, brotli, libfdt, mipisyst, ...) from GitHub. Build it on a machine
		with GitHub access:  scripts/setup.sh && scripts/build.sh C
		EOF
		continue
	fi
	obj="$TOP/build/$v"
	mkdir -p "$obj"
	{
		sed -e "s|@TOP@|$TOP|g" -e "s|@GBE@|$GBE|g" "$TOP/configs/common.defconfig"
		cat "$TOP/configs/${CFG[$v]}.defconfig"
		[ "$TOOLCHAIN" = system ] && echo "CONFIG_ANY_TOOLCHAIN=y"
	} > "$obj/defconfig"
	log "$v: configuring ($n)"
	make -C "$CB" -s obj="$obj" DOTCONFIG="$obj/.config" \
		KBUILD_DEFCONFIG="$obj/defconfig" defconfig > "$TOP/logs/build-$v.log" 2>&1
	# every line of the fragment must have survived Kconfig
	while IFS= read -r line; do
		case "$line" in ''|'#'*) continue ;; esac
		grep -qxF "$line" "$obj/.config" || die "$v: '$line' not in resulting .config"
	done < <(grep -v '^# CONFIG_.* is not set' "$obj/defconfig")
	log "$v: building (log: logs/build-$v.log)"
	make -C "$CB" obj="$obj" DOTCONFIG="$obj/.config" -j"$JOBS" >> "$TOP/logs/build-$v.log" 2>&1 ||
		{ tail -30 "$TOP/logs/build-$v.log"; die "$v: build failed"; }
	cp "$obj/coreboot.rom" "$OUT/$n.rom"
	cp "$obj/.config" "$OUT/$n.config"
	check_rom "$v" "$OUT/$n.rom"
	log "$v: OK -> out/$n.rom"
done

(cd "$OUT" && sha256sum ./*.rom ./*.bios-region.bin 2>/dev/null | sed 's| \./| |' > SHA256SUMS)
log "out/SHA256SUMS:"
cat "$OUT/SHA256SUMS"
