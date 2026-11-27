#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Dump the child device table (BDB block 2) of an Intel VBT.

Field layout follows Linux drivers/gpu/drm/i915/display/intel_vbt_defs.h.
Usage: vbt_dump.py data.vbt
"""
import struct
import sys

DVO_PORT = {0: "HDMI-A", 1: "HDMI-B", 2: "HDMI-C", 3: "HDMI-D", 4: "LVDS",
            5: "TV", 6: "CRT", 7: "DP-B", 8: "DP-C", 9: "DP-D", 10: "DP-A",
            11: "DP-E", 12: "HDMI-E", 13: "DP-F", 14: "HDMI-F"}
AUX = {0x00: "none", 0x40: "AUX-A", 0x10: "AUX-B", 0x20: "AUX-C",
       0x30: "AUX-D", 0x50: "AUX-E", 0x60: "AUX-F"}
# Bits of device_type (DEVICE_TYPE_* in intel_vbt_defs.h)
DT_BITS = [(15, "CLASS_EXT"), (14, "POWER_MGMT"), (13, "HOTPLUG"),
           (12, "INTERNAL_CONN"), (11, "NOT_HDMI"), (10, "MIPI"),
           (9, "COMPOSITE"), (8, "DUAL_CHANNEL"), (7, "HIGH_SPEED"),
           (6, "TMDS_DVI"), (5, "LVDS"), (4, "DISPLAYPORT"), (3, "MIPI_OUT?"),
           (2, "DIGITAL"), (1, "ANALOG"), (0, "CRT/TV")]


def main(path):
    b = open(path, "rb").read()
    assert b[:4] == b"$VBT", "not a VBT"
    vbt_size = struct.unpack_from("<H", b, 0x18)[0]
    bdb_off = struct.unpack_from("<I", b, 0x1c)[0]
    sig = b[bdb_off:bdb_off + 16]
    ver, hdr, bdbsize = struct.unpack_from("<HHH", b, bdb_off + 16)
    print("VBT signature %r size %d, BDB %r version %d" %
          (b[:20].decode("latin1").strip(), vbt_size, sig.decode("latin1").strip(), ver))
    p = bdb_off + hdr
    end = bdb_off + bdbsize
    blocks = {}
    while p + 3 <= end:
        bid = b[p]
        bsz = struct.unpack_from("<H", b, p + 1)[0]
        blocks.setdefault(bid, b[p + 3:p + 3 + bsz])
        p += 3 + bsz
    print("blocks:", sorted(blocks))
    g = blocks[2]
    crt_ddc, _, boot_disp, child_size = g[0], g[1], struct.unpack_from("<H", g, 2)[0], g[4]
    print("block2: crt_ddc_gmbus_pin=%d boot_display=0x%04x child_dev_size=%d" %
          (crt_ddc, boot_disp, child_size))
    n = (len(g) - 5) // child_size
    for i in range(n):
        c = g[5 + i * child_size:5 + (i + 1) * child_size]
        handle, dtype = struct.unpack_from("<HH", c, 0)
        if dtype == 0:
            continue
        dvo_port = c[16]
        ddc_pin = c[19]
        flags = c[23]  # efp_routed..dp_max_lane_count (bdb >= 158)
        sup = c[24]
        aux = c[25]
        hpd_invert = (flags >> 4) & 1
        lane_rev = (flags >> 1) & 1
        dt = [n for bit, n in DT_BITS if dtype & (1 << bit)]
        print("child %d: handle 0x%04x type 0x%04x [%s]" % (i, handle, dtype, ",".join(dt)))
        print("    dvo_port=%d (%s) ddc_pin=%d aux=0x%02x (%s) hdmi=%d dp=%d tmds=%d "
              "lane_reversal=%d hpd_invert=%d iboost=%d" %
              (dvo_port, DVO_PORT.get(dvo_port, "?"), ddc_pin, aux, AUX.get(aux, "?"),
               sup & 1, (sup >> 1) & 1, (sup >> 2) & 1, lane_rev, hpd_invert, (flags >> 3) & 1))


if __name__ == "__main__":
    main(sys.argv[1])
