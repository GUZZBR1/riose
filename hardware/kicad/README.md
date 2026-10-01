# Initial tag power-tree capture notes

KiCad is not available in the current build environment (`kicad-cli` was not
found), so this workstream supplies the electrical topology and a runnable
ngspice equivalent rather than claiming a validated KiCad schematic or PCB.
Capture the following as a KiCad schematic once KiCad is installed:

```text
BAT+ (nominal/configurable 3.3 V equivalent)
  ├── local bypass capacitor Cbulk to GND
  ├── STM32L031K6 VDD, VDDIO, VDDA; decoupling at each supply pin
  ├── SX1262 VBAT / VBAT_RF; local bulk + high-frequency bypass
  ├── LIS2DW12 VDD/VDDIO; local bypass
  └── passive animal RFID element (no DC load modeled here)
BAT- / GND ── common return
```

This is a first-pass direct rail budget: 3.3 V is used as a configurable
nominal supply and is inside the STM32L031, SX1262 and LIS2DW12 supply ranges.
It is not a battery recommendation. Battery chemistry, capacity, pulse
impedance, protection, charging, regulator choice and brownout margin remain
unselected. The current ngspice deck models the source as an ideal voltage
plus configurable series resistance and one bypass capacitor. Component
provenance and the pulse results are in `../spice/power_profile.json` and
`../reports/power-model.md`.
