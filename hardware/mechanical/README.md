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

STEP/STL export uses the optional CadQuery runtime and runs without a GUI:

```sh
uv sync --extra dev
uv pip install --python .venv/bin/python -r requirements-cad.txt
uv run python -m hardware.mechanical.model \
  --spec hardware/mechanical/tests/fixtures/fitting_spec.yaml \
  --output /tmp/ear_tag.geometry.json \
  --step /tmp/ear_tag.step \
  --stl /tmp/ear_tag.stl
```

The fitting fixture is only an export smoke example, not RIOSE design evidence.
The current `hardware/spec.yaml` geometry has fit blockers and correctly refuses
STEP/STL export until the candidate dimensions are revised.

Numeric parameters can be overridden for controlled simulations with repeatable
`--set dotted.path=value` arguments. For example:

```sh
uv run python -m hardware.mechanical.model \
  --set mechanical.enclosure.width_mm=39 \
  --set mechanical.minimum_clearance_mm=0.75
```

Overrides retain the original unit and are marked `SIMULATED` with their CLI
source in the report. Every STEP/STL has a `.provenance.json` sidecar. CAD
export is refused when the report contains a clash or fit blocker. The CLI
still writes the JSON report for diagnosis, then exits nonzero for blocked fit.
Output paths are checked before writing so report, CAD, provenance, and source
specification files cannot overwrite one another.

The report contains component bounding boxes, cavity fit checks, pairwise
bounding-box clearances, estimated volume/mass by part and center of mass,
mass by modeled material class, along with each source/status. Because physical
materials have not been selected, those class densities remain explicit
assumptions. Body and parts
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
* `mechanical.minimum_clearance_mm`;
* `mechanical.components.{mcu,radio,imu}.{width_mm,height_mm,thickness_mm}`;
* optional `materials.{enclosure,pcb,battery,component}_density_g_cm3`.

Each value must use the spec record `{value, unit, source, status}`. Lengths
accept `mm`, `cm`, `m`, or `in`. Missing material densities use explicit
`ASSUMED` generic fallbacks with warnings; missing geometry is an error.

JSON fit and mass analysis remains available without CadQuery, but STEP/STL
export requires it; install `requirements-cad.txt` before requesting exports. The
enclosure is modeled as a closed hollow shell with a through mounting hole.
Blocked geometry exits 1, invalid spec or missing CAD runtime exits 2. YAML
input requires PyYAML. Geometry and mass are simulation/assumption evidence;
neither CAD export nor a passing envelope analysis is physical validation or
approval for fabrication.
