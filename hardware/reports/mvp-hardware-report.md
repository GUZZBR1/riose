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
| `uv run pytest -q hardware/spice/test_energy_model.py` | 3 passaram |
| Zephyr v4.2.1 `native_sim/native/64` | build e execução passaram; um ciclo produziu 1 pacote de 24 bytes com CRC válido e deixou o rádio dormindo |
| ngspice 42 | netlist executado; mínimo de 3,164086 V para fonte/célula equivalente de 3,3 V, 3 Ω e capacitor de 47 µF |

Os testes de hardware são simulações de software: a API SPI/I2C no harness e os modelos C não representam temporização, integridade de sinal ou tolerâncias elétricas. A execução Zephyr usa kernel/timer Zephyr, mas chama os modelos C determinísticos diretamente; não é uma simulação de barramento analógico.

## Resultados quantitativos

O harness avançou cenários acelerados até 24 horas virtuais:

| Perfil | Transmissões | Leitura |
|---|---:|---|
| Política nominal configurada a cada 60 s | 1.440/dia | Base usada no cálculo de energia nominal |
| Perfil misto de movimento, com IRQ INT1 desabilitada | 7.341/dia | Transmissões com origem em deadline; 1.680 estacionário, 360 caminhada, 990 corrida, 2.151 anormal e 2.160 estacionário tardio; 0 falhas no cenário |
| Imóvel por 3 h, abaixo do limiar de alerta | 180 | Mantém beacon de 60 s; nenhum alerta prematuro |
| Imóvel por 24 h | 14.640/dia | Limiar configurado de 4 h; alerta a cada 5 s após o limiar |

As contagens demonstram que a máquina de estados e as cadências configuradas se comportam como esperado no modelo. O volume de 14.640 transmissões/dia no alerta estacionário mostra que essa política pode ser energeticamente cara; o limiar e o intervalo precisam ser definidos com veterinários/produtores e medidos no hardware.

### Energia

Para o perfil nominal (1.440 transmissões/dia; TX configurado em 120 ms; MCU ativa por 30 ms e janela RX de 100 ms por beacon), o modelo retorna:

- **2,416305 mAh/tag/dia**;
- **100,679 µA de corrente média configurada**;
- **45,3048 mA de pico calculado**;
- autonomia **não calculada**, pois a capacidade da bateria não está selecionada.

Aplicando as mesmas correntes e durações configuradas às contagens do harness, resultam 12,146009 mAh/dia para o perfil misto e 24,180767 mAh/dia para o perfil estacionário com alerta. São extrapolações de tráfego a partir do mesmo perfil de componentes, não medições.

Os valores combinam dados de datasheet e hipóteses editáveis. O consumo TX de 45 mA é um proxy conservador referenciado ao valor da Semtech em +14 dBm; o firmware está configurado em +10 dBm e o relatório não afirma que 45 mA seja a corrente real nesse nível. Corrente de sleep da placa, IMU, tempo ativo, airtime, recepção e bateria requerem caracterização da placa final. O resultado ngspice também só se refere à rede equivalente configurada, não prova margem de brownout real. A HAL recebe tensão de bateria como valor estático de telemetria; não há ADC, supervisor de brownout ou teste de queda de energia implementado.

## Componentes avançados e bloqueios

- **Zephyr:** o caminho `native_sim/native/64` está compilado e executado. O adapter de uma placa física ainda precisa de overlay, pinagem, driver e build para uma placa alvo real.
- **Wokwi:** indisponível neste ambiente; não foi criado projeto Wokwi nem alegada simulação de MCU/periférico pelo Wokwi. Os modelos C cumprem o papel de harness local determinístico.
- **KiCad:** `kicad-cli` indisponível; não existe esquemático/PCB para ERC/DRC ou simulação SPICE de placa. O netlist ngspice usado é uma topologia equivalente mínima.
- **SX1262, IMU e RFID físicos:** sem dispositivo, antena, leitor, bateria ou instrumento de medida, não há validação de RF, consumo ou identificação no campo.
- **Autonomia:** não reportada como estimativa de produto. Um valor hipotético só seria resultado de divisão por capacidade explicitamente fornecida e ainda dependeria de validar correntes, derating e ciclo de vida da bateria.

## Hipóteses avaliadas

- **Promissora, restrita ao software:** a lógica de beacon adaptativo, packetização/CRC, troca por HAL, fluxo de energia configurável e integração de dois periféricos podem ser exercitados em máquina host e Zephyr `native_sim` sem uma placa.
- **Ainda sem evidência física:** compatibilidade da arquitetura com consumo de anos. A carga nominal calculada é pequena em valores absolutos, mas usa parâmetros ainda não medidos; perfil de alerta estacionário eleva o custo diário em cerca de 10 vezes comparado ao perfil nominal configurado.
- **Limitação revelada:** alerta a cada 5 s após quatro horas parado gera tráfego elevado (14.640 TX/dia no cenário contínuo). A política precisa evitar falsos positivos e controlar o consumo.
- **Não avaliada neste workstream:** propagação/localização RF, cobertura em fazenda, custo de infraestrutura, comportamento real de bovinos ou melhoria de erro por número de âncoras. Esses dados não podem ser inferidos dos testes de firmware.

## Próximo experimento físico recomendado

Montar um protótipo instrumentável com MCU de baixo consumo, módulo SX1262 apropriado à faixa/região e antena ajustada, LIS2DW12, regulador/proteção e suporte para bateria substituível. Conectar ST-Link e analisador de corrente ou source meter. Medir STOP, wake/leitura de IMU, TX com payload/modulação/potência documentados, janela RX e vazamento em sleep, incluindo temperatura. Capturar a linha de alimentação durante TX para verificar regulador, ESR, capacitância e reset. Em paralelo, testar leitor/transponder RFID passivo compatível com a identificação pretendida. Nenhum preço é estimado neste relatório: pesquisa de preço e seleção de componentes permanecem necessários.

As correntes nominais usadas como referência estão documentadas com fontes primárias no [relatório de energia](power-model.md); os valores de corrente de uma placa pronta devem ser substituídos por medições antes de alegar autonomia.
