# Orçamento de energia da tag candidata

**Evidência: SIMULATED.** A política foi reduzida a 96 beacons/dia em condição
normal (um a cada 15 minutos). Bursts de atividade e alerta têm duração máxima
configurada de dois minutos por episódio. Isso é uma simulação de firmware e
um orçamento com correntes assumidas; não é uma medição da placa.

## Perfil normal

O perfil em [`power_profile.json`](../spice/power_profile.json) usa 96 TX/dia,
120 ms configurados de TX, 30 ms de MCU ativa e 100 ms de RX por beacon. Os
parâmetros elétricos somam correntes de datasheet e hipóteses, depois convertem
a carga do rail de 3,3 V em corrente de bateria usando 85% de eficiência
assumida e 60 nA típicos de IQ para o buck candidato.

| Métrica | Valor | Qualificação |
|---|---:|---|
| Carga simulada em 24 h | 0,217436 mAh/tag | Mistura de dados de fabricante e hipóteses |
| Corrente média equivalente da célula | 9,060 µA | Derivada do modelo |
| TX normais por dia | 96 | Política configurada, beacon de 15 min |
| Capacidade nominal da célula candidata | 1.100 mAh | Tadiran TLL-5902, ficha técnica a 1 mA até 2 V |
| Vida aritmética capacidade/carga | 5.059 dias (13,85 anos) | **Limite matemático do modelo, não autonomia prevista** |

O cálculo nominal fica abaixo do alvo de 0,5 mAh/dia. Aplicando a mesma carga
unitária aos resultados observados no harness: 108 TX/dia (perfil estacionário
com alerta) resultam em 0,238773 mAh/dia; 128 TX/dia (perfil misto) resultam
em 0,274336 mAh/dia. São extrapolações de contagem de pacotes sob as mesmas
hipóteses de duração e corrente; não incluem medidas fisiológicas nem ráfagas
reais no campo. O cenário de atividade contínua foi testado por três horas e
gerou 14 TX nesse intervalo; não extrapolamos esse recorte para 24 horas.

## Premissas que mais pesam

- MCU STM32L031 STOP: 0,35 µA típico; RUN calculado a partir de 76 µA/MHz ×
  4 MHz. Corrente da placa e periféricos não foi medida.
- IMU LIS2DW12: 0,8 µA configurado dentro do resumo `below 1 µA` da ST; modo e
  taxa finais ainda não estão definidos.
- SX1262: 4,6 mA em RX segundo Semtech. O cálculo de TX usa 45 mA em **+14 dBm**
  como stress case publicado, enquanto o firmware está configurado em +10 dBm.
  Não atribuímos 45 mA à potência de +10 dBm.
- Buck TI TPS62840 candidato: IQ de 60 nA típico de datasheet; eficiência de
  85% é ASSUMED no orçamento de carga. A ficha do CI não valida a placa ou a
  eficiência real em todos os regimes.
- Janela RX de 100 ms depois de cada TX é o timeout atual do firmware, não um
  calendário de recepção LoRaWAN validado.
- Não incluímos auto-descarga, envelhecimento, temperatura, eficiência medida,
  perdas de antena, armazenamento, nem consumo do leitor de RFID.

## Célula e rail

A candidata de engenharia é a Tadiran TLL-5902 Li-SOCl₂ primária de 1/2 AA,
3,6 V nominal e 1,1 Ah. Sua ficha declara até 50 mA de corrente contínua
recomendada e capacidade máxima de pulso de 100 mA. A candidata não está
montada nem escolhida para o encapsulamento final do brinco. O buck TPS62840
reduz a entrada a 3,3 V; o perfil de carga inclui uma eficiência estimada.

O modelo ngspice específico de rail varre tensão terminal, ESR assumida e
capacitor de saída. Ele é executado e documentado em
[`spice/candidate/README.md`](../spice/candidate/README.md). O caso nominal
3,6 V simulou mínimo de rail de 3,2909 V e pico de célula de 48,858 mA. O pior
ponto de tensão incluído (2,0 V, diagnóstico no endpoint da capacidade da
ficha sob 1 mA) caiu a 1,7151 V e cruzou o limite de projeto assumido de 2,7 V.
Esse limite de 2,7 V é uma linha de comparação de engenharia, não o limiar de
brownout configurado do MCU. O modelo não simula o controlador chaveado real,
e não prova funcionamento ou falha de uma placa física.

## Próxima medida

Na bancada, medir corrente de repouso da placa, forma de onda de TX na potência
regional escolhida, recepção, eficiência do regulador e tensão do rail durante
TX com TLL-5902 nova e descarregada, incluindo temperatura. Trocar no perfil
as correntes, ESR, capacitância efetiva, eficiência e temporizações assumidas.
Só então tratar autonomia como estimativa de engenharia; a divisão atual de
1.100 mAh pela carga simulada não é previsão de vida útil.

Fontes de fabricante: [Tadiran TLL-5902](https://tadiranbat.com/wp-content/uploads/2022/03/tll-5902.pdf),
[TI TPS62840](https://www.ti.com/product/TPS62840),
[STM32L031K6](https://www.st.com/resource/en/datasheet/stm32l031k6.pdf),
[Semtech SX1262](https://www.semtech.com/products/wireless-rf/lora-connect/sx1262),
[correntes TX/RX da Semtech](https://www.semtech.com/amazon-sidewalk-lora) e
[LIS2DW12](https://www.st.com/en/mems-and-sensors/lis2dw12.html).
