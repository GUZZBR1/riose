# Candidate battery and rail transient model

**Evidence status: SIMULATED.** This is a narrow source/rail sensitivity model
for a proposed compact tag supply:

- Cell: Tadiran TLL-5902, one 1/2-AA Li-SOCl2 cell, 3.6 V nominal and 1.1 Ah
  nominal capacity. The datasheet specifies up to 50 mA recommended continuous
  current and 100 mA pulse current; observe its conditions and pulse duration
  when selecting the actual operating profile.
- Regulator: TI TPS62840 candidate, buck topology, 3.3 V output. TI lists
  1.8–6.5 V input and 750 mA output capability. This deck does not contain a
  TPS62840 vendor SPICE model.
- Stress load: radio 45 mA at **+14 dBm** (stress proxy), followed by 100 ms
  RX at 4.6 mA. Firmware currently configures +10 dBm; 45 mA is not asserted
  as a +10 dBm measurement. Semtech publishes 45 mA at +14 dBm for SX1262
  and 4.6 mA receive current; MCU and IMU loads are added from the existing
  profile assumptions.

The script runs an ngspice sweep over battery terminal voltage, source ESR and
rail output capacitance:

```sh
python3 hardware/spice/candidate/run_sweep.py \
  --ngspice /path/to/ngspice
```

By default it keeps `sweep.csv` and `summary.json`; transient successful decks
and logs are removed. Pass `--keep-decks` to preserve the 150 individual
netlists/logs, or failure decks/logs remain automatically for inspection.
Modify `profile.json` to change the sweep. On this workstation
the command was run with ngspice 42 at
`/tmp/riose-ngspice-local/usr/bin/ngspice`.

## Observed sweep

The checked-in run contains 150/150 successful ngspice invocations. `vrail_min`
is the lowest modeled 3.3 V rail during TX+RX, across the 15 combinations of
assumed ESR and output capacitor at each cell voltage:

| Cell input voltage (assumed) | Lowest rail | Highest modeled cell current | Combinations below assumed 2.7 V threshold |
|---:|---:|---:|---:|
| 3.6 V | 3.2909 V | 50.262 mA | 0/15 |
| 3.4 V | 3.1841 V | 53.410 mA | 0/15 |
| 3.3 V | 3.0807 V | 55.143 mA | 0/15 |
| 3.2 V | 2.9769 V | 56.996 mA | 0/15 |
| 3.0 V | 2.7687 V | 61.120 mA | 0/15 |
| 2.9 V | 2.6641 V | 63.426 mA | 3/15 |
| 2.8 V | 2.5591 V | 65.922 mA | 15/15 |
| 2.7 V | 2.4537 V | 68.634 mA | 15/15 |
| 2.4 V | 2.1341 V | 78.411 mA | 15/15 |
| 2.0 V | 1.6961 V | 97.439 mA | 15/15 |

The maximum modeled battery-side pulse current across this sweep is 97.439 mA;
the profile records 100 mA as the candidate cell's pulse limit. This is a
comparison between the assumed average converter and load model and the stated
cell rating. It does not establish compliance with the battery datasheet's
specific pulse-duration, temperature, or state-of-discharge conditions. The
2.7 V line is an assumed design threshold, not an observed MCU brownout. The
voltage sweep is a set of independent points, not a cell discharge curve. The
TLL-5902's 2.0 V point is the datasheet's rated capacity endpoint under 1 mA
load; it is included only as an end-of-capacity stress point and is not a valid
TX operating condition. A buck set to 3.3 V cannot regulate that output below
its input headroom, and the sweep does not establish whether the downstream
components remain reliable at a lower rail. The 1.1 Ah nominal rating is not
demonstrated usable capacity for this design and must not be turned into a
runtime claim. Measure cutoff under load or investigate a lower rail or
buck-boost design before treating this battery/regulator pairing as viable.

## What the deck models

It uses a nominal cell voltage source, explicit assumed series ESR, battery
bypass capacitor, an output load profile, and an averaged battery-side current
behavioral source computed as `Pout/(Vcell_loaded * assumed_efficiency) + Iq`.
An idealized regulated target sits behind assumed output resistance and
output-capacitor ESR, with the capacitor connected at the rail. The regulator
has no modeled
switching control loop. The regulator target is 3.3 V until the input falls below the assumed
0.1 V headroom; below that, the rail follows the input minus that headroom.
TX rises over 0.5 ms, remains at the configured current for 120 ms, then RX
lasts 100 ms. This exposes sensitivity to source impedance and rail storage.
Since the input current uses the loaded raw cell voltage, cell sag increases the
calculated input current; output regulation and current limits still are not
modeled with the device's internal control loop.

ESR points (0.1–2 ohm), cell-voltage points (2.0–3.6 V), regulator efficiency
(85%), dropout/headroom (0.1 V), output resistance (0.15 ohm), and capacitor
values/ESRs are **ASSUMED sweep points or simplifications**. They are not
TLL-5902 cell characterization or TPS62840 measurements. The assumed 2.7 V
functional rail threshold is a comparison line only; no board brownout setting
was measured. Battery voltage points are independent DC operating points, not
a discharge curve. The 1.1 Ah capacity is recorded for the candidate but this
transient script does not predict service life.

This model omits regulator soft start, loop response, current limit behavior,
switching ripple, actual cell electrochemistry and temperature/ageing effects,
PCB trace/contact resistance, antenna or RF mismatch, and MCU brownout/reset
behavior. The result is not a substitute for an assembled board. Validate with
a pulse-capable source meter or scope/current probe and the actual cell over
fresh and depleted voltage states before relying on margin.

Sources: [Tadiran TLL-5902 datasheet](https://tadiranbat.com/wp-content/uploads/2022/03/tll-5902.pdf),
[TI TPS62840 product page](https://www.ti.com/product/TPS62840),
[Semtech SX1262 current table](https://www.semtech.com/amazon-sidewalk-lora),
[Semtech SX1262 product page](https://www.semtech.com/products/wireless-rf/lora-connect/sx1262).
