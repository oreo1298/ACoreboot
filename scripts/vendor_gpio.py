#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Extract the board GPIO table from the ASUS PRIME B360M-C vendor firmware.

The ASUS board PEIM (FFS 2accd044-284c-432f-9a1a-4cde31036c9f) carries a
GPIO_INIT_CONFIG[] table (Intel Coffee Lake reference code format) that
covers every Cannon Point PCH-H pad (GPP_A..GPP_K, GPD). The PEI firmware
volume is not compressed, so the table can be found directly in the SPI
image.

For each pad this script derives the DW0/DW1/HOSTSW_OWN values the
reference code GpioConfigurePad() programs, together with a mask of the
bits the table actually determines. Fields left at "default" (0) in the
table keep their hardware reset value, which is not known without an
inteltool dump; those bits are excluded from the mask and filled with
documented assumptions (see ASSUMED_* below).

Outputs (all in --outdir):
  gpio_vendor_table.txt     human readable decode of the vendor table
  inteltool-G-synthetic.txt inteltool -G style pad lines (input for intelp2m)
  gpio_vendor_expected.json DW0/DW1/mask/ownership per pad (gpio_check.py)

Usage: vendor_gpio.py <spi image or .CAP> --outdir <dir> [--names cannonlake.h]
"""
import argparse
import json
import os
import re
import struct
import sys

# Cannon Point PCH-H pad groups in Intel RC group-index order (GpioPinsCnlH.h)
GROUPS = [("GPP_A", 24), ("GPP_B", 24), ("GPP_C", 24), ("GPP_D", 24),
          ("GPP_E", 13), ("GPP_F", 24), ("GPP_G", 8), ("GPP_H", 24),
          ("GPP_I", 15), ("GPP_J", 12), ("GPP_K", 24), ("GPD", 12)]
CNL_H_CHIPSET_ID = 0x3
TOTAL_PADS = sum(n for _, n in GROUPS)

# Assumptions for bits the vendor table leaves at their reset value.
ASSUMED_RXEVCFG_GPIO = 0b10   # trigger OFF for GPIO pads without interrupt cfg

MODE_NAMES = {0: "default", 1: "GPIO", 3: "NF1", 5: "NF2", 7: "NF3", 9: "NF4",
              11: "NF5", 13: "NF6", 15: "NF7", 17: "NF8"}
OWN_NAMES = {0: "default", 1: "ACPI", 3: "GPIO-driver"}
DIR_NAMES = {0: "default", 0x09: "InOut", 0x19: "InInvOut", 0x0b: "In",
             0x1b: "InInv", 0x05: "Out", 0x07: "None"}
OUT_NAMES = {0: "default", 1: "Low", 3: "High"}
RST_NAMES = {0x00: "default", 0x01: "ResumeReset", 0x03: "HostDeepReset",
             0x05: "PlatformReset", 0x07: "DswReset", 0x09: "PwrGood(legacy)",
             0x0b: "Deep(legacy)", 0x0d: "Normal(legacy)", 0x0f: "Resume(legacy)"}
TERM_NAMES = {0x00: "default", 0x01: "None", 0x05: "WPD5K", 0x09: "WPD20K",
              0x13: "WPU1K", 0x15: "WPU5K", 0x17: "WPU2K", 0x19: "WPU20K",
              0x1b: "WPU1K2K", 0x1f: "Native"}
LOCK_NAMES = {0x0: "default", 0x1: "PadConfigLock", 0x3: "PadConfigUnlock",
              0x4: "OutputStateLock", 0xc: "OutputStateUnlock", 0xf: "PadUnlock",
              0x5: "PadLock"}


def pad_names():
    names = []
    for grp, n in GROUPS:
        for i in range(n):
            names.append("GPD%d" % i if grp == "GPD" else "%s%d" % (grp, i))
    return names


def valid_entry(buf, off):
    pad, c0, c1 = struct.unpack_from("<III", buf, off)
    if (pad >> 24) != CNL_H_CHIPSET_ID:
        return False
    grp, idx = (pad >> 16) & 0xff, pad & 0xffff
    if grp >= len(GROUPS) or idx >= GROUPS[grp][1]:
        return False
    if (c0 & 0x1f) not in MODE_NAMES or ((c0 >> 7) & 0x3f) not in DIR_NAMES:
        return False
    return (c1 >> 22) == 0


def find_tables(buf):
    """Return offsets of runs that cover every PCH-H pad exactly once."""
    found = []
    for align in range(4):
        off = align
        while off + 12 <= len(buf):
            if not valid_entry(buf, off):
                off += 4
                continue
            start, pads = off, []
            while off + 12 <= len(buf) and valid_entry(buf, off):
                pads.append(struct.unpack_from("<I", buf, off)[0])
                off += 12
            if len(pads) == TOTAL_PADS and len(set(pads)) == TOTAL_PADS:
                found.append(start)
    return found


def decode(pad, c0, c1):
    grp, idx = (pad >> 16) & 0xff, pad & 0xffff
    gname = GROUPS[grp][0]
    f = {
        "mode": c0 & 0x1f, "own": (c0 >> 5) & 0x3, "dir": (c0 >> 7) & 0x3f,
        "out": (c0 >> 13) & 0x3, "int": (c0 >> 15) & 0x1ff, "rst": (c0 >> 24) & 0xff,
        "elec": c1 & 0x1ff, "lock": (c1 >> 9) & 0xf, "other": (c1 >> 13) & 0x1ff,
    }
    dw0 = dw1 = m0 = m1 = 0
    is_gpd = gname == "GPD"
    if f["mode"]:
        dw0 |= ((f["mode"] >> 1) & 0x7) << 10
        m0 |= 0x7 << 10
    if f["dir"]:
        dw0 |= ((f["dir"] & 0x7) >> 1) << 8          # GPIORXDIS:GPIOTXDIS
        m0 |= 0x3 << 8
        inv = (f["dir"] >> 3) & 0x3
        if inv:
            dw0 |= (inv >> 1) << 23                  # RXINV
            m0 |= 1 << 23
    if f["out"]:
        dw0 |= f["out"] >> 1                         # GPIOTXSTATE
        m0 |= 1
    route = f["int"] & 0x1f
    if route:
        dw0 |= (route >> 1) << 17                    # GPIROUT{NMI,SMI,SCI,IOXAPIC}
        m0 |= 0xf << 17
    trig = (f["int"] >> 5) & 0xf
    if trig:
        dw0 |= (trig >> 1) << 25                     # RXEVCFG
        m0 |= 0x3 << 25
    if f["rst"]:
        rst = f["rst"]
        if rst & 0x1 and rst <= 0x07:                # GpioResumeReset..GpioDswReset
            table = ({0x01: 0b11, 0x03: 0b01, 0x05: 0b10, 0x07: 0b00} if is_gpd else
                     {0x01: 0b00, 0x03: 0b01, 0x05: 0b10})
            if rst not in table:
                raise ValueError("reset 0x%02x invalid for %s%d" % (rst, gname, idx))
            dw0 |= table[rst] << 30
        else:                                        # legacy PadRstCfg encoding
            dw0 |= ((rst >> 1) & 0x3) << 30
        m0 |= 0x3 << 30
    if f["other"] & 0x3:
        dw0 |= ((f["other"] & 0x3) >> 1) << 28       # RXRAW1
        m0 |= 1 << 28
    if f["elec"] & 0x1f:
        dw1 |= ((f["elec"] & 0x1f) >> 1) << 10       # TERM
        m1 |= 0xf << 10
    if (f["elec"] >> 5) & 0x3:
        dw1 |= (((f["elec"] >> 5) & 0x3) >> 1) << 25  # PADTOL
        m1 |= 1 << 25
    own = None if not f["own"] else ("DRIVER" if f["own"] == 3 else "ACPI")
    return f, dw0, dw1, m0, m1, own


def load_function_names(path):
    """Parse inteltool's gpio_names/cannonlake.h for PCH-H pad function names."""
    names = {}
    if not path or not os.path.exists(path):
        return names
    text = open(path).read()
    for m in re.finditer(r"cannonlake_pch_h_group_\w+_names\[\]\s*=\s*\{(.*?)\};", text, re.S):
        body = m.group(1)
        rows = [re.findall(r'"([^"]*)"', line) for line in body.splitlines()]
        for row in rows:
            if row:
                names[row[0]] = row
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--names", help="util/inteltool/gpio_names/cannonlake.h")
    a = ap.parse_args()
    buf = open(a.image, "rb").read()
    offs = find_tables(buf)
    if not offs:
        sys.exit("no complete CNP-H GPIO_INIT_CONFIG table found")
    tables = [buf[o:o + TOTAL_PADS * 12] for o in offs]
    if any(t != tables[0] for t in tables):
        sys.exit("vendor GPIO table copies differ: %s" % [hex(o) for o in offs])
    fnames = load_function_names(a.names)
    os.makedirs(a.outdir, exist_ok=True)
    names = pad_names()
    expected = {}
    human = ["# Vendor GPIO_INIT_CONFIG table, %d pads, found at image offset(s) %s" %
             (TOTAL_PADS, ", ".join(hex(o) for o in offs)),
             "# Source: %s" % os.path.basename(a.image),
             "# pad      raw-pad  cfg0     cfg1     mode    own         dir      out     "
             "int   reset          term    lock            other"]
    synth = ["# SYNTHETIC inteltool -G style dump generated by scripts/vendor_gpio.py",
             "# from the vendor GPIO table. NOT read from hardware. Bits the vendor",
             "# table leaves at reset default are filled with assumptions (see",
             "# gpio_vendor_expected.json 'mask0'/'mask1' for the bits that are known).",
             ""]
    cur_grp = None
    for i in range(TOTAL_PADS):
        pad, c0, c1 = struct.unpack_from("<III", tables[0], i * 12)
        grp, idx = (pad >> 16) & 0xff, pad & 0xffff
        name = "GPD%d" % idx if GROUPS[grp][0] == "GPD" else "%s%d" % (GROUPS[grp][0], idx)
        if name != names[i]:
            sys.exit("unexpected pad order at %d: %s" % (i, name))
        f, dw0, dw1, m0, m1, own = decode(pad, c0, c1)
        fill0 = dw0
        if f["mode"] == 1 and not (m0 & (0x3 << 25)):
            fill0 |= ASSUMED_RXEVCFG_GPIO << 25
        pmode = (fill0 >> 10) & 0x7
        func = "GPIO"
        if pmode and name in fnames and pmode < len(fnames[name]):
            func = fnames[name][pmode]
        elif pmode:
            func = "NF%d" % pmode
        expected[name] = {"dw0": dw0, "dw1": dw1, "mask0": m0, "mask1": m1,
                          "own": own, "lock": f["lock"], "func": func,
                          "synthetic_dw0": fill0, "synthetic_dw1": dw1,
                          "vendor_cfg": [c0, c1]}
        human.append("%-9s %08x %08x %08x %-7s %-11s %-8s %-7s 0x%03x %-14s %-7s %-15s 0x%x" % (
            name, pad, c0, c1, MODE_NAMES[f["mode"]], OWN_NAMES[f["own"]],
            DIR_NAMES[f["dir"]], OUT_NAMES[f["out"]], f["int"],
            RST_NAMES.get(f["rst"], hex(f["rst"])), TERM_NAMES.get(f["elec"] & 0x1f, hex(f["elec"])),
            LOCK_NAMES.get(f["lock"], hex(f["lock"])), f["other"]))
        if GROUPS[grp][0] != cur_grp:
            cur_grp = GROUPS[grp][0]
            synth.append("GPIO Group %s" % cur_grp)
        synth.append("0x%04x: 0x%016x %-12s %-20s" % (i * 16, (dw1 << 32) | fill0, name, func))
    open(os.path.join(a.outdir, "gpio_vendor_table.txt"), "w").write("\n".join(human) + "\n")
    open(os.path.join(a.outdir, "inteltool-G-synthetic.txt"), "w").write("\n".join(synth) + "\n")
    with open(os.path.join(a.outdir, "gpio_vendor_expected.json"), "w") as fp:
        json.dump({"source": os.path.basename(a.image), "offsets": offs,
                   "assumed_rxevcfg_gpio": ASSUMED_RXEVCFG_GPIO, "pads": expected},
                  fp, indent=1, sort_keys=True)
    print("vendor GPIO table: %d pads at %s -> %s" %
          (TOTAL_PADS, ", ".join(hex(o) for o in offs), a.outdir))


if __name__ == "__main__":
    main()
