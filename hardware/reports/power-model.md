# Tag power and pulse model

**Status: SIMULATED, not hardware validated.** This workstream adds a
configurable 24-hour charge budget and an ngspice single-beacon source-dip
simulation. The starting concept is STM32L031K6 + SX1262 + LIS2DW12. Battery
chemistry/capacity and the final module/antenna are not selected. Circuit
capture in KiCad is still pending because `kicad-cli` is unavailable here.

## Observed run

Inputs: 1,440 beacons/day (the firmware's 60-second default), 120 ms configured
airtime per beacon, 30 ms MCU-active time per beacon, 100 ms receive window per
beacon, firmware TX power +10 dBm, a conservative 45 mA TX current proxy,
SX1262 RX current 4.6 mA, STM32L031 STOP 0.35 µA, MCU active current
derived as 76 µA/MHz × 4 MHz, and an 0.8 µA low-power IMU estimate. The model
uses an assumed 0.6 µA radio sleep allowance. All are editable in
[`power_profile.json`](../spice/power_profile.json), with a status and
provenance field for each value.

| Metric | Result | Status |
|---|---:|---|
| Estimated charge in 24 h | 2.416305 mAh/tag | SIMULATED, mixed inputs |
| Average current | 100.679 µA | SIMULATED, mixed inputs |
| Configured peak during TX | 45.3048 mA | SIMULATED, conservative TX-current proxy + derived MCU + assumed IMU |
| Messages per day | 1,440 | ASSUMED/configured, one per 60 s |
| Battery autonomy | Not calculated | Capacity is null/unselected |
| ngspice minimum tag rail during TX pulse | 3.164086 V | SIMULATED, assumed 3.3 V source + 3 Ω + 47 µF |
| Brownout threshold comparison | Above configured 1.8 V threshold | SIMULATED; threshold is configurable |

The nominal day consists of 23.9 h sleep, 43.2 s MCU-active work, 172.8 s TX, and
144 s RX. The integration harness separately measured 7,344 TX for its mixed
24-hour motion profile and 14,640 TX for 24 hours stationary after the assumed
4-hour stillness alarm. Re-running the same current model with those traffic
counts estimates 12.150956 mAh/day and 24.180767 mAh/day, respectively. These
are simulated traffic-profile extrapolations using the same conservative TX
current proxy, not cell measurements; neither has an autonomy calculation.

The 45 mA TX input is **not** sourced for the firmware's +10 dBm
configuration: it is a conservative proxy referencing Semtech's +14 dBm
figure. This choice avoids pretending to know the +10 dBm current; it may
overstate consumption. Replace it with a sourced +10 dBm value or board
measurement before using this estimate to compare architectures. As a
calculation-path check only, an explicit temporary `--capacity-mah 2200` run
produced 910.481 days. That is extrapolation from configured estimates, not
a selected battery or field-life prediction, and must not be used as a product
claim. The checked-in default deliberately has no capacity, so no autonomy is
reported.

## Electrical topology

```text
3.3 V battery equivalent ── Rcell (3 Ω assumed) ── TAG_RAIL
                                                   ├── 47 µF reservoir
                                                   ├── MCU + clock state load
                                                   ├── SX1262 TX/RX/sleep load
                                                   └── LIS2DW12 low-power load
GND ──────────────────────────────────────────────┴── common return
```

The ngspice transient represents one 120 ms TX pulse, not a full day or an
actual battery. Its 3.3 V input and 3 Ω source impedance are illustrative
configuration values, and the 47 µF capacitor is an initial placement
assumption. It does not model regulator efficiency, cell electrochemistry,
voltage-vs-state-of-charge, ESR vs temperature, RF matching losses or junction
temperature. The estimated instantaneous electrical input is about 149.5 mW
at the configured TX level; this alone does not establish die temperature or
thermal safety.

## Provenance and limits

- ST lists 0.35 µA typical STOP current and down to 76 µA/MHz RUN current for
  STM32L031; actual clock/peripheral setup changes the result. [STM32L031K6
  datasheet](https://www.st.com/resource/en/datasheet/stm32l031k6.pdf)
- Semtech lists 45 mA at +14 dBm and 118 mA at +22 dBm for SX1262, and 4.6 mA
  receive current. The configured firmware power is +10 dBm, for which this
  report does not assert that 45 mA is the datasheet value; it is only an
  explicitly marked conservative proxy until a +10 dBm source/measurement is
  available.
  [Semtech SX1262 data](https://www.semtech.com/amazon-sidewalk-lora),
  [SX1262 product page](https://www.semtech.com/products/wireless-rf/lora-connect/sx1262)
- ST describes LIS2DW12 active low-power mode as below 1 µA. The configured
  0.8 µA is an estimate within that bound, not a measurement for a specific
  ODR/mode. [LIS2DW12 product page](https://www.st.com/en/mems-and-sensors/lis2dw12.html)
- Airtime, firmware awake time, receive-window size, radio sleep allowance,
  cell impedance, capacity, bypass capacitance and brownout threshold are
  configurable assumptions. The radio sleep allowance is especially
  board-dependent and requires verification against the selected module and
  measured leakage.
- Passive 134.2 kHz RFID is represented as zero DC load in this power budget;
  any active reader circuitry or tag interactions are out of scope.

ngspice 42 was available at `/tmp/riose-ngspice-local/usr/bin/ngspice` and ran
the generated deck successfully. It is not globally installed. KiCad CLI was
not available, so no schematic/PCB validation is claimed. To reproduce,
follow [`hardware/spice/README.md`](../spice/README.md); outputs are in
[`hardware/spice/results`](../spice/results/summary.json).

## Next physical measurement

Use the intended STM32L031 + SX1262 module + LIS2DW12 prototype on a source
meter or a calibrated current analyzer. Capture sleep, MCU wake + IMU read,
the exact LoRa TX power/modulation/payload duration, receive window, and
standby/sleep leakage over temperature. Then replace the assumed values and
source impedance with the chosen battery supplier's data and measured pulse
response before calculating autonomy.
