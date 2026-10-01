# Tag power model

This is a configurable engineering estimate, marked `SIMULATED`. Inputs are in
[`power_profile.json`](power_profile.json); provenance/status is attached to
each current. Edit those values when the exact component variant, mode, RF
power, packet settings and measured board leakage are known.

## Reproduce 24-hour estimate

```sh
python3 hardware/spice/energy_model.py
```

To execute ngspice when it is installed:

```sh
python3 hardware/spice/energy_model.py --ngspice /path/to/ngspice
```

To calculate autonomy, explicitly supply a candidate capacity, for example:

```sh
python3 hardware/spice/energy_model.py --capacity-mah 2200
```

Do not treat that example as a selected battery or an advertised lifetime.
When capacity is absent the model emits `NOT_CALCULATED_CAPACITY_UNCONFIGURED`
and leaves both lifetime fields null. Outputs are `summary.json`,
`energy_24h.csv`, a generated ngspice pulse deck and the ngspice log.

The day profile assumes 96 beacons/day, 120 ms airtime each, 30 ms MCU awake
per beacon and a 5 ms receive window after each beacon. These timings are
configurable planning assumptions, not a measured packet airtime or firmware
trace. The estimate adds MCU and IMU current in TX/RX periods, counts the
IMU low-power load through the day, and treats all other time as sleep. It does
not add battery self-discharge, regulator losses, antenna/front-end losses,
passive RFID loading, temperature derating, retransmissions or component
leakage beyond the configured radio sleep allowance.

The ngspice deck is a representative single TX pulse through a battery
equivalent, source resistance and bypass capacitor. It checks a transient
voltage dip; it is not a 24-hour transient run and does not independently
validate the charge integration in `energy_model.py`.
