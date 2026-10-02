# Candidate hardware power tree

**Evidence: ASSUMED / SIMULATED.** A candidate supply is now selected for
bench evaluation. There is no KiCad schematic, PCB, assembled prototype, or
physical rail measurement checked in yet. The ngspice study is a simplified
average-load sensitivity model, not a switching-regulator model.

```text
Tadiran TLL-5902, 3.6 V nominal, 1/2 AA Li-SOCl2 (primary, not rechargeable)
  └── TPS62840 buck, candidate output 3.3 V
       ├── STM32L031K6 MCU (test platform candidate)
       ├── Semtech SX1262MB2CAS 915 MHz mbed shield (wired test candidate)
       └── LIS2DW12 IMU
Passive 134.2 kHz animal RFID identity element: represented in architecture;
  it is not powered from this rail and has no reader/load in this prototype.
```

The NUCLEO firmware wiring profile is written for the Semtech MB2xAS shield's
external `ANT SW` control: shield D8 is wired to NUCLEO D8/PC15 and held high.
SX1262 DIO2 RF-switch control is enabled in radio setup so the shield routes
TX/RX automatically. The shield and NUCLEO-32 use jumper wires, not an
assumed mechanical stack. Use a 50-ohm load for first RF bring-up and check the
final radio configuration against Brazilian requirements before antenna
transmission. The +14 dBm profile is a characterization setting, not
regulatory approval.

The **TLL-5902 and TPS62840 are engineering candidates, not a released BOM**.
Tadiran rates the cell at 1.1 Ah under its datasheet test condition (1 mA to
2 V), recommends up to 50 mA continuous and specifies 100 mA pulse current
subject to its conditions. Those ratings do not establish capacity at the
tag's pulsed load, temperature, age, or end-of-life rail margin. TI specifies
the TPS62840 as a 1.8–6.5 V input buck with 750 mA output capability; its
60 nA typical quiescent current and a circuit-level efficiency must be
verified on the actual implementation. See
[`spice/candidate/README.md`](../spice/candidate/README.md) for the assumed
rail sweep and its limitations.

There is an unresolved compatibility risk in this pair: a buck set to 3.3 V
cannot regulate 3.3 V after its input falls below the required headroom. It is
not yet known how much of the cell's 2.0 V capacity-rating range a complete tag
could use at a lower rail, or where the radio stops operating reliably. The
rated 1.1 Ah must not be used to claim usable capacity or runtime. Before
selecting the battery, measure loaded cutoff and confirm every component's
minimum supply voltage; then evaluate a lower rail or buck-boost topology if
needed. No alternative is validated yet.

## Schematic capture checklist

When KiCad is available, capture the cell holder, reverse-polarity protection
decision, regulator and feedback, inductor, input/output capacitors, MCU
decoupling, radio peak-current bypassing, IMU decoupling, test points for
battery and 3.3 V rail, and a current-measurement link. Select every passive
from the regulator datasheet and radio layout guidance; current model values
are not component selections. Provide a removable link that lets the current
instrument measure the complete tag without routing current through the
debugger/USB power path.

The first bench setup may use an STM32 Nucleo board plus a wired SX1262 module
and LIS2DW12 breakout to validate firmware. Its board regulator, debugger LEDs
and interface circuitry can dominate sleep current. Measure MCU-only current
and complete assembly current as separate results; neither is the final
custom-brincho current. The Nucleo IDD jumper, where available, isolates MCU
current only and is not a whole-tag measurement.

## Design thresholds

The ngspice sweep's 2.7 V rail line is an **assumed design comparison point**,
not the MCU brownout threshold or a measured reset voltage. It does not model
TPS62840 switching, control-loop response, current limit, cell electrochemistry,
or the SX1262's actual TX transient. Determine reset/brownout behavior and rail
margin using the assembled circuit and a scope/current measurement before
selecting a battery or claiming runtime.

Sources: [Tadiran TLL-5902 datasheet](https://tadiranbat.com/wp-content/uploads/2022/03/tll-5902.pdf),
[TI TPS62840](https://www.ti.com/product/TPS62840),
[ST STM32L031K6](https://www.st.com/resource/en/datasheet/stm32l031k6.pdf),
[Semtech SX1262](https://www.semtech.com/products/wireless-rf/lora-connect/sx1262),
[ST LIS2DW12](https://www.st.com/en/mems-and-sensors/lis2dw12.html).
