#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Show or set the MAC address in an Intel GbE (I219) flash region.

The GbE NVM image starts with the MAC address (words 0-2) and the sum of
words 0x00-0x3f must equal 0xBABA (word 0x3f is the checksum). The region
holds two 4 KiB banks; every bank with a valid signature (word 0x13 bits
15:14 = 10b) is updated.

Usage: gbe_mac.py <gbe.bin>                     print MAC of each valid bank
       gbe_mac.py <gbe.bin> <MAC> <out.bin>     write a copy with MAC set
"""
import re
import struct
import sys

BANK = 0x1000


def banks(data):
    for off in range(0, len(data), BANK):
        words = struct.unpack_from("<64H", data, off)
        if (words[0x13] >> 14) == 0b10:
            yield off, words


def mac_of(data, off):
    return ":".join("%02x" % x for x in data[off:off + 6])


def main(argv):
    data = bytearray(open(argv[1], "rb").read())
    if len(argv) == 2:
        print(" ".join("bank%d=%s" % (off // BANK, mac_of(data, off)) for off, _ in banks(data))
              or "no valid bank")
        return
    mac = argv[2].lower()
    if not re.fullmatch(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", mac):
        sys.exit("bad MAC %r" % mac)
    raw = bytes(int(x, 16) for x in mac.split(":"))
    if raw[0] & 1:
        sys.exit("multicast MAC not allowed")
    found = False
    for off, _ in list(banks(data)):
        data[off:off + 6] = raw
        words = struct.unpack_from("<63H", data, off)
        struct.pack_into("<H", data, off + 0x7e, (0xBABA - sum(words)) & 0xffff)
        found = True
    if not found:
        sys.exit("no valid GbE bank")
    open(argv[3], "wb").write(data)
    print("MAC set to %s in %s" % (mac, argv[3]))


if __name__ == "__main__":
    main(sys.argv)
