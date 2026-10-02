# RIOSE MVP 2 — Digital twin report

**Gate: NOT_READY_FOR_PHYSICAL_PROTOTYPE**

Este relatório descreve um fluxo digital e SIMULATED. Nenhum hardware físico, laboratório ou medição foi usado. READY significaria apenas plausibilidade digital para justificar a fabricação do primeiro protótipo.

## Execução

- Spec SHA-256: `60e0f22cef0930fb29ac577df8a14ba96cf1e05b582d936c8bb9b5c1b98b3d51`
- Plataforma: `Linux-6.6.87.2-microsoft-standard-WSL2-x86_64-with-glibc2.39`
- Parâmetros por status: `{"ASSUMED": 77, "DATASHEET": 14, "SIMULATED": 3}`
- GPU: `{"CUDA_AVAILABLE": false, "GPU_AVAILABLE": false, "GPU_TYPE": "NONE_DETECTED", "SIONNA_AVAILABLE": false, "experiment": "OPTIONAL_GPU_EXPERIMENT", "result_status": "ENVIRONMENT_CAPABILITY_ONLY", "status": "SKIPPED_OPTIONAL"}`

## Estágios

| Estágio | Status | Evidência/limitação |
|---|---|---|
| synthetic_motion | COMPLETED |  |
| gpu_optional | SKIPPED_OPTIONAL | Sionna RT is optional; no GPU scenario blocks the digital twin core |
| mvp1_c_tests | PASSED |  |
| zephyr_firmware | PASSED | Built target firmware for nucleo_l031k6 |
| renode_firmware | PASSED | Renode platform smoke and Zephyr ELF execution completed |
| host_trace_export | PASSED |  |
| firmware_scenarios | COMPLETED | C FSM traces exported for all four requested profiles |
| long_duration_1_7_30_days | COMPLETED | 12 deterministic FSM long runs completed |
| adversarial_fault_injection | PARTIAL | Host C models cover transient I2C/SPI/TX timeout recovery; persistent pin and analog power faults require Renode or electrical models |
| mechanical | FAILED | battery envelope exceeds enclosure cavity; antenna_keepout envelope exceeds enclosure cavity; antenna keepout exceeds PCB envelope; unexpected envelope overlap: pcb / battery |
| antenna | PARTIAL_OR_BLOCKED | ANTENNA_FREE_SPACE: ADAPTER_NOT_CONFIGURED (Bindings detected, but RIOSE_OPENEMS_ADAPTER is not configured); ANTENNA_WITH_PCB: ADAPTER_NOT_CONFIGURED (Bindings detected, but RIOSE_OPENEMS_ADAPTER is not configured); ANTENNA_WITH_BATTERY: ADAPTER_NOT_CONFIGURED (Bindings detected, but RIOSE_OPENEMS_ADAPTER is not configured); ANTENNA_WITH_ENCLOSURE: ADAPTER_NOT_CONFIGURED (Bindings detected, but RIOSE_OPENEMS_ADAPTER is not configured); ANTENNA_NEAR_ANIMAL_APPROXIMATION: ADAPTER_NOT_CONFIGURED (Bindings detected, but RIOSE_OPENEMS_ADAPTER is not configured) |
| power | COMPLETED | Four scenario rail simulations completed |
| four_power_scenarios | COMPLETED | NORMAL/ACTIVE/ALERT/WORST_REASONABLE_CASE were converted from firmware traces and analyzed |
| trace_schedule | PASSED |  |

## Gate e bloqueadores

- adversarial_fault_injection: PARTIAL
- antenna: PARTIAL_OR_BLOCKED
- mechanical: FAILED
- mechanical: envelope_fit

## Respostas técnicas

1. Estabilidade do firmware: long runs C host `COMPLETED`; Zephyr `PASSED`.
2. Coerência dos periféricos virtuais: Renode `PASSED`; Renode platform smoke and Zephyr ELF execution completed.
3. Energia digital estimada na janela observada: `0.514252 µAh` pela integração SIMULATED de correntes ASSUMED/trace; ngspice: EXECUTED.
4. Estabilidade do rail: ngspice `EXECUTED`; sem medição física ou resultado de rail quando não executado.
5. Evento com maior carga integrada: `TX` / `sx1262` (0.375 µAh) na janela simulada.
6. A antena cabe: análise geométrica `FAILED`; battery envelope exceeds enclosure cavity; antenna_keepout envelope exceeds enclosure cavity; antenna keepout exceeds PCB envelope; unexpected envelope overlap: pcb / battery.
7. Frequência de ressonância/S11: openEMS `PARTIAL_OR_BLOCKED`; métricas permanecem nulas sem adaptador configurado e simulação concluída.
8. Degradação por PCB/bateria/carcaça/animal: 5 cenários listados; resultados exigem openEMS; aproximação animal é experimental.
9. Encaixe físico digital: `BLOCKED`; CadQuery disponível `True`.
10. Falhas encontradas: 12 entradas; falhas de host cobertas `one_shot_i2c_failure_recovery, one_shot_spi_failure_recovery, late_tx_done_timeout_recovery`; pendentes `sx1262_busy_stuck, irq_missing, crc_corruption, battery_voltage_drop, high_esr, regulator_instability, watchdog_reset, unexpected_reboot`.
11. Hipóteses a revisar: parâmetros ASSUMED e limites provisórios em hardware/spec.yaml; dimensões, antena e encaixe aguardam aprovação.
12. Parâmetros por status: `{"ASSUMED": 77, "DATASHEET": 14, "SIMULATED": 3}`; provenance completa na spec.
13. Sem hardware real não são validados consumo, brownout, potência RF, sintonia, materiais ou comportamento animal.
14. Este gate não é validação comercial, clínica ou de campo.

## Integridade da evidência

Nenhum campo MEASURED é permitido na spec do MVP2. Capacidades GPU são metadados de ambiente e o experimento Sionna é opcional.
