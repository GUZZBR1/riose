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
| gpu_optional | SKIPPED_OPTIONAL |  |
| zephyr_firmware | NOT_AVAILABLE | Zephyr SDK/workspace is not configured; host C tests do not validate the Zephyr target |
| long_duration_1_7_30_days | NOT_AVAILABLE | Accelerated virtual-time execution for 1/7/30 days is not implemented in the available host harness |
| adversarial_fault_injection | NOT_AVAILABLE | Fault injection requires the Renode peripheral platform/backend, unavailable in this environment |
| four_power_scenarios | NOT_AVAILABLE | Only one host-harness trace is available; NORMAL/ACTIVE/ALERT/WORST_REASONABLE_CASE must run through the FSM before energy comparison |
| mvp1_c_tests | PASSED |  |
| renode_firmware | NOT_AVAILABLE | Renode and renode-test are required for the MCU/bus twin |
| host_trace_export | PASSED |  |
| mechanical | NOT_AVAILABLE | battery envelope exceeds enclosure cavity; antenna_keepout envelope exceeds enclosure cavity; antenna keepout exceeds PCB envelope; unexpected envelope overlap: pcb / battery; CadQuery STEP export unavailable |
| antenna | NOT_AVAILABLE | The animal-proximity case is an experimental material approximation, not tissue validation. |
| trace_schedule | PASSED |  |
| power | NOT_AVAILABLE | Assumed-current charge integration completed; ngspice rail simulation was not executed |

## Gate e bloqueadores

- adversarial_fault_injection: NOT_AVAILABLE
- antenna: NOT_AVAILABLE
- four_power_scenarios: NOT_AVAILABLE
- long_duration_1_7_30_days: NOT_AVAILABLE
- mechanical: NOT_AVAILABLE
- mechanical: envelope_fit
- power: NOT_AVAILABLE
- renode_firmware: NOT_AVAILABLE
- zephyr_firmware: NOT_AVAILABLE

## Respostas técnicas

1. Estabilidade do firmware: depende da execução Renode; testes C host são reportados separadamente.
2. Coerência dos periféricos virtuais: depende de Renode; comparar com os modelos C do MVP1.
3. Energia digital estimada na janela observada: `0.187059 µAh` pela integração SIMULATED de correntes ASSUMED/trace; ngspice: NOT_AVAILABLE.
4. Estabilidade do rail: sem resultado se ngspice não executar; nenhuma queda física é inferida.
5. Evento com maior carga integrada: `RX` / `sx1262` (0.127778 µAh) na janela simulada.
6. A antena cabe: envelope mecânico inicial ASSUMED; revisar saída CAD.
7. Frequência de ressonância/S11: somente solver openEMS; null quando indisponível.
8. Degradação por PCB/bateria/carcaça/animal: somente comparação openEMS; aproximação animal ASSUMED.
9. Encaixe físico digital: estimativa geométrica; envelope ainda não aprovado.
10. Falhas encontradas: ver failures.csv e status dos testes; estágio ausente não significa sucesso.
11. Hipóteses a revisar: todos os valores ASSUMED e limites do modelo listados na spec.
12. Parâmetros ASSUMED: consultar hardware/spec.yaml e provenance exportada.
13. Sem hardware real não são validados consumo, brownout, potência RF, sintonia, materiais ou comportamento animal.
14. Este gate não é validação comercial, clínica ou de campo.

## Integridade da evidência

Nenhum campo MEASURED é permitido na spec do MVP2. Capacidades GPU são metadados de ambiente e o experimento Sionna é opcional.
