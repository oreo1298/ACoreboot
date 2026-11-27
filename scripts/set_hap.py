#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Set the Intel ME "HAP" strap in a full flash image (me_cleaner -S equivalent).

me_cleaner -S ("soft disable only") changes nothing but the HAP bit,
PCHSTRP0 bit 16, for every ME >= 11. me_cleaner itself refuses this board's
CSME 12 image, because it expects $FPT at ME+0x10 and CSME 12 starts with a
CSE layout table / BPDT, so this script does the same strap write directly.

WARNING: coreboot's ifdtool does not list a HAP location for Cannon Point
("HAP bit location not known for platform"). PCHSTRP0[16] is the location
me_cleaner uses for all ME >= 11 and the one confirmed for SPT/KBP. It is
NOT verified for CNP-H. See DECISIONS.md D-028.

Usage: set_hap.py <in.rom> <out.rom>
"""
import struct
import sys

HAP_WORD = 0
HAP_BIT = 16


def main(src, dst):
    img = bytearray(open(src, "rb").read())
    if struct.unpack_from("<I", img, 0x10)[0] != 0x0FF0A55A:
        sys.exit("no flash descriptor at 0x10")
    flmap1 = struct.unpack_from("<I", img, 0x18)[0]
    fpsba = (flmap1 >> 12) & 0xff0
    psl = (flmap1 >> 24) & 0xff
    if HAP_WORD >= psl:
        sys.exit("PCHSTRP%d outside the strap section" % HAP_WORD)
    off = fpsba + 4 * HAP_WORD
    old = struct.unpack_from("<I", img, off)[0]
    if old & (1 << HAP_BIT):
        sys.exit("HAP bit already set")
    struct.pack_into("<I", img, off, old | (1 << HAP_BIT))
    orig = open(src, "rb").read()
    changed = [i for i in range(len(img)) if img[i] != orig[i]]
    assert changed == [off + HAP_BIT // 8], changed
    open(dst, "wb").write(img)
    print("PCHSTRP%d @0x%x: 0x%08x -> 0x%08x (HAP set) -> %s" %
          (HAP_WORD, off, old, old | (1 << HAP_BIT), dst))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
