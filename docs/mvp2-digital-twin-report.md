# RIOSE MVP 2 — Digital twin report

**Gate: NOT_READY_FOR_PHYSICAL_PROTOTYPE**

Este relatório descreve um fluxo digital e SIMULATED. Nenhum hardware físico, laboratório ou medição foi usado. READY significaria apenas plausibilidade digital para justificar a fabricação do primeiro protótipo.

## Execução

- Spec SHA-256: `411580b196dada6c5125df22cdf149e46c5d05cc1fa2feea092e7203f8e48b81`
- Plataforma: `Linux-6.6.87.2-microsoft-standard-WSL2-x86_64-with-glibc2.39`
- Parâmetros por status: `{"ASSUMED": 81, "DATASHEET": 18, "SIMULATED": 3}`
- GPU: `{"CUDA_AVAILABLE": false, "DRJIT_CUDA_AVAILABLE": false, "GPU_AVAILABLE": false, "GPU_TYPE": "NONE_DETECTED", "MITSUBA_VARIANT": null, "SIONNA_AVAILABLE": false, "experiment": "OPTIONAL_GPU_EXPERIMENT", "result_status": "ENVIRONMENT_CAPABILITY_ONLY", "status": "SKIPPED_OPTIONAL"}`

## Estágios

| Estágio | Status | Evidência/limitação |
|---|---|---|
| synthetic_motion | COMPLETED |  |
| lis2dw12_datasets | PARTIAL | All five RESD profiles converted and firmware read the sensor, but distinct STATIC/WALK values were not verified (raw Z observations: {'STATIC': 0, 'WALK': 0}) |
| gpu_optional | SKIPPED_OPTIONAL | Sionna RT is optional; no GPU scenario blocks the digital twin core |
| mvp1_c_tests | PASSED |  |
| zephyr_firmware | PASSED | Built target firmware for nucleo_l031k6 |
| renode_firmware | PASSED | Renode firmware sleep/wake cycle passed; STATIC/WALK RESD were loaded and the firmware read the sensor, but raw dataset-value propagation remains unverified |
| host_trace_export | PASSED |  |
| firmware_scenarios | COMPLETED | C FSM traces exported for all four requested profiles |
| long_duration_1_7_30_days | COMPLETED | 12 deterministic FSM long runs completed |
| timer_and_sequence_rollover | PASSED | Counter rollover exercised from near uint32 limits |
| adversarial_fault_injection | COMPLETED | Electrical outcomes require a fresh hash-validated ngspice waveform to cross the sourced assumed brownout threshold, recover above it, and produce a post-reinitialization CRC-valid beacon. Synthetic reset probes do not claim watchdog expiration, CPU lockup, or independent reset-cause observation. |
| mechanical | COMPLETED | Bounding-box fit estimate completed |
| antenna | PARTIAL_OR_BLOCKED | ANTENNA_FREE_SPACE: FAILED (mesh refinement did not meet declared numerical convergence criteria); ANTENNA_WITH_BATTERY: FAILED (openEMS candidate simulation failed closed: RuntimeError: openEMS did not reach the -40 dB field-energy criterion before its timestep limit; log=/tmp/riose-mvp2-final-main/antenna/ANTENNA_WITH_BATTERY/mesh_4mm/solver.log; tail: RunFDTD: Warning: Max. number of timesteps was reached before the end-criteria of -40dB was reached...  	You may want to choose a higher number of max. timesteps...  Time for 160000 iterations with 63168.00 cells : 176.32 sec Speed: 57.32 MCells/s ); ANTENNA_NEAR_ANIMAL_APPROXIMATION: FAILED (mesh refinement did not meet declared numerical convergence criteria) |
| power | COMPLETED | Four scenario rail simulations completed |
| four_power_scenarios | COMPLETED | NORMAL/ACTIVE/ALERT/WORST_REASONABLE_CASE were converted from firmware traces and analyzed |
| trace_schedule | PASSED |  |

## Gate e bloqueadores

- antenna: PARTIAL_OR_BLOCKED
- lis2dw12_datasets: PARTIAL

## Respostas técnicas

1. Estabilidade do firmware: long runs C host `COMPLETED`; Zephyr `PASSED`.
2. Coerência dos periféricos virtuais: Renode `PASSED`; Renode firmware sleep/wake cycle passed; STATIC/WALK RESD were loaded and the firmware read the sensor, but raw dataset-value propagation remains unverified.
3. Energia digital estimada na janela observada: `0.878847 µAh` pela integração SIMULATED de correntes ASSUMED/trace; ngspice: PASS.
4. Estabilidade do rail: ngspice `PASS`; sem medição física ou resultado de rail quando não executado.
5. Evento com maior carga integrada: `TX` / `sx1262` (0.375 µAh) na janela simulada.
6. O envelope mecânico estimado cabe: análise de caixas delimitadoras `COMPLETED`; sem conflito de envelope reportado.
7. Frequência de ressonância/S11: openEMS `PARTIAL_OR_BLOCKED`; 2/5 cenários passaram a comparação numérica de malha; resultados simulados não validam desempenho físico.
8. Degradação por PCB/bateria/carcaça/animal: 5 cenários listados; resultados exigem openEMS; aproximação animal é experimental.
9. Encaixe geométrico estimado: `PASS`; CadQuery disponível `True`. O resultado não valida montagem física.
10. Faults: 10 cenários; 8 RECOVERED, 2 OBSERVED, 0 BLOCKED, 0 FAILED; CSV estruturado `fault_scenarios.csv`.
11. Hipóteses a revisar: parâmetros ASSUMED e limites provisórios em hardware/spec.yaml; dimensões, antena e encaixe aguardam aprovação.
12. Parâmetros por status: `{"ASSUMED": 81, "DATASHEET": 18, "SIMULATED": 3}`; provenance completa na spec.
13. Sem hardware real não são validados consumo, brownout, potência RF, sintonia, materiais ou comportamento animal.
14. Este gate não é validação comercial, clínica ou de campo.

## Integridade da evidência

Nenhum campo MEASURED é permitido na spec do MVP2. Capacidades GPU são metadados de ambiente e o experimento Sionna é opcional.

### Feedback elétrico para o modelo do firmware

Os perfis ngspice alimentam amostras de rail validadas pelo hash ao modelo host do firmware. A classificação de brownout usa o supervisor SIMULATED; o limite de 2.7 V e os amplitudes dos faults são ASSUMED, não constituem validação física.

| Cenário | Rail mínimo (V) | Cruzamento (V) | Retorno (V) | Resultado | Simulation ID |
|---|---:|---:|---:|---|---|
| voltage_drop | 2.28097778 | 2.63140079 | 2.79784043 | RECOVERED | 26ff8acb18ab6575095e809df99e5c571aeb2c75016fdd563854eab5a0fdc78d |
| high_esr | 1.53880606 | 2.55401301 | 2.83763254 | RECOVERED | 883ff32af47558b2944e6f194e84d078af6cc856f6323f924dc55c0b9e2d65ad |
| regulator_instability | 2.68102219 | 2.69621307 | 2.70476922 | RECOVERED | 071056e57c2bb4c28e576a1fd2cd845229cf587e926bf8215aad9436df75efd5 |

Watchdog/reset classification rows are synthetic reinitialization probes; they do not demonstrate watchdog expiry, CPU lockup, independent reset cause, or physical MCU reset. Fault status counts above derive from structured per-scenario evidence, not from the global prototype gate failure count.
