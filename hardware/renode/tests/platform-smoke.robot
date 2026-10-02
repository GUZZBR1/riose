*** Settings ***
Documentation     Headless smoke and SX1262 protocol checks for the RIOSE Renode platform.
Library           RenodeLibrary
Library           String
Library           Collections

*** Variables ***
${PLATFORM}       ${CURDIR}/../riose_stm32l0.repl
${ELF}            %{RIOSE_ZEPHYR_ELF=}

*** Test Cases ***
Loads MCU Surrogate And Custom Peripherals
    ${listing}=    Execute Command    peripherals
    Should Contain    ${listing}    SX1262
    Should Contain    ${listing}    LIS2DW12
    [Setup]    Create RIOSE Platform

Loads Firmware When Provided
    Skip If    '${ELF}' == ''    Set RIOSE_ZEPHYR_ELF to a Zephyr ELF built for the STM32L0 profile.
    Execute Command    sysbus LoadELF @${ELF}
    Execute Command    start
    [Setup]    Create RIOSE Platform

SX1262 Config And FIFO Use SPI Command Bytes
    Send SX1262 Command    0x8A    0x01
    Send SX1262 Command    0x86    0x39    0x30    0x00    0x00
    Send SX1262 Command    0x8F    0x00    0x80
    Send SX1262 Command    0x0E    0x20    0xC1    0x7A    0x05
    ${radio_frequency}=    Execute Command    sysbus.spi1.radio RfFrequencyWord
    ${packet_type}=    Execute Command    sysbus.spi1.radio PacketType
    ${tx_base}=    Execute Command    sysbus.spi1.radio TxBase
    ${rx_base}=    Execute Command    sysbus.spi1.radio RxBase
    Should Be Equal As Integers    ${radio_frequency}    39300000    base=16
    Should Be Equal As Integers    ${packet_type}    01    base=16
    Should Be Equal As Integers    ${tx_base}    00    base=16
    Should Be Equal As Integers    ${rx_base}    80    base=16
    Execute Command    sysbus.spi1.radio Transmit 0x1E
    Execute Command    sysbus.spi1.radio Transmit 0x20
    Execute Command    sysbus.spi1.radio Transmit 0x00
    ${first_fifo_byte}=    Execute Command    sysbus.spi1.radio Transmit 0x00
    ${second_fifo_byte}=    Execute Command    sysbus.spi1.radio Transmit 0x00
    ${third_fifo_byte}=    Execute Command    sysbus.spi1.radio Transmit 0x00
    Execute Command    sysbus.spi1.radio FinishTransmission
    Should Be Equal As Integers    ${first_fifo_byte}    C1    base=16
    Should Be Equal As Integers    ${second_fifo_byte}    7A    base=16
    Should Be Equal As Integers    ${third_fifo_byte}    05    base=16
    Send SX1262 Command    0x0E    0xFF    0xAA    0xBB
    Execute Command    sysbus.spi1.radio Transmit 0x1E
    Execute Command    sysbus.spi1.radio Transmit 0xFF
    Execute Command    sysbus.spi1.radio Transmit 0x00
    ${wrap_first}=    Execute Command    sysbus.spi1.radio Transmit 0x00
    ${wrap_second}=    Execute Command    sysbus.spi1.radio Transmit 0x00
    Execute Command    sysbus.spi1.radio FinishTransmission
    Should Be Equal As Integers    ${wrap_first}    AA    base=16
    Should Be Equal As Integers    ${wrap_second}    BB    base=16
    ${long_fifo_write}=    Create List    0x0E    0x00
    FOR    ${index}    IN RANGE    0    510
        Append To List    ${long_fifo_write}    0xAA
    END
    Append To List    ${long_fifo_write}    0xBB
    Send SX1262 Command    @{long_fifo_write}
    Execute Command    sysbus.spi1.radio Transmit 0x1E
    Execute Command    sysbus.spi1.radio Transmit 0xFE
    Execute Command    sysbus.spi1.radio Transmit 0x00
    ${long_fifo_tail}=    Execute Command    sysbus.spi1.radio Transmit 0x00
    Execute Command    sysbus.spi1.radio FinishTransmission
    Should Be Equal As Integers    ${long_fifo_tail}    BB    base=16
    [Setup]    Create RIOSE Platform

SX1262 TX Completes On Virtual Time And Routes DIO1 IRQ
    Execute Command    sysbus.spi1.radio TxLatencyMs 7
    Send SX1262 Command    0x08    0x00    0x01    0x00    0x01    0x00    0x00    0x00    0x00
    Send SX1262 Command    0x83    0x00    0x00    0x00
    Execute Command    sysbus.spi1.radio TxLatencyMs 30
    ${busy}=    Execute Command    sysbus.spi1.radio BusyAsserted
    ${busy}=    Strip String    ${busy}
    Should Be Equal    ${busy}    True
    Execute Command    emulation RunFor "0.006"
    ${pending_mode}=    Execute Command    sysbus.spi1.radio CurrentMode
    Should Be Equal As Integers    ${pending_mode}    60    base=16
    Execute Command    emulation RunFor "0.001"
    ${done_mode}=    Execute Command    sysbus.spi1.radio CurrentMode
    ${irq_status}=    Execute Command    sysbus.spi1.radio IRQStatus
    ${irq}=    Execute Command    sysbus.spi1.radio IRQAsserted
    ${irq}=    Strip String    ${irq}
    Should Be Equal As Integers    ${done_mode}    20    base=16
    Should Be Equal As Integers    ${irq_status}    0001    base=16
    Should Be Equal    ${irq}    True
    Execute Command    sysbus.spi1.radio Transmit 0x12
    ${status}=    Execute Command    sysbus.spi1.radio Transmit 0x00
    ${irq_msb}=    Execute Command    sysbus.spi1.radio Transmit 0x00
    ${irq_lsb}=    Execute Command    sysbus.spi1.radio Transmit 0x00
    Execute Command    sysbus.spi1.radio FinishTransmission
    Should Be Equal As Integers    ${status}    22    base=16
    Should Be Equal As Integers    ${irq_msb}    00    base=16
    Should Be Equal As Integers    ${irq_lsb}    01    base=16
    Send SX1262 Command    0x02    0x00    0x01
    ${cleared_irq}=    Execute Command    sysbus.spi1.radio IRQAsserted
    ${cleared_irq}=    Strip String    ${cleared_irq}
    Should Be Equal    ${cleared_irq}    False
    [Setup]    Create RIOSE Platform

SX1262 TX Timeout And RX Window Are Distinct
    [Setup]    Create RIOSE Platform
    Send SX1262 Command    0x08    0x02    0x01    0x02    0x01    0x00    0x00    0x00    0x00
    Send SX1262 Command    0x83    0x00    0x00    0x01
    Execute Command    emulation RunFor "0.000015625"
    ${tx_irq}=    Execute Command    sysbus.spi1.radio IRQStatus
    Should Be Equal As Integers    ${tx_irq}    0200    base=16
    Execute Command    sysbus.spi1.radio Transmit 0x12
    ${tx_status}=    Execute Command    sysbus.spi1.radio Transmit 0x00
    ${tx_irq_msb}=    Execute Command    sysbus.spi1.radio Transmit 0x00
    ${tx_irq_lsb}=    Execute Command    sysbus.spi1.radio Transmit 0x00
    Execute Command    sysbus.spi1.radio FinishTransmission
    Should Be Equal As Integers    ${tx_status}    22    base=16
    Should Be Equal As Integers    ${tx_irq_msb}    02    base=16
    Should Be Equal As Integers    ${tx_irq_lsb}    00    base=16
    Send SX1262 Command    0x02    0x03    0xFF
    Send SX1262 Command    0x83    0x00    0x07    0x80
    Execute Command    emulation RunFor "0.030"
    ${equal_deadline_irq}=    Execute Command    sysbus.spi1.radio IRQStatus
    Should Be Equal As Integers    ${equal_deadline_irq}    0200    base=16
    Send SX1262 Command    0x02    0x03    0xFF
    Send SX1262 Command    0x82    0x00    0x00    0x40
    Execute Command    emulation RunFor "0.001"
    ${rx_irq}=    Execute Command    sysbus.spi1.radio IRQStatus
    Should Be Equal As Integers    ${rx_irq}    0200    base=16
    Execute Command    sysbus.spi1.radio Transmit 0x12
    ${rx_status}=    Execute Command    sysbus.spi1.radio Transmit 0x00
    ${rx_irq_msb}=    Execute Command    sysbus.spi1.radio Transmit 0x00
    ${rx_irq_lsb}=    Execute Command    sysbus.spi1.radio Transmit 0x00
    Execute Command    sysbus.spi1.radio FinishTransmission
    Should Be Equal As Integers    ${rx_status}    22    base=16
    Should Be Equal As Integers    ${rx_irq_msb}    02    base=16
    Should Be Equal As Integers    ${rx_irq_lsb}    00    base=16
    Send SX1262 Command    0x02    0x03    0xFF
    Send SX1262 Command    0x82    0x00    0x00    0x00
    Execute Command    emulation RunFor "0.999"
    ${continuous_mode}=    Execute Command    sysbus.spi1.radio CurrentMode
    Should Be Equal As Integers    ${continuous_mode}    50    base=16
    Execute Command    emulation RunFor "0.001"
    ${continuous_irq}=    Execute Command    sysbus.spi1.radio IRQStatus
    Should Be Equal As Integers    ${continuous_irq}    0200    base=16
    Send SX1262 Command    0x02    0x03    0xFF
    Send SX1262 Command    0x82    0x00    0x00    0x40
    Send SX1262 Command    0x80    0x00
    Execute Command    emulation RunFor "0.001"
    ${cancelled_rx_irq}=    Execute Command    sysbus.spi1.radio IRQStatus
    Should Be Equal As Integers    ${cancelled_rx_irq}    0000    base=16
    Send SX1262 Command    0x82    0x00    0x00    0x00
    Send SX1262 Command    0x83    0x00    0x00    0x00
    Execute Command    emulation RunFor "0.030"
    ${replacement_tx_irq}=    Execute Command    sysbus.spi1.radio IRQStatus
    Should Be Equal As Integers    ${replacement_tx_irq}    0001    base=16

SX1262 Rejects Malformed Frames And Reset Clears State
    [Setup]    Create RIOSE Platform
    Send SX1262 Command    0x86    0x39
    ${faults_after_short}=    Execute Command    sysbus.spi1.radio FaultCount
    Send SX1262 Command    0xFF
    ${faults_after_unknown}=    Execute Command    sysbus.spi1.radio FaultCount
    Send SX1262 Command    0x83    0x00    0x00    0x00    0x00
    ${faults_after_long}=    Execute Command    sysbus.spi1.radio FaultCount
    Send SX1262 Command    0x80    0x00    0x00
    ${faults_after_overlong}=    Execute Command    sysbus.spi1.radio FaultCount
    Should Be Equal As Integers    ${faults_after_short}    1    base=16
    Should Be Equal As Integers    ${faults_after_unknown}    2    base=16
    Should Be Equal As Integers    ${faults_after_long}    3    base=16
    Should Be Equal As Integers    ${faults_after_overlong}    4    base=16
    Execute Command    sysbus.spi1.radio Transmit 0xC0
    ${status_after_fault}=    Execute Command    sysbus.spi1.radio Transmit 0x00
    Execute Command    sysbus.spi1.radio FinishTransmission
    Should Be Equal As Integers    ${status_after_fault}    28    base=16
    Send SX1262 Command    0x08    0x00    0x01    0x00    0x01    0x00    0x00    0x00    0x00
    Send SX1262 Command    0x86    0x39    0x30    0x00    0x00
    Send SX1262 Command    0x0E    0x00    0xA5
    Send SX1262 Command    0x83    0x00    0x00    0x00
    Execute Command    sysbus.spi1.radio OnGPIO 0 false
    Execute Command    emulation RunFor "0.030"
    ${irq_after_reset}=    Execute Command    sysbus.spi1.radio IRQStatus
    Should Be Equal As Integers    ${irq_after_reset}    0000    base=16
    ${faults_after_reset}=    Execute Command    sysbus.spi1.radio FaultCount
    ${mode_after_reset}=    Execute Command    sysbus.spi1.radio CurrentMode
    Should Be Equal As Integers    ${faults_after_reset}    0    base=16
    Should Be Equal As Integers    ${mode_after_reset}    20    base=16
    ${frequency_after_reset}=    Execute Command    sysbus.spi1.radio RfFrequencyWord
    ${busy_after_reset}=    Execute Command    sysbus.spi1.radio BusyAsserted
    ${busy_after_reset}=    Strip String    ${busy_after_reset}
    Should Be Equal As Integers    ${frequency_after_reset}    00000000    base=16
    Should Be Equal    ${busy_after_reset}    False
    Execute Command    sysbus.spi1.radio Transmit 0x1E
    Execute Command    sysbus.spi1.radio Transmit 0x00
    Execute Command    sysbus.spi1.radio Transmit 0x00
    ${fifo_after_reset}=    Execute Command    sysbus.spi1.radio Transmit 0x00
    Execute Command    sysbus.spi1.radio FinishTransmission
    Should Be Equal As Integers    ${fifo_after_reset}    00    base=16
    Execute Command    sysbus.spi1.radio Transmit 0x83
    Execute Command    sysbus.spi1.radio Transmit 0x00
    Execute Command    sysbus.spi1.radio Transmit 0x00
    Execute Command    sysbus.spi1.radio Transmit 0x00
    Execute Command    sysbus.spi1.radio FinishTransmission
    Execute Command    emulation RunFor "0.030"
    ${irq_before_pending_reset}=    Execute Command    sysbus.spi1.radio IRQStatus
    Should Be Equal As Integers    ${irq_before_pending_reset}    0001    base=16
    Execute Command    sysbus.spi1.radio OnGPIO 0 false
    ${irq_pending_reset}=    Execute Command    sysbus.spi1.radio IRQStatus
    ${mode_pending_reset}=    Execute Command    sysbus.spi1.radio CurrentMode
    Should Be Equal As Integers    ${irq_pending_reset}    0000    base=16
    Should Be Equal As Integers    ${mode_pending_reset}    20    base=16

SX1262 Sleep And Standby Transitions Cancel Pending RX
    [Setup]    Create RIOSE Platform
    ${initial_mode}=    Execute Command    sysbus.spi1.radio CurrentMode
    Should Be Equal As Integers    ${initial_mode}    20    base=16
    Send SX1262 Command    0x84    0x04
    ${sleep_mode}=    Execute Command    sysbus.spi1.radio CurrentMode
    Should Be Equal As Integers    ${sleep_mode}    00    base=16
    Send SX1262 Command    0x83    0x00    0x00    0x00
    ${sleep_faults}=    Execute Command    sysbus.spi1.radio FaultCount
    ${sleep_mode_after_tx}=    Execute Command    sysbus.spi1.radio CurrentMode
    Should Be Equal As Integers    ${sleep_faults}    1
    Should Be Equal As Integers    ${sleep_mode_after_tx}    00    base=16
    Send SX1262 Command    0x80    0x00
    ${standby_rc}=    Execute Command    sysbus.spi1.radio CurrentMode
    Should Be Equal As Integers    ${standby_rc}    20    base=16
    Send SX1262 Command    0x82    0x00    0x00    0x40
    ${rx_mode}=    Execute Command    sysbus.spi1.radio CurrentMode
    Should Be Equal As Integers    ${rx_mode}    50    base=16
    Send SX1262 Command    0x80    0x01
    ${standby_xosc}=    Execute Command    sysbus.spi1.radio CurrentMode
    ${busy_after_standby}=    Execute Command    sysbus.spi1.radio BusyAsserted
    ${busy_after_standby}=    Strip String    ${busy_after_standby}
    Should Be Equal As Integers    ${standby_xosc}    30    base=16
    Should Be Equal    ${busy_after_standby}    False
    Execute Command    emulation RunFor "0.002"
    ${irq_after_cancel}=    Execute Command    sysbus.spi1.radio IRQStatus
    Should Be Equal As Integers    ${irq_after_cancel}    0000    base=16
SX1262 Busy IRQ And SPI Fault Hooks Are Controllable
    [Setup]    Create RIOSE Platform
    Execute Command    sysbus.spi1.radio HoldBusy true
    ${busy_stuck}=    Execute Command    sysbus.spi1.radio BusyAsserted
    ${busy_stuck}=    Strip String    ${busy_stuck}
    Should Be Equal    ${busy_stuck}    True
    Execute Command    sysbus.spi1.radio HoldBusy false
    Send SX1262 Command    0x08    0x00    0x01    0x00    0x01    0x00    0x00    0x00    0x00
    Send SX1262 Command    0x83    0x00    0x00    0x00
    Execute Command    emulation RunFor "0.030"
    ${routed_irq}=    Execute Command    sysbus.spi1.radio IRQAsserted
    ${routed_irq}=    Strip String    ${routed_irq}
    Should Be Equal    ${routed_irq}    True
    Execute Command    sysbus.spi1.radio SuppressIRQ true
    ${suppressed_irq}=    Execute Command    sysbus.spi1.radio IRQAsserted
    ${suppressed_irq}=    Strip String    ${suppressed_irq}
    Should Be Equal    ${suppressed_irq}    False
    Execute Command    sysbus.spi1.radio SuppressIRQ false
    Execute Command    sysbus.spi1.radio DropSPI true
    ${dropped_byte}=    Execute Command    sysbus.spi1.radio Transmit 0xC0
    Should Be Equal As Integers    ${dropped_byte}    FF    base=16
    Execute Command    sysbus.spi1.radio DropSPI false

*** Keywords ***
Create RIOSE Platform
    Execute Command    mach create
    Execute Command    machine LoadPlatformDescription @${PLATFORM}

Send SX1262 Command
    [Arguments]    @{bytes}
    FOR    ${byte}    IN    @{bytes}
        Execute Command    sysbus.spi1.radio Transmit ${byte}
    END
    Execute Command    sysbus.spi1.radio FinishTransmission
