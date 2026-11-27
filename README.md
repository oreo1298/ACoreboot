# coreboot for the ASUS PRIME B360M-C

A coreboot port for the ASUS PRIME B360M-C (Intel B360 / Coffee Lake-S), with build
scripts and ready-made ROMs.

> **Hardware status:** variant C (EDK2 + FSP GOP) boots Linux on the owner's board,
> with NVMe, LAN, audio, USB and HDMI working (2026-11-27). A and B are untested.
> Read [BRINGUP.md](BRINGUP.md) before flashing: back up the chip, flash the BIOS
> region only, and watch the COM1 serial console.

## Build on Arch Linux

Run as your normal user; the script uses `sudo pacman` for missing packages.

```bash
sudo pacman -S --needed git
```
```bash
git clone -b claude/dreamy-thompson-w24gzl https://github.com/oreo1298/ACoreboot.git
```
```bash
cd ACoreboot
```
```bash
scripts/build-arch.sh
```

What it does:

1. Installs the missing packages (base-devel, gcc-ada, acpica, nasm, imagemagick, …).
2. Fetches coreboot at the pinned commit and applies `patches/`.
3. Builds the cross toolchain.
4. Builds every variant into `out/`, with `out/SHA256SUMS`.

Options and notes:

- Build only some variants: `scripts/build-arch.sh A B`.
- Put your board's MAC into the full images:
  `MAC=xx:xx:xx:xx:xx:xx scripts/build-arch.sh`.
- **First run:** about 35 min and about 20 GB of disk (cross toolchain, plus the
  EDK2 checkout for variant C). Later runs take a few minutes.
- If pacman reports packages not found, your package database is stale. Run
  `sudo pacman -Syu` and retry.
- The repository is private: `git clone` asks for your GitHub login (a token, not
  your password). With SSH keys, clone `git@github.com:oreo1298/ACoreboot.git`
  instead.
- `out/` is tracked in git, so a local rebuild shows up as modified files. Run
  `git checkout -- out` before you `git pull`.
- Tested in a clean Arch Linux container (host GCC/GNAT 16.2.1) as a non-root user.

Other distributions: `scripts/setup.sh && scripts/build.sh`. `setup.sh` installs the
packages with apt or pacman.

## Variants

| Variant | Payload | Display | Use |
|---|---|---|---|
| A | SeaBIOS | libgfxinit (HDMI, DP) | legacy boot |
| B | SeaBIOS | FSP GOP (HDMI, DP, VGA) | legacy boot with VGA |
| C | EDK2 (UEFI) | FSP GOP (HDMI, DP, VGA) | UEFI boot, **tested** |

- **To disable the Intel ME** (verified on the board):
  - C: setup menu, Device Manager > Platform Setup Menu > Intel Management Engine.
  - A/B: `nvramtool -w me_state=Disable`.
  - It can be undone. Details in BRINGUP.md §9.
- The former D/E "HAP" variants were removed: the ME ran normally with them.

## Documents

- [BRINGUP.md](BRINGUP.md) — **read first**: flashing, serial console, boot
  milestones, test checklist, what to capture.
- [SUMMARY.md](SUMMARY.md) — feature status, first-boot risks, ROM checksums.
- [DECISIONS.md](DECISIONS.md) — every assumption, with its source and confidence.
- [AUDIT.md](AUDIT.md) — the independent review of the port.
- `patches/` — the coreboot patch series (intelp2m CNL-H support, NCT6793D Super I/O
  driver, board port).
