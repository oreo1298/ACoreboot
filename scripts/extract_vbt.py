#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Extract the GOP VBT from the ASUS PRIME B360M-C BIOS region.

The VBT used by the Intel GOP lives uncompressed in FFS file
56752da9-de6b-4895-8819-1945b6b76c22 (IntelGopVbt) as a raw section. The
image also contains a legacy VBIOS option ROM with its own embedded VBT
("$VBT COFFEELAKE"); that one is ignored. All FFS copies must be identical.

Usage: extract_vbt.py <bios region> <out.vbt>
"""
import struct
import sys
import uuid

GOP_VBT_GUID = uuid.UUID("56752da9-de6b-4895-8819-1945b6b76c22").bytes_le
EFI_SECTION_RAW = 0x19


def main(src, dst):
    b = open(src, "rb").read()
    found = []
    i = b.find(GOP_VBT_GUID)
    while i >= 0:
        # FFS header is 24 bytes, followed by a 4-byte common section header
        sec_type = b[i + 24 + 3]
        vbt = i + 28
        if sec_type == EFI_SECTION_RAW and b[vbt:vbt + 4] == b"$VBT":
            size = struct.unpack_from("<H", b, vbt + 0x18)[0]
            found.append(b[vbt:vbt + size])
        i = b.find(GOP_VBT_GUID, i + 16)
    if not found:
        sys.exit("IntelGopVbt FFS file not found")
    if any(v != found[0] for v in found):
        sys.exit("VBT copies differ")
    open(dst, "wb").write(found[0])
    print("VBT: %d copies of IntelGopVbt, %d bytes -> %s" % (len(found), len(found[0]), dst))


if __name__ == "__main__":
    main(*sys.argv[1:3])
