# BRINGUP — ASUS PRIME B360M-C, first boot of coreboot

For you, at the bench. Read §0 and §2 before you flash anything.
Values marked *(verify)* are not from your board; DECISIONS.md has the details.

## 0. Before the first flash

1. **Dump the chip twice** with the external programmer and compare the files. Keep
   the dump and put a copy into `board-data/vendor/` (any `*.bin`).
   - `scripts/extract_blobs.sh --force && scripts/build.sh` then rebuilds every ROM
     with *your* descriptor, ME and GbE. Your MAC is in the GbE region; the capsule's
     GbE has the placeholder MAC `88:88:88:88:87:88`.
   - Until you do that, flash **BIOS region only** (§2.1). That keeps your IFD, ME
     and GbE untouched.
2. Note the MAC from the board sticker or from `ip link` under the vendor firmware.
3. Under the vendor firmware, collect the reference dumps listed in §7 ("vendor"
   column). They turn most of DECISIONS.md into verified values.
4. Fit the PSU and one DIMM in **DIMM_A2** (the manual marks A2/B2 with "*", the
   usual ASUS mark for the slots to populate first). Attach a monitor to **HDMI**,
   connect the COM1 header (§3) and, if you have one, an ASUS LPC debug card on
   `LPC_DEBUG`.
   - If that DIMM does not train (§4), try `DIMM_A1` next; see §5.

## 1. The ROMs in `out/`

| File | Payload | Display init | Flash regions | Use |
|---|---|---|---|---|
| `asus_prime-b360m-c_A_seabios_libgfxinit.rom` | SeaBIOS | libgfxinit (HDMI, DP1, DP2) | full 16 MiB: vendor IFD + ME + GbE from the capsule | **first boot** |
| `asus_prime-b360m-c_B_seabios_fspgop.rom` | SeaBIOS | Intel FSP GOP (VBT-driven, includes VGA) | same | display fallback; VGA |
| `asus_prime-b360m-c_C_edk2_fspgop.rom` | EDK2 UefiPayloadPkg (coreboot default, MrChromebox fork) | FSP GOP | same | UEFI boot |
| `*.bios-region.bin` | | | the 13 MiB BIOS region (0x300000-0xFFFFFF) of the same ROM | layout-based flashing |
| `*.cbfs.txt`, `*.ifd.txt`, `*.config` | | | CBFS listing, descriptor dump, full .config | reference |

- Every ROM uses the console on COM1 at 115200 8N1, POST codes on port 0x80 and
  log level 7 (DEBUG).
- A, B and C carry the vendor descriptor byte-for-byte (`build.sh` checks it).
- **C is hardware-tested:** it boots Linux with NVMe, LAN, audio, USB and HDMI working.
- **The former D/E variants are gone.** They set PCHSTRP0 bit 16 ("HAP"), and on
  hardware the ME still ran normally, so that bit is not HAP on this chipset. To
  disable the ME, use the `me_state` option (§9) instead.

## 2. Flashing

The SPI flash is 16 MiB, 3.3 V. The descriptor's VSCC table lists Winbond W25Q128 and
GigaDevice GD25Q128 *(verify the part on the board)*. Unplug the ATX cable
completely before you clip on in-circuit.

### 2.1 BIOS region only (recommended for the first boots)

This keeps your descriptor, ME and GbE.

```bash
flashrom -p ch341a_spi -r backup1.bin
```
```bash
flashrom -p ch341a_spi -r backup2.bin
```
```bash
cmp backup1.bin backup2.bin
```
```bash
flashrom -p ch341a_spi --ifd -i bios -w out/asus_prime-b360m-c_A_seabios_libgfxinit.rom
```

- Use your programmer's `-p` name.
- `--ifd` reads the layout from the descriptor already on the chip, so the full-size
  ROM file is the right input.

Once coreboot runs, you can do the same internally:

```bash
flashrom -p internal --ifd -i bios -w out/asus_prime-b360m-c_B_seabios_fspgop.rom
```

- The vendor descriptor makes the IFD and ME read-only for the host. Internal
  flashing of a full image will fail; that is expected.
- From the vendor BIOS, internal writes may also be blocked by its BIOS-region
  protection. Use the programmer for the first flash.

### 2.2 Full image (external programmer only)

```bash
flashrom -p ch341a_spi -w out/asus_prime-b360m-c_A_seabios_libgfxinit.rom
```

This writes the capsule's descriptor, ME (factory-fresh CSME 12.0.64.1551) and GbE
(placeholder MAC) unless you rebuilt from your own dump. To keep your MAC without a
dump:

```bash
MAC=xx:xx:xx:xx:xx:xx scripts/build.sh A
```

### 2.3 Restoring your own descriptor and GbE (MAC)

After a full-image flash, the chip holds the capsule's descriptor and GbE region.
Your board then shows the placeholder MAC `88:88:88:88:87:88`. To put your own
regions back from your backup, keeping the coreboot BIOS region:

```bash
flashrom -p ch341a_spi --ifd -i fd -i gbe -w backup1.bin
```

- `--ifd` takes the layout from the chip; `-i fd -i gbe` writes only those two
  regions, taken from `backup1.bin`.
- Without a backup, set the MAC from the board sticker instead: build with
  `MAC=xx:xx:xx:xx:xx:xx`, then flash with `--ifd -i gbe`.

### 2.4 Restore

```bash
flashrom -p ch341a_spi -w backup1.bin
```

After switching firmware, short **CLRTC** for a few seconds with the board unpowered.
coreboot and the vendor BIOS use CMOS differently.

## 3. Serial console (COM1 header)

| Pin | Signal | | Pin | Signal |
|---|---|---|---|---|
| 1 | DCD | | 2 | RXD (into board) |
| 3 | TXD (out of board) | | 4 | DTR |
| 5 | GND | | 6 | DSR |
| 7 | RTS | | 8 | CTS |
| 9 | RI | | 10 | (no pin, key) |

- This is the standard ASUS 10-1 pin COM header layout. The manual (rev 3) has no
  pinout figure, so **verify** it on the board.
- **Levels are RS-232**, not TTL: the header is driven through the board's RS-232
  transceiver. Before you connect a 3.3 V/5 V USB-TTL adapter, measure TXD (pin 3)
  against GND (pin 5) with the board in S0. A negative idle voltage (about -5 to
  -10 V) means RS-232: use a USB-RS232 adapter or a MAX3232 level shifter.
  Connecting a TTL adapter directly can destroy the adapter.
- Settings: **115200 8N1, no flow control.**
  - Linux: `picocom -b 115200 /dev/ttyUSB0`
  - Linux, logging to a file: `screen -L /dev/ttyUSB0 115200`
- The same console is also in CBMEM: run `cbmem -c` from Linux.
- COM2 (UART B, 0x2F8, IRQ 3) and LPT (0x378, IRQ 7) are enabled for the OS. They
  carry no firmware output.

## 4. Expected console milestones and what a hang means

POST codes (port 0x80, LPC_DEBUG header) are in brackets. FSP-M/FSP-S also post
their own codes while they run.

| # | Console text | Normal duration | If it stops here |
|---|---|---|---|
| 0 | *(nothing at all, POST 0x01/0x10/0x21 or nothing)* | — | See row 0 notes below. |
| 1 | `coreboot-… bootblock starting (log level: 7)...` [0x40] | <0.1 s | — |
| 2 | `FMAP: area COREBOOT found`, `CBFS: Found 'fallback/romstage'` | <0.1 s | Hang after bootblock banner but before romstage: GPIO table (applied at the end of bootblock). Remove `mainboard_configure_gpios()` from `bootblock_mainboard_init()` to test. |
| 3 | `romstage starting` [0x13], SPD dump lines | <1 s | SMBus/SPD: no DIMM found → check slot (§5), SPD addresses `romstage.c`. |
| 4 | `FSP-M` (`fsp_memory_init`) [0x92] … returns [0x98] | **first boot 20-90 s** (training), later <5 s (MRC cache) | See row 4 notes below. |
| 5 | `CBMEM: …`, `postcar`, `ramstage starting` | <1 s | Rare. Cache-as-RAM teardown; report the log. |
| 6 | `FSP-S` / `fsp_silicon_init` [0x93] … [0x99] | 1-3 s | See row 6 notes below. |
| 7 | PCI enumeration [0x24/0x25], `PCI: 00:1c.x`, `gfx: …` / `GMA: …` | 1-3 s | Device enable/resource issues: report the log (devicetree). Display: libgfxinit prints the ports it probed. |
| 8 | ACPI/SMBIOS tables [0x79/0x9c], `Jumping to boot code` [0xf3] | <1 s | — |
| 9 | SeaBIOS banner / EDK2 logo | | Payload; try another variant. |

**Row 0: no output at all.**
- Check RS-232 levels and pins (§3).
- With an LPC debug card: a code means the CPU runs and the serial path is wrong;
  no code at all means no reset vector.
- Reflash and verify. Check the IFD region boundaries in `*.ifd.txt` (BIOS
  0x300000-0xFFFFFF).
- If the CPU runs but the serial stays silent, the Super I/O pin-mux writes in
  `bootblock.c` are the prime suspect. Try commenting out the CR27/CR2A/CR2F/LDN12
  writes; only `nuvoton_enable_serial()` is needed for the console.

**Row 4: hang inside FSP-M (memory init).** In order:
1. Let it run 2 minutes.
2. Try one DIMM in each slot alone (§5) to find the SPD-to-slot mapping.
3. Use a known-good DDR4-2400/2666 single-rank stick.
4. Reset/reboot loops here (the console restarts at row 1) are normal once or twice
   when FSP changes settings. Endless loops: report the log.

**Row 6: hang inside FSP-S (silicon init).**
- PCIe: all 24 root ports are enabled and every reference clock runs free.
  Disable unpopulated ports in `devicetree.cb` one controller at a time.
- GbE: remove `gbe` if the GbE region does not match.
- Graphics (B/C only): FSP GOP + VBT.
- A hang right after `FSP-S` *returns* is usually a coreboot driver: report the log.

## 5. Memory slot mapping test *(verify DECISIONS D-016)*

SPD addresses in the firmware are 0x50 = channel A DIMM0, 0x51 = A DIMM1,
0x52 = B DIMM0, 0x53 = B DIMM1.

1. Under the vendor firmware, put one DIMM in each slot in turn:
   ```bash
   decode-dimms
   ```
   Or `i2cdetect` on the i801 bus. Write down which slot answers at which address.
2. Under coreboot, boot with one DIMM in each slot in turn. Each must train and
   show up with full size in `free -m`.
3. If a slot fails while the vendor firmware sees its SPD at the expected address,
   the DIMM0/DIMM1 order within a channel is swapped. Swap spd[0]/spd[1] and
   spd[2]/spd[3] in `romstage.c`.

## 6. Test checklist (in feature priority order)

| # | Feature | How to test | Pass |
|---|---|---|---|
| 1 | Payload + serial | console reaches row 9; SeaBIOS menu (ESC) visible on serial | ☐ |
| 2 | RAM, all slots | one DIMM per slot (§5), then 2 and 4 DIMMs; `memtest86+` 1 pass | ☐ |
| 3a | HDMI (A) | SeaBIOS text on HDMI; Linux console on HDMI | ☐ |
| 3b | DP1, DP2 (A) | same on each DP | ☐ |
| 3c | VGA (B, C) | output on D-Sub with variant B. Not supported with A/D: libgfxinit cannot drive the DDI E converter | ☐ |
| 4 | SATA, NVMe | a disk on each SATA6G_1..6. NVMe in M.2_1 and M.2_2. M.2_1 SATA SSD (disables SATA6G_2). Boot from each | ☐ |
| 5 | USB | each rear and header port with a USB2 and a USB3 device; compare `lsusb -t` with DECISIONS D-014 | ☐ |
| 6 | LAN | `ip link` shows I219-V, link and DHCP; MAC as expected (§0) | ☐ |
| 7 | Audio | rear line out, front HP, rear and front mic; HDMI audio; `aplay -l` | ☐ |
| 8 | PCIe/PCI | GPU in PCIEX16; cards in PCIEX1_1/2; card in PCI slot (behind ASM1083); `lspci -tv` | ☐ |
| 9 | S3 | `systemctl suspend`, wake by power button / keyboard, devices still work | ☐ |
| 10 | COM2, LPT, PS/2, fans | loopback on COM2; PS/2 keyboard+mouse; **fans spin** (they should run at power-on default, likely full speed) | ☐ |
| 11 | TPM | not implemented | — |

Thermal sanity check: stress all cores (`stress-ng --cpu 0`) for 10 minutes.
- Watch `sensors` / `turbostat`: package temperature and power must stay within
  spec.
- PL1 is TDP and PL2 is 1.25×TDP (Intel default); no overrides are set.

## 7. What to capture and bring back

`cbmem` and `inteltool` are coreboot utilities, not distro packages. Arch has
them only in the AUR. Build them from the checkout that `setup.sh` created:

```bash
make -C coreboot/util/cbmem
```
```bash
make -C coreboot/util/inteltool
```

- Run them as `sudo coreboot/util/cbmem/cbmem …` and
  `sudo coreboot/util/inteltool/inteltool …`.
- If inteltool fails with an mmap or permission error, the kernel is blocking
  `/dev/mem`. Boot once with `iomem=relaxed` on the kernel command line.
- `lsusb` is in the `usbutils` package.

Put everything into `board-data/dumps/` (create subfolders `vendor/` and `coreboot/`).

| Capture | vendor | coreboot | Command |
|---|---|---|---|
| Full SPI dump | ✔ | | `flashrom -p <prog> -r spi.bin` (also into `board-data/vendor/`) |
| Serial log, cold boot | | ✔ | full log from power-on to payload (`screen -L`), one per variant tried |
| CBMEM console | | ✔ | `cbmem -c > cbmem.txt`; `cbmem -t > timestamps.txt` |
| GPIO | ✔ | ✔ | `inteltool -G > inteltool-G.txt` |
| Other inteltool | ✔ | ✔ | `inteltool -a > inteltool-a.txt` (needs `iomem=relaxed`) |
| ME | ✔ | ✔ | `intelmetool -m -b > intelmetool.txt` (`-b` = Boot Guard status) |
| Super I/O | ✔ | ✔ | `superiotool -deV > superiotool.txt` |
| PCI | ✔ | ✔ | `lspci -nnvvvxxx > lspci.txt`; `lspci -tv > lspci-tree.txt` |
| USB | ✔ | ✔ | `lsusb -t > lsusb-t.txt`; `lsusb -v > lsusb-v.txt` |
| Kernel log | ✔ | ✔ | `dmesg > dmesg.txt` |
| ACPI | ✔ | | `acpidump > acpidump.txt` |
| HDA | ✔ | ✔ | `cat /proc/asound/card*/codec#* > codecs.txt` |
| SPD | ✔ | | `decode-dimms > decode-dimms.txt` (with the DIMM-per-slot notes of §5) |
| Sensors | ✔ | ✔ | `sensors > sensors.txt`; `superiotool -deV` already includes HWM |

The most valuable item is `inteltool -G` under the vendor firmware:

```bash
scripts/gpio_check.py --dump board-data/dumps/vendor/inteltool-G.txt
```

- This diffs the coreboot GPIO table against the real registers. The pads FSP or RC
  changed after the vendor table, most likely CLKREQ#, are the next thing to fix.
- `inteltool -G` under coreboot against that same vendor dump shows any remaining
  difference.

## 8. Rebuilding

### Arch Linux (one-shot)

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

- `build-arch.sh` installs the missing packages (base-devel, gcc-ada, acpica,
  nasm, imagemagick, …) and runs `setup.sh` and `build.sh`.
  - Build a subset with `scripts/build-arch.sh A B`.
  - Use `MAC=xx:xx:xx:xx:xx:xx scripts/build-arch.sh` to put your MAC into the full
    images.
- **First run:** about 35 min and about 20 GB of disk. That covers the cross
  toolchain plus the EDK2 checkout with all its submodules for variant C. Later runs
  take a few minutes.
- **Tested** in a clean Arch Linux container (bootstrap 2026.11.01, host GCC/GNAT
  16.2.1) as a non-root user: all variants built.
- If pacman reports packages not found, your package database is stale. Run
  `sudo pacman -Syu` and rerun.
- `out/` is tracked in git, so a local rebuild shows up as modified files. Run
  `git checkout -- out` before you `git pull` updates.

### Any distribution

```bash
scripts/setup.sh
```
```bash
scripts/build.sh
```

- `setup.sh` is idempotent: coreboot at the pinned commit, patches applied,
  toolchain, blobs.
- `build.sh` builds A B C into `out/` and checks IFD/ME/GbE and CBFS. Build a
  subset with e.g. `scripts/build.sh A B`.
- Change board code in `coreboot/src/mainboard/asus/b360m-c/` and commit there,
  then regenerate the series:
  ```bash
  git -C coreboot format-patch -o ../patches c49935a4
  ```
- GPIO table from a real dump: run `util/intelp2m -p cnl-h -file inteltool-G.txt`
  and feed its output to `scripts/gen_gpio_c.py`, as the current table was made.
  `gen_gpio_c.py` takes ownership from `gpio_vendor_expected.json`.

## 9. Disabling the ME (`me_state`)

coreboot can ask the ME to switch itself off over HECI (Intel's "Soft Temporary
Disable"). It doesn't touch the flash descriptor and can be undone. The setting is
a CMOS option.

1. Build `nvramtool` from the checkout:
   ```bash
   make -C coreboot/util/nvramtool
   ```
2. Set the option:
   ```bash
   sudo coreboot/util/nvramtool/nvramtool -w me_state=Disable
   ```
3. Reboot. coreboot sends the request and does a full (global) reset, so the
   board resets once more by itself.
4. Check the result:
   ```bash
   lspci -s 00:16.0
   ```
   No output means the ME interface is gone.
   ```bash
   sudo coreboot/util/cbmem/cbmem -c | grep 'ME:'
   ```
   The "Current Operation Mode" should no longer be 0.

- Undo with `me_state=Enable` and a reboot.
- Clearing CMOS (CLRTC) restores the default (Enable).
- `me_state_counter` stops retry loops if the ME refuses the change three times.

