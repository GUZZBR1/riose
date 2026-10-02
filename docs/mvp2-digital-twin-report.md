# RIOSE MVP 2 — Digital twin report

**Gate: NOT_READY_FOR_PHYSICAL_PROTOTYPE**

Este relatório descreve um fluxo digital e SIMULATED. Nenhum hardware físico, laboratório ou medição foi usado. READY significaria apenas plausibilidade digital para justificar a fabricação do primeiro protótipo.

## Execução

- Spec SHA-256: `d5af1cc24253f70e6a337551038096504267dc1311178b53ef1f585b6340aef8`
- Plataforma: `Linux-6.6.87.2-microsoft-standard-WSL2-x86_64-with-glibc2.39`
- Parâmetros por status: `{"ASSUMED": 78, "DATASHEET": 18, "SIMULATED": 3}`
- GPU: `{"CUDA_AVAILABLE": false, "GPU_AVAILABLE": true, "GPU_TYPE": "NVIDIA GeForce GTX 1060 6GB", "SIONNA_AVAILABLE": false, "experiment": "OPTIONAL_GPU_EXPERIMENT", "result_status": "ENVIRONMENT_CAPABILITY_ONLY", "status": "SKIPPED_OPTIONAL"}`

## Estágios

| Estágio | Status | Evidência/limitação |
|---|---|---|
| synthetic_motion | COMPLETED |  |
| gpu_optional | SKIPPED_OPTIONAL | Sionna RT is optional; no GPU scenario blocks the digital twin core |
| mvp1_c_tests | PASSED |  |
| zephyr_firmware | NOT_AVAILABLE | west/Zephyr workspace is not configured; set ZEPHYR_BASE and install the pinned SDK/workspace |
| renode_firmware | NOT_AVAILABLE | Renode and renode-test are required for the MCU/bus twin |
| host_trace_export | PASSED |  |
| firmware_scenarios | COMPLETED | C FSM traces exported for all four requested profiles |
| long_duration_1_7_30_days | COMPLETED | 12 deterministic FSM long runs completed |
| timer_and_sequence_rollover | PASSED | Counter rollover exercised from near uint32 limits |
| adversarial_fault_injection | COMPLETED | Electrical outcomes require a fresh hash-validated ngspice waveform to cross the sourced assumed brownout threshold, recover above it, and produce a post-reinitialization CRC-valid beacon. Synthetic reset probes do not claim watchdog expiration, CPU lockup, or independent reset-cause observation. |
| mechanical | NOT_AVAILABLE | Bounding-box fit estimate completed; CadQuery STEP export unavailable |
| antenna | NOT_AVAILABLE | ANTENNA_FREE_SPACE: NOT_AVAILABLE (openEMS/CSXCAD bindings are absent; no RF metrics were generated); ANTENNA_WITH_PCB: NOT_AVAILABLE (openEMS/CSXCAD bindings are absent; no RF metrics were generated); ANTENNA_WITH_BATTERY: NOT_AVAILABLE (openEMS/CSXCAD bindings are absent; no RF metrics were generated); ANTENNA_WITH_ENCLOSURE: NOT_AVAILABLE (openEMS/CSXCAD bindings are absent; no RF metrics were generated); ANTENNA_NEAR_ANIMAL_APPROXIMATION: NOT_AVAILABLE (openEMS/CSXCAD bindings are absent; no RF metrics were generated) |
| power | COMPLETED | Four scenario rail simulations completed |
| four_power_scenarios | COMPLETED | NORMAL/ACTIVE/ALERT/WORST_REASONABLE_CASE were converted from firmware traces and analyzed |
| trace_schedule | PASSED |  |

## Gate e bloqueadores

- antenna: NOT_AVAILABLE
- mechanical: NOT_AVAILABLE
- renode_firmware: NOT_AVAILABLE
- zephyr_firmware: NOT_AVAILABLE

## Respostas técnicas

1. Estabilidade do firmware: long runs C host `COMPLETED`; Zephyr `NOT_AVAILABLE`.
2. Coerência dos periféricos virtuais: Renode `NOT_AVAILABLE`; Renode and renode-test are required for the MCU/bus twin.
3. Energia digital estimada na janela observada: `0.878847 µAh` pela integração SIMULATED de correntes ASSUMED/trace; ngspice: PASS.
4. Estabilidade do rail: ngspice `PASS`; sem medição física ou resultado de rail quando não executado.
5. Evento com maior carga integrada: `TX` / `sx1262` (0.375 µAh) na janela simulada.
6. O envelope mecânico estimado cabe: análise de caixas delimitadoras `NOT_AVAILABLE`; sem conflito de envelope reportado.
7. Frequência de ressonância/S11: openEMS `NOT_AVAILABLE`; 0/5 cenários passaram a comparação numérica de malha; resultados simulados não validam desempenho físico.
8. Degradação por PCB/bateria/carcaça/animal: 5 cenários listados; resultados exigem openEMS; aproximação animal é experimental.
9. Encaixe geométrico estimado: `PASS`; CadQuery disponível `False`. O resultado não valida montagem física.
10. Faults: 10 cenários; 8 RECOVERED, 2 OBSERVED, 0 BLOCKED, 0 FAILED; CSV estruturado `fault_scenarios.csv`.
11. Hipóteses a revisar: parâmetros ASSUMED e limites provisórios em hardware/spec.yaml; dimensões, antena e encaixe aguardam aprovação.
12. Parâmetros por status: `{"ASSUMED": 78, "DATASHEET": 18, "SIMULATED": 3}`; provenance completa na spec.
13. Sem hardware real não são validados consumo, brownout, potência RF, sintonia, materiais ou comportamento animal.
14. Este gate não é validação comercial, clínica ou de campo.

## Integridade da evidência

Nenhum campo MEASURED é permitido na spec do MVP2. Capacidades GPU são metadados de ambiente e o experimento Sionna é opcional.

### Feedback elétrico para o modelo do firmware

Os perfis ngspice alimentam amostras de rail validadas pelo hash ao modelo host do firmware. A classificação de brownout usa o supervisor SIMULATED; o limite de 2.7 V e os amplitudes dos faults são ASSUMED, não constituem validação física.

| Cenário | Rail mínimo (V) | Cruzamento (V) | Retorno (V) | Resultado | Simulation ID |
|---|---:|---:|---:|---|---|
| voltage_drop | 2.28080341 | 2.49923423 | 2.84172959 | RECOVERED | d18a6d5f88dfdb83db67e9d5bcaf39ef8209303e1bae19559695cc6a93ae75b8 |
| high_esr | 1.53880539 | 2.55401301 | 2.91683991 | RECOVERED | 94cdf07e7045b753b0b3393e688e2e0cacbf8321cae0ceab57fdb2a412bf6733 |
| regulator_instability | 2.68102219 | 2.69621307 | 2.70476922 | RECOVERED | 7de877e8af9286d38d0515e456a04dcfb9cb902b64c2780a28782f6ebbbb3955 |

Watchdog/reset classification rows are synthetic reinitialization probes; they do not demonstrate watchdog expiry, CPU lockup, independent reset cause, or physical MCU reset. Fault status counts above derive from structured per-scenario evidence, not from the global prototype gate failure count.
