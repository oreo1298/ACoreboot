#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Turn intelp2m output into the mainboard gpio.c.

intelp2m only sees DW0/DW1 (inteltool dumps carry no HOSTSW_OWN), so it
always emits ACPI ownership. The vendor table says GpioHostOwnGpio for
every GPIO-mode input; this script restores that (DRIVER ownership) from
gpio_vendor_expected.json, wraps long lines and adds pad function names.

Usage: gen_gpio_c.py <intelp2m gpio.h> <gpio_vendor_expected.json> <out gpio.c>
"""
import json
import re
import sys

HEADER = """/* SPDX-License-Identifier: GPL-2.0-only */

#include <gpio.h>
#include "include/gpio.h"

/*
 * Pad configuration taken from the GPIO_INIT_CONFIG table of the vendor
 * firmware (ASUS BIOS 3202, board PEIM 2accd044-284c-432f-9a1a-4cde31036c9f)
 * and converted with `util/intelp2m -p cnl-h`. Every Cannon Point PCH-H pad
 * is listed in the vendor table, so every pad is listed here.
 */
static const struct pad_config gpio_table[] = {
"""

FOOTER = """};

void mainboard_configure_gpios(void)
{
	gpio_configure_pads(gpio_table, ARRAY_SIZE(gpio_table));
}
"""

MAX_COLS = 96


def width(s):
    return len(s.expandtabs(8))


def wrap_struct(line):
    """Split a _PAD_CFG_STRUCT(pad, dw0, dw1) entry over several lines."""
    m = re.match(r"_PAD_CFG_STRUCT\((\w+), (.*), ([^,]*)\),$", line)
    if not m:
        return ["\t" + line]
    pad, dw0, dw1 = m.groups()
    parts = [p.strip() for p in dw0.split("|")]
    out = ["\t_PAD_CFG_STRUCT(%s," % pad]
    cur = "\t\t" + parts[0]
    for p in parts[1:]:
        if width(cur + " | " + p + ",") > MAX_COLS:
            out.append(cur + " |")
            cur = "\t\t" + p
        else:
            cur += " | " + p
    out.append(cur + ",")
    out.append("\t\t%s)," % dw1)
    return out


def main(src, expected_json, dst):
    exp = json.load(open(expected_json))["pads"]
    body = []
    seen = set()
    for raw in open(src):
        line = raw.strip()
        if line.startswith("/* GPIO Group"):
            grp = line.split()[3]
            if body:
                body.append("")
            body.append("\t/* %s */" % grp)
            continue
        m = re.match(r"(PAD_\w+|_PAD_CFG_STRUCT)\((\w+),", line)
        if not m:
            continue
        pad = m.group(2)
        seen.add(pad)
        e = exp[pad]
        if e["own"] == "DRIVER":
            if m.group(1) == "PAD_CFG_GPI_TRIG_OWN":
                line = re.sub(r", ACPI\),$", ", DRIVER),", line)
            elif m.group(1) == "_PAD_CFG_STRUCT":
                line = re.sub(r", (0|[^,]*)\),$",
                              lambda x: ", %s),"
                              % ("PAD_CFG_OWN_GPIO(DRIVER)" if x.group(1) == "0"
                                 else x.group(1) + " | PAD_CFG_OWN_GPIO(DRIVER)"), line)
            else:
                sys.exit("%s: cannot express DRIVER ownership with %s" % (pad, m.group(1)))
        comment = "\t/* %s - %s */" % (pad, e["func"]) if e["func"] != "GPIO" else None
        if comment:
            body.append(comment)
        if width("\t" + line) > MAX_COLS:
            body.extend(wrap_struct(line))
        else:
            body.append("\t" + line)
    missing = set(exp) - seen
    if missing:
        sys.exit("pads missing from intelp2m output: %s" % sorted(missing))
    open(dst, "w").write(HEADER + "\n".join(body) + "\n" + FOOTER)
    print("wrote %s (%d pads)" % (dst, len(seen)))


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
