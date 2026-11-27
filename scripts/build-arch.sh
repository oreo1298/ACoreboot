#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
#
# One-shot build for Arch Linux: host packages (pacman, via sudo), coreboot
# checkout with the patches, crossgcc toolchain, blobs and all ROM variants.
# Run from the repository root as your normal user:
#
#   scripts/build-arch.sh          build A B C
#   scripts/build-arch.sh A B      build only A and B
#   MAC=xx:xx:xx:xx:xx:xx scripts/build-arch.sh   put your MAC into the GbE region
#
# The first run builds the toolchain (~10-30 min) and, for variant C, clones
# EDK2 with its submodules from GitHub (~7 GB). Later runs are incremental.
set -euo pipefail

TOP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[ -f /etc/arch-release ] || echo "warning: this does not look like Arch Linux" >&2
[ "$(id -u)" -ne 0 ] || echo "note: running as root; a normal user with sudo also works" >&2

"$TOP/scripts/setup.sh"
"$TOP/scripts/build.sh" "$@"

echo
echo "Done. ROMs and checksums are in $TOP/out/ - see BRINGUP.md for flashing."
