# RF capability matrix

Every status below distinguishes code or package capability from the path actually configured and executed by this campaign. Evidence is SIMULATED throughout.

| Feature | Analytic FREQUENCIA `rf.channel` | Sionna RT 2.2.0 via FREQUENCIA `rf.sionna_backend` | Actually configured here | Testable now | Limitation |
|---|---|---|---|---|---|
| LOS | Always includes direct free-space path | `PathSolver(los=...)`; LOS inferred from a valid path with no interactions | Yes, LOS control and direct LOS sweeps | Yes | Analytic LOS cannot be blocked |
| NLOS | No occlusion model | Direct-path search can be disabled; mesh geometry blocks rays; status derives from path interactions | Blocked-wall case, after geometric path-intersection check | Yes | Diffraction is disabled; no arbitrary NLOS loss |
| Reflection | One flat-ground specular image path with fixed coefficient -0.35 | Specular reflections controlled by flag and depth | Ground reflection enabled/disabled | Yes | Analytic coefficient is uncalibrated; Sionna ground is a material proxy |
| Diffraction | No | Library may support it; wrapper explicitly passes `diffraction=False` | No | No through current wrapper | Do not infer from package capability |
| Scattering | No | No diffuse reflection in wrapper (`diffuse_reflection=False`) | No | No through current wrapper | Not configured |
| Multipath | Exactly LOS plus one ground-reflection component | Enumerated valid paths and path interactions | Yes | Yes | No stochastic fading; bounded depth/path limits |
| Orientation | Scalar, ignored | Isotropic 1x1 arrays; wrapper exposes no pose/orientation | No | No | Cannot test tag yaw/pitch/roll effect |
| Height | 3D endpoint coordinates affect distance/image-path geometry | 3D device coordinates affect rays and terrain intersection | Yes | Yes | Assumed heights, no measured ear-tag placement |
| Terrain | None | Optional triangle mesh, path intersections/reflections | Flat and synthetic relief meshes | Yes | Relief is procedural, not surveyed |
| Vegetation proxy | None | No vegetation mesh/material in the active reference assets | No | No | Trees are inventory metadata only |
| Obstacles | None | Optional obstacle PLY mesh | One vertical wall; separate shed mesh in reference fixture | Yes | Shape and placement are synthetic proxies |
| Materials | Fixed scalar reflection coefficient only | Ground `RadioMaterial`; obstacle uses concrete proxy | Ground/custom material and wall proxy | Yes | Not measured or calibrated at 915 MHz |
| CIR | Two discrete analytic paths; no standardized channel impulse response artifact | Exported complex baseband path coefficients and absolute delays | Yes | Yes | No receiver pulse/demodulation response |
| CFR | Analytic narrow frequency sample grid | CFR generated over explicit offsets | Yes | Yes | No calibrated front-end transfer function |
| Delay | Geometric path delays; record reports earliest component | Per-path absolute delay in seconds | Yes | Yes | No clock/detector timestamp error |
| RSSI / path loss | Received power from coherent scalar sum; no receiver implementation | TX power times channel coefficient squared; coherent and path-sum power both preserved | Yes | Yes | Simulated received power is not measured RSSI |
| SNR | Not directly modeled | No noise/demodulator in propagation output | Derived only using declared engineering noise assumptions | Limited | Not a LoRa sensitivity or packet reception result |
| Seed | Not consumed by deterministic `simulate_link` | Forwarded to path solver; path solver is deterministic | Yes, Sionna seed recorded | Yes | Seed changes do not imply random channel variation |
| Requested radio parameters | Direct function arguments | Scenario/config fields consumed by wrapper | Yes in this direct API campaign | Yes | RIOSE's analytic request adapter does not forward request parameters; it runs a fixed smoke |
| NO_PATH | Never emitted | Null powers and CFR when no valid paths | Counted as a distinct state | Yes | Does not mean transmitter was off or simulator failed |

## Source evidence

- FREQUENCIA `rf/channel.py`: `simulate_link` computes free-space direct path and one flat-ground image path; fixed default reflection coefficient `-0.35`; no obstacles, shadowing, antenna pattern or randomness.
- FREQUENCIA `rf/sionna_backend.py`: arrays are `pattern="iso"`, polarization `"V"`; path solver explicitly sets `diffuse_reflection=False`, `refraction=False`, and `diffraction=False`; it exports path/CIR/CFR and preserves `NO_PATH` as null power.
- RIOSE `src/riose/simulation_lab/runner.py`: analytic request values are recorded `REQUEST_SPECIFIC_PARAMETERS_UNSUPPORTED`; the engine runs its built-in smoke.
- RIOSE `src/riose/simulation_lab/farm_rf.py`: FARM Sionna requests configure position/radio/seed/solver flags but inherit a pinned synthetic scene config and do not expose arbitrary antenna orientation or custom obstacle meshes.

## Agent execution

Required multi-agent reviews were attempted for architecture, Sionna, analytic/red-team. All three launches failed before execution because the account rejected the repository-default model (`gpt-5.3-codex` / `gpt-5.4-mini`) as unsupported. Sequential independent source audit was performed; independent red-team is recorded as not delegated.
