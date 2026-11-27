#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
#
# Run the quality gates for the ASUS PRIME B360M-C port:
#   1. util/abuild for asus/b360m-c
#   2. util/lint lint-stable
#   3. checkpatch on patches/*.patch (no Signed-off-by check, see DECISIONS D-027)
#   4. scripts/gpio_check.py (vendor table, and --dump if a vendor inteltool -G exists)
# Results go to logs/check-*.log; exit status is non-zero if anything fails.
set -uo pipefail

TOP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CB="$TOP/coreboot"
rc=0
step() { printf '%-28s' "$1"; }
ok() { echo "PASS"; }
fail() { echo "FAIL (see $1)"; rc=1; }

step "abuild asus/b360m-c"
rm -rf "$TOP/build/abuild"
if (cd "$CB" && util/abuild/abuild -t asus/b360m-c -c "$(nproc)" -o "$TOP/build/abuild") \
	> "$TOP/logs/check-abuild.log" 2>&1 && grep -q 'All 1 tested configurations passed' \
	"$TOP/logs/check-abuild.log"; then ok; else fail logs/check-abuild.log; fi

step "lint-stable"
if (cd "$CB" && util/lint/lint lint-stable) > "$TOP/logs/check-lint.log" 2>&1; then ok
else fail logs/check-lint.log; fi

step "checkpatch"
: > "$TOP/logs/check-checkpatch.log"
cp_rc=0
for p in "$TOP"/patches/*.patch; do
	(cd "$CB" && util/lint/checkpatch.pl --no-signoff "$p") >> "$TOP/logs/check-checkpatch.log" 2>&1
	grep -q '^total: 0 errors, 0 warnings' <(cd "$CB" && util/lint/checkpatch.pl --no-signoff "$p" 2>&1) || cp_rc=1
done
if [ $cp_rc -eq 0 ]; then ok; else fail logs/check-checkpatch.log; fi

step "gpio_check (vendor table)"
if python3 -I "$TOP/scripts/gpio_check.py" > "$TOP/logs/check-gpio.log" 2>&1; then ok
else fail logs/check-gpio.log; fi

VDUMP="$TOP/board-data/dumps/vendor/inteltool-G.txt"
if [ -f "$VDUMP" ]; then
	step "gpio_check (inteltool dump)"
	if python3 -I "$TOP/scripts/gpio_check.py" --dump "$VDUMP" > "$TOP/logs/check-gpio-dump.log" 2>&1
	then ok; else fail logs/check-gpio-dump.log; fi
fi
exit $rc
