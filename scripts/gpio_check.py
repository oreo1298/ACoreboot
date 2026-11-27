#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify the ASUS PRIME B360M-C GPIO table against the vendor configuration.

The pad table is read from the gpio.o of a real coreboot build (so every
macro is expanded by the coreboot toolchain exactly as in the firmware) and
each pad is turned back into the DW0/DW1/HOSTSW_OWN values coreboot programs:

  * logical PAD_RESET() values are mapped to PADRSTCFG with the CNP-H maps
    (GPP communities: rst_map, GPD: rst_map_gpd, soc/intel/cannonlake/gpio_cnp_h.c)
  * only the bits in PAD_DW0_MASK / PAD_DW1_MASK are written by coreboot
    (soc/intel/common/block/gpio/gpio.c), everything else keeps its value

Reference (one of):
  default        board-data/dumps/gpio_vendor_expected.json, derived from the vendor
                 GPIO_INIT_CONFIG table by scripts/vendor_gpio.py. Only bits the
                 vendor table determines are compared.
  --dump FILE    an `inteltool -G` dump taken under the vendor firmware. All bits
                 coreboot writes are compared.

Differences are classified; any difference without an explanation makes the
script exit with status 1.

Usage: gpio_check.py [--dump inteltool-G.txt] [--coreboot DIR] [--gpio-o FILE] [-v]
"""
import argparse
import json
import os
import re
import struct
import subprocess
import sys
import tempfile

TOP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# soc/intel/common/block/gpio/gpio.c, CNL: no IOSTANDBY, no PADTOL, 3-bit PMODE
DW0_MASK = (1 << 0) | (1 << 8) | (1 << 9) | (0x7 << 10) | (0xf << 17) | (0x3 << 21) | \
    (1 << 23) | (1 << 24) | (0x3 << 25) | (1 << 27) | (1 << 28) | (1 << 29) | (0x3 << 30)
DW1_MASK = 0xf << 10
OWN_DRIVER = 1 << 4			# PAD_CFG_OWN_GPIO_DRIVER in pad_config[1]
RO_DW0 = 1 << 1				# GPIORXSTATE
RO_DW1 = 0xff				# INTSEL

# PAD_CFG0_LOGICAL_RESET_* (gpio_defs.h): PWROK=0, DEEP=1, PLTRST=2, RSMRST=3 (<<30)
RST_GPP = {1: 0b01, 2: 0b10, 3: 0b00}		# rst_map
RST_GPD = {0: 0b00, 1: 0b01, 2: 0b10, 3: 0b11}	# rst_map_gpd

FIELDS = [  # name, register, mask
    ("TXSTATE", 0, 1 << 0), ("RXSTATE(RO)", 0, 1 << 1), ("TXDIS", 0, 1 << 8),
    ("RXDIS", 0, 1 << 9), ("PMODE", 0, 0x7 << 10), ("GPIROUT", 0, 0xf << 17),
    ("RXTXENCFG", 0, 0x3 << 21), ("RXINV", 0, 1 << 23), ("PREGFRXSEL", 0, 1 << 24),
    ("RXEVCFG", 0, 0x3 << 25), ("NAFVWE", 0, 1 << 27), ("RXRAW1", 0, 1 << 28),
    ("RXPADSTSEL", 0, 1 << 29), ("PADRSTCFG", 0, 0x3 << 30),
    ("INTSEL(RO)", 1, 0xff), ("TERM", 1, 0xf << 10), ("IOSSTATE", 1, 0xf << 14),
    ("PADTOL", 1, 1 << 25),
]


def field_names(reg, bits):
    return ",".join(n for n, r, m in FIELDS if r == reg and m & bits) or hex(bits)


def pad_ids(cb):
    """Pad name -> number from gpio_soc_defs_cnp_h.h."""
    path = os.path.join(cb, "src/soc/intel/cannonlake/include/soc/gpio_soc_defs_cnp_h.h")
    ids = {}
    for m in re.finditer(r"#define\s+(GP[A-Z0-9_]+)\s+(\d+)\b", open(path).read()):
        ids[int(m.group(2))] = m.group(1)
    return ids


def compile_table(cb, gpio_o):
    """Read gpio_table out of the gpio.o produced by the real coreboot build.

    struct pad_config is { gpio_t pad; uint32_t pad_config[4]; enum lock_action; }
    (24 bytes on x86, GPIO_NUM_PAD_CFG_REGS = 4 on CNP-H).
    """
    objcopy = os.path.join(cb, "util/crossgcc/xgcc/bin/i386-elf-objcopy")
    if not os.path.exists(objcopy):
        objcopy = "objcopy"
    with tempfile.TemporaryDirectory() as d:
        raw = os.path.join(d, "gpio_table.bin")
        subprocess.run([objcopy, "--dump-section", ".rodata.gpio_table=" + raw, gpio_o,
                        os.path.join(d, "scratch.o")], check=True)
        data = open(raw, "rb").read()
    if len(data) % 24:
        sys.exit("unexpected gpio_table size %d" % len(data))
    rows = []
    for off in range(0, len(data), 24):
        pad, c0, c1, _c2, _c3, lock = struct.unpack_from("<6I", data, off)
        rows.append((pad, c0, c1, lock))
    return rows


def coreboot_view(pad_name, cfg0, cfg1):
    """DW0/DW1 bits coreboot writes, ownership."""
    logical = (cfg0 >> 30) & 0x3
    rmap = RST_GPD if pad_name.startswith("GPD") else RST_GPP
    if logical not in rmap:
        raise ValueError("%s: logical reset %d has no chipset mapping" % (pad_name, logical))
    dw0 = (cfg0 & ~(0x3 << 30)) | (rmap[logical] << 30)
    return dw0 & DW0_MASK, cfg1 & DW1_MASK, ("DRIVER" if cfg1 & OWN_DRIVER else "ACPI")


def parse_inteltool(path):
    pads = {}
    for line in open(path, errors="replace"):
        m = re.match(r"\s*0x[0-9a-fA-F]+:\s+0x([0-9a-fA-F]{16})\s+(\S+)", line)
        if m:
            v = int(m.group(1), 16)
            pads[m.group(2)] = (v & 0xffffffff, v >> 32)
    return pads


def explain_vendor(pad, e, reg, bits, cb_val):
    """Explanation for a coreboot-written field the vendor table leaves at default."""
    if reg == 0 and bits & (0x3 << 25) and e["vendor_cfg"][0] & 0x1f == 1:
        return "RXEVCFG of a GPIO pad without interrupt config: vendor keeps reset " \
               "value, coreboot writes TRIG(%s) (assumption, see DECISIONS D-006)" % \
               ["LEVEL", "EDGE_SINGLE", "OFF", "EDGE_BOTH"][(cb_val >> 25) & 3]
    if reg == 0 and bits & (1 << 23) and not (e["mask0"] & (1 << 23)):
        return "RXINV: vendor direction has no inversion field, coreboot writes 0"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--coreboot", default=os.path.join(TOP, "coreboot"))
    ap.add_argument("--gpio-o", default=None,
                    help="gpio.o from a coreboot build (default: build/<A|B|D|C>/bootblock/...)")
    ap.add_argument("--expected", default=os.path.join(TOP, "board-data/dumps/gpio_vendor_expected.json"))
    ap.add_argument("--dump", help="inteltool -G output taken under the vendor firmware")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    cb = a.coreboot
    rel = "bootblock/mainboard/asus/b360m-c/gpio.o"
    gpio_o = a.gpio_o or next((os.path.join(TOP, "build", v, rel) for v in "ABDC"
                               if os.path.exists(os.path.join(TOP, "build", v, rel))), None)
    if not gpio_o:
        sys.exit("no build/<variant>/%s, run scripts/build.sh first" % rel)
    names = pad_ids(cb)
    table = compile_table(cb, gpio_o)
    exp = json.load(open(a.expected))["pads"]
    dump = parse_inteltool(a.dump) if a.dump else None

    unexplained, explained, seen = [], [], set()
    for pad, cfg0, cfg1, lock in table:
        name = names[pad]
        if name in seen:
            unexplained.append("%s: listed twice" % name)
        seen.add(name)
        dw0, dw1, own = coreboot_view(name, cfg0, cfg1)
        if dump is not None:
            if name not in dump:
                unexplained.append("%s: not in inteltool dump" % name)
                continue
            r0, r1 = dump[name]
            for reg, cbv, ref, mask in ((0, dw0, r0, DW0_MASK & ~RO_DW0), (1, dw1, r1, DW1_MASK & ~RO_DW1)):
                d = (cbv ^ ref) & mask
                if d:
                    unexplained.append("%s DW%d %s: coreboot 0x%08x, dump 0x%08x" %
                                       (name, reg, field_names(reg, d), cbv & mask, ref & mask))
            continue
        e = exp.get(name)
        if e is None:
            unexplained.append("%s: not in vendor table" % name)
            continue
        for reg, cbv, ref, vmask, cmask in ((0, dw0, e["dw0"], e["mask0"], DW0_MASK),
                                            (1, dw1, e["dw1"], e["mask1"], DW1_MASK)):
            d = (cbv ^ ref) & vmask & cmask
            if d:
                unexplained.append("%s DW%d %s: coreboot 0x%08x, vendor 0x%08x" %
                                   (name, reg, field_names(reg, d), cbv & vmask, ref & vmask))
            nd = vmask & ~cmask
            if nd:
                unexplained.append("%s DW%d %s: set by vendor, not writable by coreboot" %
                                   (name, reg, field_names(reg, nd)))
            # Fields coreboot writes that the vendor table leaves at their
            # reset value. Non-zero writes need an explanation; zero writes
            # assume a reset value of 0 and are listed so a real dump can
            # confirm them (--dump compares them against the hardware).
            for fname, freg, fm in FIELDS:
                if freg != reg or not (fm & cmask & ~vmask):
                    continue
                written = cbv & fm & cmask
                if written:
                    why = explain_vendor(name, e, reg, fm, cbv)
                    if why:
                        explained.append("%s DW%d %s: %s" % (name, reg, fname, why))
                    else:
                        unexplained.append("%s DW%d %s: coreboot writes 0x%x, vendor leaves "
                                           "reset value" % (name, reg, fname, written))
                else:
                    explained.append("%s DW%d %s: coreboot writes 0 where the vendor keeps the "
                                     "reset value (assumed 0, confirm with --dump)"
                                     % (name, reg, fname))
        if e["own"] and e["own"] != own:
            unexplained.append("%s HOSTSW_OWN: coreboot %s, vendor %s" % (name, own, e["own"]))
        if not e["own"] and own != "ACPI":
            unexplained.append("%s HOSTSW_OWN: coreboot DRIVER, vendor default" % name)
        if e["lock"] not in (0, 3) and lock == 0:
            explained.append("%s: vendor lock config 0x%x not replicated" % (name, e["lock"]))

    ref_pads = set(dump) if dump is not None else set(exp)
    if dump is not None:
        ref_pads = {p for p in ref_pads if re.match(r"GP(P_[A-K]\d+|D\d+)$", p)}
    for p in sorted(ref_pads - seen):
        unexplained.append("%s: in reference but not configured by coreboot" % p)

    ref = a.dump or os.path.relpath(a.expected, TOP)
    print("gpio_check: %d pads in %s, reference %s" % (len(table), os.path.relpath(gpio_o, TOP), ref))
    cats = {}
    for x in explained:
        head, reason = x.split(": ", 1)
        parts = head.split()
        pad, field = parts[0], " ".join(parts[1:]) or "-"
        cats.setdefault((field, reason), []).append(pad)
    for (field, reason), pads in sorted(cats.items()):
        print("  explained %-16s %3d pads: %s" % (field, len(pads), reason))
        if a.verbose:
            print("    " + " ".join(pads))
    for x in unexplained:
        print("  UNEXPLAINED: " + x)
    print("gpio_check: %d explained (pad, field) items, %d unexplained differences" %
          (len(explained), len(unexplained)))
    return 1 if unexplained else 0


if __name__ == "__main__":
    sys.exit(main())
