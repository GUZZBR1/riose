# RIOSE mechanical digital model

Headless, parameter-driven first-pass envelope and fit analysis. Inputs come
from `hardware/spec.yaml`; the model does not inject production defaults when
required spec records are missing. A small fitting geometry exists only as an
isolated unit-test fixture.

Run from the repository root:

```sh
python3 -m hardware.mechanical.model \
  --spec hardware/spec.yaml \
  --output results/mvp2/mechanical/geometry.json
```

Optional STEP export uses CadQuery when installed:

```sh
python3 -m hardware.mechanical.model --step results/mvp2/mechanical/ear_tag.step
```

The report contains component bounding boxes, cavity fit checks, estimated
volume/mass and center of mass, along with each source/status. Body and parts
are simplified boxes; the battery is represented by a cylindrical mass estimate
and a rectangular fit envelope. Material density and component masses are
assumptions. The mounting-hole location and package layout are provisional.
The gate cannot become `READY_FOR_PHYSICAL_PROTOTYPE` here: dimensions, antenna
and fit remain subject to explicit review.

Required spec records are:

* `mechanical.enclosure.width_mm`, `height_mm`, `thickness_mm`,
  `wall_thickness_mm`, `mounting_hole_diameter_mm`;
* `mechanical.pcb.width_mm`, `height_mm`, `thickness_mm`;
* `mechanical.battery.diameter_mm`, `length_mm`;
* `mechanical.antenna.width_mm`, `height_mm`, `thickness_mm`, `keepout_mm`;
* `mechanical.components.{mcu,radio,imu}.{width_mm,height_mm,thickness_mm}`;
* optional `materials.{enclosure,pcb,battery,component}_density_g_cm3`.

Each value must use the spec record `{value, unit, source, status}`. Lengths
accept `mm`, `cm`, `m`, or `in`. Missing material densities use explicit
`ASSUMED` generic fallbacks with warnings; missing geometry is an error.

CadQuery is not installed in the current environment. JSON fit and mass
analysis remains available without it; STEP export requires the optional
CadQuery Python runtime. When available, `--step` and `--stl` export the same
assembly geometry in both formats. The enclosure is modeled as a closed hollow
shell with a through mounting hole. A completed analysis exits 0 even when it
finds fit blockers; callers should inspect `fit.fits` and `gate`. Invalid spec
or missing optional CAD runtime exits 2. YAML input requires PyYAML.
