# Modelo virtual LIS2DW12

Status: **SIMULATED**. Este módulo C apresenta um periférico virtual acessível por operações de registrador I2C para integrar com a HAL do firmware. Não é um driver para o sensor físico nem uma reprodução certificada do silício.

## API de integração

Inclua `lis2dw12_model.h` e mantenha uma instância `lis2dw12_model_t`. O firmware usa os callbacks do HAL como ponte:

- `imu_read(ctx, sample)`: lê os seis bytes iniciando em `LIS2DW12_REG_OUT_X_L`, combina cada par little-endian como `int16_t` e preenche a amostra; se necessário lê `STATUS`.
- `imu_irq_pending(ctx)`: consulta `lis2dw12_irq_pending()` ou um flag definido pelo callback de `lis2dw12_init()`.
- O driver I2C da firmware encaminha transações para `lis2dw12_i2c_read()` e `lis2dw12_i2c_write()`.
- O agendador da simulação avança o sensor com `lis2dw12_tick(model, elapsed_ms)`; `lis2dw12_set_motion()` seleciona um perfil determinístico.

Exemplo mínimo:

```c
lis2dw12_model_t imu;
lis2dw12_init(&imu, irq_flag_set, &tag_irq);
uint8_t who = 0;
if (lis2dw12_i2c_read(&imu, LIS2DW12_REG_WHO_AM_I, &who, 1) != LIS2DW12_OK ||
    who != LIS2DW12_WHO_AM_I_VALUE) {
    /* SELF_TEST failure */
}
```

`lis2dw12_fail_next_i2c(&imu, n)` injeta erros nas próximas `n` transações;
`lis2dw12_timeout_next_i2c(&imu, n)` injeta timeouts I2C. Ambos se esgotam e a
transação seguinte pode recuperar normalmente. `lis2dw12_set_irq_faults()`
simula INT1 ausente ou preso; limpar a falha e a fonte permite recuperação.
Ler `WAKE_UP_SRC` ou `ALL_INT_SRC` reconhece fontes e limpa o IRQ latched.

## Registradores e perfis

Implementa WHO_AM_I (`0x0F`, valor `0x44`), registradores de controle
principais (`CTRL1`, `CTRL4`, `CTRL5`, `CTRL6`, `CTRL7` e wake), STATUS,
saídas X/Y/Z (`0x28`–`0x2D`) e fontes de interrupção. Saídas são signed
little-endian no formato de 16 bits do sensor. A unidade interna dos perfis é
mg; a faixa selecionável é ±2/4/8/16 g. `CTRL1.ODR` agenda atualizações em
tempo virtual, com resolução de relógio de 1 ms; atrasos longos avançam a
sequência e disponibilizam a amostra mais recente. A IRQ de wake requer
`CTRL4.INT1_WU` (`0x20`) e `CTRL7.INTERRUPTS_ENABLE` (`0x20`). Sono/repouso é
modelado pelo subconjunto `WAKE_UP_THS.SLEEP_ON`, `WAKE_UP_DUR` e rota de
mudança de sono em `CTRL5`.

## Datasets sintéticos

O gerador grava `STATIC`, `WALK`, `RUN`, `IMPACT` e `RANDOM_MOVEMENT` como CSV
mais um `manifest.json`. Cada conjunto registra seed, taxa em Hz, unidade `g`
e status `SIMULATED`. Os sinais são fixtures ilustrativas de firmware, não
medições ou padrões de comportamento bovino.

```sh
python3 hardware/models/lis2dw12/generate_datasets.py \
  --output hardware/models/lis2dw12/datasets --samples 128 \
  --sample-rate-hz 12.5 --seed 20261002
python3 -m pytest hardware/models/lis2dw12/tests/test_datasets.py -q
```

Renode upstream inclui `Sensors.LIS2DW12` desde a release 1.13.3. O arquivo
`hardware/renode/riose_stm32l0.repl` usa esse periférico nativo; converta uma
das CSVs para RESD com a ferramenta `csv2resd.py` da instalação Renode e
alimente-a por `imu FeedAccelerationSamplesFromRESD @<arquivo.resd>`. Isso
evita manter outro driver de periférico Renode no repositório.

## Referência do formato físico

A disposição e conversão da saída signed de 16 bits seguem a nota de aplicação oficial da ST [AN5038](https://www.st.com/resource/en/application_note/dm00401877-lis2dw12-alwayson-3d-accelerometer-stmicroelectronics.pdf), seção 4.5. O exemplo de wake-up da seção 5.4 configura `CTRL1=0x14` (12,5 Hz, high-performance), `WAKE_UP_DUR=0x00`, `WAKE_UP_THS=0x02` (62,5 mg a ±2 g), `CTRL4=0x20` e `CTRL7=0x20`. AN5038 descreve dados alinhados à esquerda e sensibilidade de 0,244 mg/LSB (14-bit, ±2 g); este modelo gera aceleração em mg e quantiza para esse formato. O limiar representa 1/64 da escala total por código.

## Limitações conhecidas

- Os perfis são formas de onda determinísticas inventadas para exercitar estados e não foram medidos em bovinos.
- Sensibilidade/quantização, ODR, conversão de limiar, filtros, interrupções e semântica de leitura implementam apenas o subconjunto necessário ao teste da aplicação; não substituem o datasheet nem garantem equivalência ciclo a ciclo com o LIS2DW12.
- I2C é uma API de chamada local, sem temporização elétrica, NACK/clock stretching, barramento compartilhado ou ruído analógico.
- A amostra fornece aceleração simulada; comportamento/saúde precisa ser inferido em outra camada e não é validado aqui.

## Build e teste

```sh
cmake -S hardware/models/lis2dw12 -B /tmp/lis2dw12-build
cmake --build /tmp/lis2dw12-build
ctest --test-dir /tmp/lis2dw12-build --output-on-failure
```

The motion profiles use an integer Q10 sine lookup table with linear
interpolation. This makes the model portable to the Zephyr host simulation
without `libm`; the waveform remains illustrative, not measured sensor data.
