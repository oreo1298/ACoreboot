#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
#
# Build the ASUS PRIME B360M-C coreboot variants into out/.
#
#   scripts/build.sh            build A B C
#   scripts/build.sh A B        build only A and B
#
#   A  SeaBIOS + libgfxinit                (primary first-boot image)
#   B  SeaBIOS + FSP GOP                   (display fallback, VGA)
#   C  EDK2 (coreboot default fork) + FSP GOP   (needs GitHub access)
#   D  A + PCHSTRP0[16] ("HAP", me_cleaner -S equivalent)   } NOT recommended: on
#   E  C + PCHSTRP0[16]                                      } hardware this bit did
#      not disable the ME (DECISIONS.md D-028). Built only with HAP_EXPERIMENT=1.
#      To disable the ME use the me_state CMOS option instead (BRINGUP.md §9).
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
VARIANTS="${*:-A B C}"

declare -A CFG=(
	[A]=A_seabios_libgfxinit
	[B]=B_seabios_fspgop
	[C]=C_edk2_fspgop
	[D]=none
	[E]=none
)
declare -A NAME=(
	[A]="${BOARD}_A_seabios_libgfxinit"
	[B]="${BOARD}_B_seabios_fspgop"
	[C]="${BOARD}_C_edk2_fspgop"
	[D]="${BOARD}_D_seabios_libgfxinit_ME_HAP_UNVERIFIED"
	[E]="${BOARD}_E_edk2_fspgop_ME_HAP_UNVERIFIED"
)
# HAP variants: built from the finished image of their base variant by setting
# only the HAP strap (scripts/set_hap.py)
declare -A HAPBASE=(
	[D]=A
	[E]=C
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
	if [ -n "${HAPBASE[$v]:-}" ]; then
		# only the HAP strap (PCHSTRP0 bit 16) may differ
		local diffs
		diffs="$( (cmp -l "$t/flashregion_0_flashdescriptor.bin" \
			"$TOP/blobs/descriptor.bin" || true) | wc -l)"
		[ "$diffs" -eq 1 ] || die "$v: expected exactly 1 changed descriptor byte, got $diffs"
		cmp -l "$t/flashregion_0_flashdescriptor.bin" "$TOP/blobs/descriptor.bin" \
			> "$OUT/$n.ifd-diff.txt" || true
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
	if [ -n "${HAPBASE[$v]:-}" ]; then
		[ "${HAP_EXPERIMENT:-0}" = 1 ] ||
			die "$v sets PCHSTRP0[16], which did not disable the ME on hardware" \
			    "(DECISIONS.md D-028). Use me_state instead, or HAP_EXPERIMENT=1."
		# HAP variant: the base variant's image with only the HAP strap set
		b="${HAPBASE[$v]}"
		if [ -f "$OUT/${NAME[$b]}.SKIPPED.txt" ] && [ ! -f "$TOP/build/$b/coreboot.rom" ]; then
			log "$v: skipped, base variant $b was not built"
			continue
		fi
		[ -f "$OUT/${NAME[$b]}.rom" ] && [ -f "$TOP/build/$b/coreboot.rom" ] ||
			die "$v needs variant $b, run: scripts/build.sh $b $v"
		cmp -s "$OUT/${NAME[$b]}.rom" "$TOP/build/$b/coreboot.rom" ||
			die "out/${NAME[$b]}.rom is stale, rebuild $b"
		log "$v: setting HAP on variant $b's image"
		mkdir -p "$TOP/build/$v/util/ifdtool"
		cp "$TOP/build/$b/util/ifdtool/ifdtool" "$TOP/build/$v/util/ifdtool/"
		cp "$TOP/build/$b/cbfstool" "$TOP/build/$v/"
		python3 -I "$TOP/scripts/set_hap.py" "$OUT/${NAME[$b]}.rom" "$OUT/$n.rom" \
			> "$TOP/logs/build-$v.log"
		cp "$OUT/${NAME[$b]}.config" "$OUT/$n.config"
		check_rom "$v" "$OUT/$n.rom"
		cmp -s "$OUT/$n.bios-region.bin" "$OUT/${NAME[$b]}.bios-region.bin" ||
			die "$v: BIOS region differs from $b"
		log "$v: OK -> out/$n.rom"
		continue
	fi
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
