# Relatório do MVP de hardware virtual

**Status geral: SIMULATED.** Nenhum resultado deste relatório é validação de campo ou medição elétrica de uma placa física. Este MVP implementa uma tag virtual com firmware C portátil, modelos de periféricos em C, um ciclo Zephyr `native_sim` e modelos configuráveis de consumo e queda de tensão.

## O que foi implementado

- Referência inicial de hardware: STM32L031K6 como MCU, SX1262 sub-GHz como rádio e LIS2DW12 como IMU. Identidade RFID animal passiva de 134,2 kHz é representada apenas como identificador externo; não há leitor RFID implementado. BLE e Wi-Fi ficam fora deste primeiro slice.
- Máquina de estados portátil em C, isolada por HAL: inicialização/autoteste, sleep, leitura de movimento, recepção, transmissão, alerta e recuperação de falha. A configuração controla cadência de beacon, alerta de imobilidade, limites de bateria e potência/cadência de TX.
- Protocolo binário de telemetria de 24 bytes com CRC16. A HAL preserva a possibilidade de trocar os drivers sem mudar a lógica de política da tag.
- Modelo C de comandos SPI do SX1262, incluindo configuração, FIFO, TX_DONE/timeout, janela RX limitada e sleep/standby. Modelo C do LIS2DW12 acessível por registradores I2C, perfis determinísticos de movimento e injeção de falhas.
- Harness de integração liga os callbacks do firmware aos modelos dos periféricos. Também há demo de ciclo da tag no host e um adaptador Zephyr.
- Perfil energético JSON com provenance/status por parâmetro e script de orçamento de carga em 24h. Um netlist ngspice opcional representa um pulso de transmissão com fonte resistiva e capacitor.
- Um template de topologia KiCad está documentado, mas não há esquemático nem PCB produzido ou validado.

## Validação executada

| Execução | Resultado |
|---|---|
| `make hardware-test` | 4/4 alvos CTest passaram: integração, ciclo host, smoke do SX1262 e modelo LIS2DW12 |
| CTest com AddressSanitizer + UndefinedBehaviorSanitizer | 4/4 passaram |
| `uv run pytest -q` | 45 passaram; uma advertência de depreciação do Starlette/httpx |
| `uv run pytest -q hardware/spice/test_energy_model.py` | 4 passaram |
| Zephyr v4.2.1 `native_sim/native/64` | build e execução passaram; um ciclo produziu 1 pacote de 24 bytes com CRC válido e deixou o rádio dormindo |
| ngspice 42 | 150/150 cenários do modelo candidato executaram; rail mínimo de 3,290939 V no caso nominal de 3,6 V |

Os testes de hardware são simulações de software: a API SPI/I2C no harness e os modelos C não representam temporização, integridade de sinal ou tolerâncias elétricas. A execução Zephyr usa kernel/timer Zephyr, mas chama os modelos C determinísticos diretamente; não é uma simulação de barramento analógico.

## Resultados quantitativos

O harness avançou cenários acelerados até 24 horas virtuais:

| Perfil | Transmissões | Leitura |
|---|---:|---|
| Política nominal, beacon de 15 min | 96/dia | 900 s entre beacons sem evento ativo |
| Perfil misto de movimento, com IRQ INT1 desabilitada | 128/dia | 36 estacionário, 24 caminhada, 32 corrida, 24 anormal, 12 estacionário tardio; 0 falhas |
| Imóvel por 3 h, abaixo do limiar de alerta | 12 | Beacon de 900 s; sem alerta antes do limite configurado |
| Imóvel por 24 h | 108 | Limiar assumido de 4 h; burst de alerta a cada 10 s limitado a 2 min |
| ACTIVE contínuo por 3 h | 14 | Burst de 60 s limitado a 2 min; depois volta ao heartbeat de 15 min |

As contagens demonstram apenas a máquina de estados e cadências configuradas no modelo. O limiar de imobilidade é uma hipótese e precisa de avaliação veterinária/produtiva; não é uma afirmação clínica.

### Energia

Para o perfil nominal (96 transmissões/dia; TX configurado em 120 ms; MCU ativa por 30 ms e janela RX de 100 ms por beacon), o modelo converte correntes do rail de 3,3 V para entrada de bateria com eficiência buck assumida de 85% e IQ de 60 nA do componente candidato. Retorna:

- **0,217436 mAh/tag/dia**;
- **9,060 µA de corrente média equivalente na célula**;
- **1.100 mAh de capacidade nominal** para a candidata Tadiran TLL-5902.

Não publicamos autonomia calculada por capacidade/carga: os estados de baixa
corrente, o perfil de eventos, a eficiência e o pulso real ainda não foram
medidos na montagem.

Aplicando o mesmo perfil energético às contagens do harness, resultam 0,274336 mAh/dia para o cenário misto (128 TX) e 0,238773 mAh/dia para o perfil estacionário com alerta (108 TX). São extrapolações da mesma corrente/duração por pacote, não medições. A atividade contínua foi exercitada por três horas e não foi extrapolada para 24 horas.

Os valores misturam dados de fabricante e hipóteses editáveis. O consumo TX de 45 mA é stress case Semtech em +14 dBm; firmware está configurado em +10 dBm e 45 mA não é atribuído a +10 dBm. A Tadiran TLL-5902 declara 3,6 V, 1,1 Ah sob teste até 2 V, corrente contínua recomendada de 50 mA e capacidade de pulso de 100 mA. Como o TPS62840 candidato é um buck ajustado para 3,3 V, essa capacidade nominal até 2 V não foi demonstrada como utilizável; existe risco de o rail sair da regulação bem antes. ESR, eficiência, capacitores, perfis de carga e limiar funcional continuam hipóteses. O modelo ngspice é médio, não inclui controle chaveado real e não comprova brownout. A HAL recebe a tensão da bateria como valor estático; não há ADC, supervisor ou teste físico de queda.

## Componentes avançados e bloqueios

- **Zephyr:** o caminho `native_sim/native/64` compila e executa o modelo de periféricos. O adapter físico espera BUSY baixo do SX1262 antes de SPI, mas ainda precisa de overlay/pinagem da placa e build para um alvo físico; esse adapter não é compilado pelo `native_sim`.
- **Wokwi:** indisponível neste ambiente; não foi criado projeto Wokwi nem alegada simulação de MCU/periférico pelo Wokwi. Os modelos C cumprem o papel de harness local determinístico.
- **KiCad:** `kicad-cli` indisponível; não existe esquemático/PCB para ERC/DRC ou simulação SPICE de placa. O netlist ngspice usado é uma topologia equivalente mínima.
- **SX1262, IMU e RFID físicos:** o ambiente não expõe dispositivo ou instrumento de medida. Não há validação de RF, consumo, tensão de rail, brownout, bateria ou identificação no campo. A coleta aguarda montagem/conexão física.
- **Autonomia:** não medida e não estimada como vida útil de produto. Temperatura, auto-descarga, envelhecimento, regulador, correntes da placa e perfil de eventos ainda requerem validação física.

## Hipóteses avaliadas

- **Promissora, restrita ao software:** a lógica de beacon adaptativo, packetização/CRC, troca por HAL, fluxo de energia configurável e integração de dois periféricos podem ser exercitados em máquina host e Zephyr `native_sim` sem uma placa.
- **Promissora para investigação física:** 96 TX/dia em normal e menos de 0,5 mAh/dia sob o perfil de corrente configurado. Cadência, airtime, janelas RX, correntes e eficiência continuam sem medição.
- **Limitação revelada:** bursts limitados podem reduzir resolução se o evento durar mais de dois minutos; validar com dados reais antes de escolher essa política.
- **Não avaliada neste workstream:** propagação/localização RF, cobertura em fazenda, custo de infraestrutura, comportamento real de bovinos ou melhoria de erro por número de âncoras. Esses dados não podem ser inferidos dos testes de firmware.

## Próximo experimento físico recomendado

Montar um protótipo instrumentável com MCU de baixo consumo, módulo SX1262/antena ajustada, LIS2DW12, buck TPS62840 ou equivalente, capacitores e célula TLL-5902 candidata. Medir STOP, wake/leitura de IMU, TX com potência/modulação documentadas, RX, vazamento em sleep e rail/pico de entrada durante TX, com bateria nova e descarregada em diferentes temperaturas. Conferir tamanho e massa no encapsulamento antes de fixar a célula. O protocolo e o analisador de capturas estão em [`../physical/README.md`](../physical/README.md). Nenhum preço foi pesquisado nesta etapa.

As correntes nominais usadas como referência estão documentadas com fontes primárias no [relatório de energia](power-model.md); os valores de corrente de uma placa pronta devem ser substituídos por medições antes de alegar autonomia.
