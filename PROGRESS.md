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
- [ ] P0 toolchain (crossgcc-i386 + nasm + iasl, coreboot mirror `-m`)  — log: logs/toolchain.log
- [ ] P0 reference build of in-tree CNL PCH-H board (asrock/h370m) unmodified
- [ ] P1 reference board survey (asrock/h370m, prodrive/hermes, intel/coffeelake_rvp cfl_s, others)
- [ ] P2 IFD/regions/ME/straps -> blobs/            (done in scratch, scripts pending)
- [ ] P2 Boot Guard check                           (done: FIT has only 4 microcode entries)
- [ ] P2 GPIO table from vendor PEIM 2accd044-...   (found, converter pending)
- [ ] P2 PCI / USB / SATA mapping
- [ ] P2 Super I/O (NCT6793D @0x2E, HWM 0x290)      (identified)
- [ ] P2 HDA verbs from vendor image
- [ ] P2 VBT + DDI mapping
- [ ] P2 memory topology / SPD addresses
- [ ] P2 ACPI board bits
- [ ] P3 port written (superio driver commit, board commit)
- [ ] P4 variants A/B/C/D built, abuild/lint/checkpatch/cbfstool/ifdtool checks
- [ ] P5 independent audit
- [ ] P6 docs (BRINGUP, DECISIONS, SUMMARY, Documentation page), patches/, ROMs, push

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
- (pending)
