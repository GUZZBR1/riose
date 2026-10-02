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

The default profile now records a Tadiran TLL-5902 capacity rating (1,100 mAh)
and a TPS62840 regulator candidate. The calculated days are an arithmetic
estimate from configured loads, not a demonstrated battery lifetime. Outputs
are `summary.json`,
`energy_24h.csv`, a generated ngspice pulse deck and the ngspice log.

The normal day profile assumes 96 beacons/day (15-minute interval), 120 ms
airtime each, 30 ms MCU awake per beacon and a 100 ms receive window after
each beacon. These timings are configurable assumptions, not measured airtime
or a firmware power trace. The charge model converts rail current to battery
input using the configured nominal voltage, regulator efficiency assumption,
and quiescent current; it also counts the IMU load through the day. It does not
include battery self-discharge, RF front-end losses, passive RFID loading,
temperature/age derating, retransmissions or unmodeled board leakage.

For the selected-cell/regulator transient sensitivity model, run
[`candidate/run_sweep.py`](candidate/README.md). It sweeps voltage, ESR and
output capacitor in ngspice. Its regulator is an averaged idealization, and
the results do not validate a physical brownout. The older generated deck here
is a representative single pulse only; it does not independently validate the
daily charge integration.
