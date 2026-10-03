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

`lis2dw12_fail_next_i2c(&imu, n)` injeta erros de barramento e `lis2dw12_timeout_next_i2c(&imu, n)` injeta timeouts nas próximas transações para validar recuperação do firmware. Ambos são falhas digitais injetadas, sem representar duração elétrica medida. `WAKE_UP_SRC`/`ALL_INT_SRC` limpam o IRQ latched quando lidos; também existe `lis2dw12_clear_irq()`.

## Registradores e perfis

Implementa WHO_AM_I (`0x0F`, valor `0x44`), registradores de controle principais (`CTRL1`, `CTRL4_INT1_PAD_CTRL`, `CTRL6`, `CTRL7`, limiar de wake), STATUS/data-ready, saídas X/Y/Z (`0x28`–`0x2D`) e fontes de interrupção. Saídas são palavras signed little-endian, 16-bit alinhadas à esquerda como no formato de dados do sensor. A referência de sensibilidade é ±2/4/8/16 g; a resolução exata depende do modo. `CTRL1` liga/desliga atualizações e `CTRL6` seleciona ±2/4/8/16 g. Perfis disponíveis: `STATIC` (alias de stationary), grazing, walking, running, `IMPACT` (pulso ilustrativo periódico) e `RANDOM_MOVEMENT` (amostras limitadas em mg). `lis2dw12_set_motion_seed()` define a semente do perfil aleatório; mesma semente e mesma sequência de ticks produzem a mesma saída. Semente zero usa um valor padrão fixo. Perfis, amostras e traces têm status **SIMULATED**; não são medições nem rótulos de comportamento bovino. A cadência temporal das chamadas `lis2dw12_tick()` é fornecida pelo scheduler anfitrião; este modelo não reproduz a temporização interna exata do ODR. A IRQ de wake exige ambos `CTRL4.INT1_WU` (`0x20`) e `CTRL7.INTERRUPTS_ENABLE` (`0x20`), além de limiar e ODR ativos. Ler `WAKE_UP_SRC` apresenta `WU_IA` no bit 3 e limpa a condição latched.

## Referência do formato físico

A disposição e conversão da saída signed de 16 bits seguem a nota de aplicação oficial da ST [AN5038](https://www.st.com/resource/en/application_note/dm00401877-lis2dw12-alwayson-3d-accelerometer-stmicroelectronics.pdf), seção 4.5. O caminho físico configura `CTRL1=0x14` (12,5 Hz, low-power), `WAKE_UP_DUR=0x00`, `WAKE_UP_THS=0x02` (62,5 mg a ±2 g), `CTRL4=0x20` e `CTRL7=0x20`, seguindo o exemplo de wake-up da seção 5.4. AN5038 descreve dados alinhados à esquerda e sensibilidade de 0,244 mg/LSB (14-bit, ±2 g); este modelo gera aceleração física em mg e quantiza para esse formato. O limiar representa 1/64 da escala total por código.

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
