# PROGRESS — coreboot port for ASUS PRIME B360M-C

Resume rule: after any restart / context compaction, re-read this file and
DECISIONS.md before doing anything else. Then `scripts/setup.sh` (idempotent)
restores ./coreboot with the patch series applied.

## Inputs actually available (gap analysis)
- ONLY input provided: ASUS update capsule `board-data/vendor/PRIME-B360M-C-ASUS-3202.CAP`
  (BIOS 3202, 07/10/2021). It is a 0x800-byte AMI capsule header + full 16 MiB SPI image
  (IFD + GbE + ME + BIOS). **No external-programmer dump, no board-data/dumps/*, no notes.md.**
- Everything that would have come from dumps is derived from the vendor image instead
  (see DECISIONS.md D-001 .. ) or taken from reference boards and marked TODO(verify).

## Phase checklist
- [x] P0 repo skeleton, .gitignore, vendor capsule committed
- [x] P0 toolchain: crossgcc-i386 (gcc 15.2.0) + nasm + iasl built with `BUILDGCC_OPTIONS=-m` (~10 min)
- [x] P0 reference build: asrock/h370m-itx_ac unmodified builds (logs/ref-h370m.log)
- [x] P1 survey: template asrock/h370m-itx_ac; refs cfl_s RVP, asus/h610m-k (ASUS/Nuvoton style), asrock/h110m (DDI-E VGA)
- [x] P2 IFD/regions/ME -> blobs/ (scripts/extract_blobs.sh)
- [x] P2 Boot Guard: FIT has only 4 microcode entries -> not provisioned
- [x] P2 GPIO: vendor_gpio.py -> intelp2m -p cnl-h -> gen_gpio_c.py; gpio_check.py 0 unexplained
- [x] P2 PCI/USB/SATA mapping (SMBIOS type 8/9 + manual; see DECISIONS D-012..D-015)
- [x] P2 Super I/O NCT6793D: vendor PEI init table decoded (D-010)
- [x] P2 HDA verbs from vendor PEIM 60c33d7a
- [x] P2 VBT + DDI mapping (B=DP1, C=DP2, D=HDMI, E=VGA bridge)
- [x] P2 memory: SPD A0/A2/A4/A6 (FSP default, no vendor override)
- [x] P2 ACPI: vendor DSDT only gives SIO data
- [x] P3 port written: patches 0001 intelp2m cnl-h, 0002 superio nct6793d, 0003 board + Documentation page
- [x] P4 A/B/C/D built + region checks; scripts/check.sh: abuild, lint-stable, checkpatch 0/0, gpio_check all PASS
- [x] DoD#1 fresh clone (`git clone` of this repo) -> setup.sh && build.sh: toolchain + A/B/C/D all OK
      (2026-11-27, build part 23 min; ROM hashes differ run-to-run because of coreboot build timestamps)
- [~] P5 independent audit (first attempt hit an API usage limit; resumed). Report -> scratchpad/audit_report.md;
      then fix/justify every finding in DECISIONS (section "Audit")
- [~] P6 BRINGUP/DECISIONS/SUMMARY drafted; remaining: audit fixes, final rebuild (scripts/build.sh),
      fill SUMMARY hashes, `git add -f out/`, push

## Key facts so far
- Flash: 16 MiB, W25Q128 (JID ef4018) / GD25Q128 (c84018) in VSCC table.
- Layout: IFD 0x0-0xfff, GbE 0x1000-0x2fff, ME 0x3000-0x2fffff, BIOS 0x300000-0xffffff.
- FLMSTR1 (host): ME region read-only, IFD read-only -> internal flashing of BIOS region only.
- ME: CSME 12.0.64.1551 (consumer). GbE region carries placeholder MAC 88:88:88:88:87:88,
  I219-V device id 0x15bc.
- Boot Guard: FIT = header + 4 microcode entries; no Startup ACM / KM / BPM -> not provisioned.
- Super I/O: Nuvoton NCT6793D (SMBIOS type 34 + DSDT SIO1, config 0x2E, keys 0x87/0xAA),
  DSDT LDN map: UARTA=2, UARTB=3, LPT=1, KBC=5, CIR=6. HWM base 0x290 len 0x10.
- SMBIOS slots (vendor static table): PCIEX16=00:01.0, PCIEX1_1=00:1c.3, PCIEX1_2=00:1c.4,
  PCI(ASM1083)=00:1c.5.
- VBT: FFS file 56752da9-de6b-4895-8819-1945b6b76c22 ("$VBT SKYLAKE", 4449 bytes valid).
- GPIO: ASUS board PEIM 2accd044-284c-432f-9a1a-4cde31036c9f holds a 228-entry
  GPIO_INIT_CONFIG table covering every CNP-H pad (A..K, GPD).

## Toolchain record
- coreboot crossgcc @ c49935a4: GCC 15.2.0, binutils 2.46.1, NASM 3.02, IASL 20251212 (DECISIONS D-024)

## Working notes
- coreboot tree: branch asus-prime-b360m-c in ./coreboot, commits on top of c49935a4; regenerate
  patches with `git -C coreboot format-patch -o ../patches c49935a4`.
- git to github.com works through the proxy (web pages 403); EDK2 clone is ~6+ GB.
