*** Settings ***
Documentation     Headless smoke and SX1262 protocol checks for the RIOSE Renode platform.
Library           String
Library           Collections

*** Variables ***
${PLATFORM}       ${CURDIR}/../riose_stm32l0.repl
${ELF}            %{RIOSE_ZEPHYR_ELF=}
${STATIC_RESD}    %{RIOSE_LIS2DW12_STATIC_RESD=}
${WALK_RESD}      %{RIOSE_LIS2DW12_WALK_RESD=}
${RUN_RESD}       %{RIOSE_LIS2DW12_RUN_RESD=}
${GOLDEN_RESD}    %{RIOSE_LIS2DW12_GOLDEN_RESD=}

*** Test Cases ***
Loads MCU Surrogate, SX1262 And Native LIS2DW12
    ${listing}=    Execute Command    peripherals
    Should Contain    ${listing}    SX1262
    Should Contain    ${listing}    imu
    [Setup]    Create RIOSE Platform

LIS2DW12 Virtual Wake Event Routes INT1 And Read Clears Source
    Execute Command    sysbus.i2c1.imu Write [0x23, 0x20]
    Execute Command    sysbus.i2c1.imu FinishTransmission
    Execute Command    sysbus.i2c1.imu Write [0x3F, 0x20]
    Execute Command    sysbus.i2c1.imu FinishTransmission
    Execute Command    sysbus.i2c1.imu TriggerWakeup
    ${irq}=    Execute Command    sysbus.i2c1.imu WakeupIRQAsserted
    ${irq}=    Strip String    ${irq}
    Should Be Equal    ${irq}    True
    ${pa8}=    Execute Command    sysbus ReadDoubleWord 0x50000010
    Should Be True    (int($pa8.strip(), 0) & 0x100) != 0
    Execute Command    sysbus.i2c1.imu Write [0x38]
    ${source}=    Execute Command    sysbus.i2c1.imu Read 1
    Should Contain    ${source}    08
    Execute Command    sysbus.i2c1.imu FinishTransmission
    ${irq}=    Execute Command    sysbus.i2c1.imu WakeupIRQAsserted
    ${irq}=    Strip String    ${irq}
    Should Be Equal    ${irq}    False
    [Setup]    Create RIOSE Platform

LIS2DW12 Auto Increment Burst Read Returns Configured Sample
    Execute Command    sysbus.i2c1.imu DefaultAccelerationZ 1
    Execute Command    sysbus.i2c1.imu AccelerationZ 1
    Execute Command    sysbus.i2c1.imu Write [0x21, 0x0C]
    Execute Command    sysbus.i2c1.imu FinishTransmission
    Execute Command    sysbus.i2c1.imu Write [0x20, 0x14]
    Execute Command    sysbus.i2c1.imu FinishTransmission
    Execute Command    sysbus.i2c1.imu Write [0xA8]
    ${sample}=    Execute Command    sysbus.i2c1.imu Read 6
    Should Contain    ${sample}    0x08
    Should Contain    ${sample}    0x40
    Execute Command    sysbus.i2c1.imu FinishTransmission
    [Setup]    Create RIOSE Platform

LIS2DW12 Rejects Missing RESD Instead Of Silently Falling Back
    Configure LIS2DW12 RESD Playback
    Run Keyword And Expect Error    *    Execute Command    sysbus.i2c1.imu FeedAccelerationSamplesFromRESD @${CURDIR}/fixtures/lis2dw12/does-not-exist.resd
    [Setup]    Create RIOSE Platform

Firmware Boots Sleeps Services IRQ And Returns To Sleep
    Skip If    '${ELF}' == ''    Set RIOSE_ZEPHYR_ELF to a Zephyr ELF built for the STM32L0 profile.
    # A stationary 1 g sample is deterministic simulation input for boot
    # self-test; the explicit TriggerWakeup below is a separate virtual event.
    Execute Command    sysbus.i2c1.imu DefaultAccelerationZ 1
    Execute Command    sysbus.i2c1.imu AccelerationZ 1
    Execute Command    sysbus LoadELF @${ELF}
    Execute Command    emulation RunFor "0.25"
    # The simulator completes TX and the bounded RX window within this
    # interval, so the state machine should already have returned to sleep.
    Firmware State Should Be    2
    ${first_tx_count}=    Execute Command    sysbus.spi1.radio TxCount
    ${first_tx_opcode}=    Execute Command    sysbus.spi1.radio LastOpcode
    ${first_tx_faults}=    Execute Command    sysbus.spi1.radio FaultCount
    ${first_tx_mode}=    Execute Command    sysbus.spi1.radio CurrentMode
    ${first_rx_count}=    Execute Command    sysbus.spi1.radio RxCount
    ${first_rx_timeout}=    Execute Command    sysbus.spi1.radio RxTimeoutCount
    Should Be Equal As Integers    ${first_tx_count}    1
    Should Be Equal As Integers    ${first_tx_opcode}    84    base=16
    Should Be Equal As Integers    ${first_tx_faults}    0
    Should Be Equal As Integers    ${first_tx_mode}    00    base=16
    Should Be Equal As Integers    ${first_rx_count}    1
    Should Be Equal As Integers    ${first_rx_timeout}    1
    Execute Command    emulation RunFor "2.0"
    Firmware State Should Be    2
    Execute Command    sysbus.i2c1.imu TriggerWakeup
    ${irq}=    Execute Command    sysbus.i2c1.imu WakeupIRQAsserted
    ${irq}=    Strip String    ${irq}
    Should Be Equal    ${irq}    True
    ${pa8}=    Execute Command    sysbus ReadDoubleWord 0x50000010
    Should Be True    (int($pa8.strip(), 0) & 0x100) != 0
    ${wake_reads_before}=    Execute Command    sysbus.i2c1.imu WakeupEventReadCount
    Execute Command    emulation RunFor "5.1"
    Firmware State Should Be    2
    ${wake_reads_after}=    Execute Command    sysbus.i2c1.imu WakeupEventReadCount
    ${expected_wake_reads}=    Evaluate    int($wake_reads_before.strip(), 0) + 1
    Should Be Equal As Integers    ${wake_reads_after}    ${expected_wake_reads}
    ${irq}=    Execute Command    sysbus.i2c1.imu WakeupIRQAsserted
    ${irq}=    Strip String    ${irq}
    Should Be Equal    ${irq}    False
    [Setup]    Create RIOSE Platform

LIS2DW12 RESD Defaults And End Of Stream Preserve Native Behavior
    Skip If    '${STATIC_RESD}' == ''    Set RIOSE_LIS2DW12_STATIC_RESD to the STATIC RESD output.
    Configure LIS2DW12 RESD Playback
    Execute Command    sysbus.i2c1.imu FeedAccelerationSamplesFromRESD @${STATIC_RESD} sampleOffsetTime=-1000000000
    Execute Command    emulation RunFor "0.5"
    ${z}=    Execute Command    sysbus.i2c1.imu AccelerationZ
    Should Be Equal As Numbers    ${z}    1
    Execute Command    emulation RunFor "0.58"
    ${z}=    Execute Command    sysbus.i2c1.imu AccelerationZ
    Should Be Equal As Numbers    ${z}    1.002
    Execute Command    emulation RunFor "12"
    ${z}=    Execute Command    sysbus.i2c1.imu AccelerationZ
    # Native bypass mode holds the final sample until the next output read.
    Should Be Equal As Numbers    ${z}    1.001
    Execute Command    sysbus.i2c1.imu Write [0xA8]
    Execute Command    sysbus.i2c1.imu Read 6
    Execute Command    sysbus.i2c1.imu FinishTransmission
    ${z}=    Execute Command    sysbus.i2c1.imu AccelerationZ
    Should Be Equal As Numbers    ${z}    1
    # Both post-stream callbacks have fired; further time retains the default.
    Execute Command    emulation RunFor "0.5"
    ${z}=    Execute Command    sysbus.i2c1.imu AccelerationZ
    Should Be Equal As Numbers    ${z}    1
    [Setup]    Create RIOSE Platform

LIS2DW12 Pending Wake Stays Routed Across RESD Lifecycle Callbacks
    Skip If    '${STATIC_RESD}' == ''    Set RIOSE_LIS2DW12_STATIC_RESD to the STATIC RESD output.
    Execute Command    include @${CURDIR}/GPIOTransitionProbe.cs
    Execute Command    machine LoadPlatformDescription @${CURDIR}/gpio-transition-probe.repl
    Configure LIS2DW12 RESD Playback
    Execute Command    sysbus.i2c1.imu Write [0x23, 0x20]
    Execute Command    sysbus.i2c1.imu FinishTransmission
    Execute Command    sysbus.i2c1.imu Write [0x3F, 0x20]
    Execute Command    sysbus.i2c1.imu FinishTransmission
    Execute Command    sysbus.i2c1.imu FeedAccelerationSamplesFromRESD @${STATIC_RESD} sampleOffsetTime=-1000000000
    Execute Command    sysbus.i2c1.imu TriggerWakeup
    # Cross before-stream, active-stream and after-stream native callbacks.
    FOR    ${interval}    IN    0.2    1.0    12.0
        Execute Command    emulation RunFor "${interval}"
        ${pa8}=    Execute Command    sysbus ReadDoubleWord 0x50000010
        Should Be True    (int($pa8.strip(), 0) & 0x100) != 0
        ${rises}=    Execute Command    sysbus.irqProbe RisingEdgeCount
        ${falls}=    Execute Command    sysbus.irqProbe FallingEdgeCount
        Should Be Equal As Integers    ${rises}    1
        Should Be Equal As Integers    ${falls}    0
    END
    Execute Command    sysbus.i2c1.imu Write [0x38]
    ${source}=    Execute Command    sysbus.i2c1.imu Read 1
    Should Contain    ${source}    08
    Execute Command    sysbus.i2c1.imu FinishTransmission
    ${pa8}=    Execute Command    sysbus ReadDoubleWord 0x50000010
    Should Be True    (int($pa8.strip(), 0) & 0x100) == 0
    ${falls}=    Execute Command    sysbus.irqProbe FallingEdgeCount
    Should Be Equal As Integers    ${falls}    1
    [Setup]    Create RIOSE Platform

LIS2DW12 Native Data Ready IRQ Survives Wake Source Release
    Configure LIS2DW12 RESD Playback
    Execute Command    sysbus.i2c1.imu Write [0x23, 0x20]
    Execute Command    sysbus.i2c1.imu FinishTransmission
    Execute Command    sysbus.i2c1.imu Write [0x3F, 0x20]
    Execute Command    sysbus.i2c1.imu FinishTransmission
    Execute Command    sysbus.i2c1.imu TriggerWakeup
    # Native DRDY becomes active while the simulated wake already holds INT1.
    Execute Command    sysbus.i2c1.imu Write [0x23, 0x21]
    Execute Command    sysbus.i2c1.imu FinishTransmission
    Execute Command    sysbus.i2c1.imu AccelerationZ 1
    Execute Command    sysbus.i2c1.imu Write [0x38]
    Execute Command    sysbus.i2c1.imu Read 1
    Execute Command    sysbus.i2c1.imu FinishTransmission
    ${wake}=    Execute Command    sysbus.i2c1.imu WakeupIRQAsserted
    Should Be Equal    ${wake.strip()}    False
    ${pa8}=    Execute Command    sysbus ReadDoubleWord 0x50000010
    Should Be True    (int($pa8.strip(), 0) & 0x100) != 0
    # Releasing only the native source must now release the exposed pin.
    Execute Command    sysbus.i2c1.imu Write [0x23, 0x20]
    Execute Command    sysbus.i2c1.imu FinishTransmission
    ${pa8}=    Execute Command    sysbus ReadDoubleWord 0x50000010
    Should Be True    (int($pa8.strip(), 0) & 0x100) == 0
    Execute Command    sysbus.i2c1.imu TriggerWakeup
    Execute Command    sysbus.i2c1.imu Reset
    ${pa8}=    Execute Command    sysbus ReadDoubleWord 0x50000010
    Should Be True    (int($pa8.strip(), 0) & 0x100) == 0
    [Setup]    Create RIOSE Platform

Firmware Reads LIS2DW12 While STATIC RESD Is Loaded
    Skip If    '${ELF}' == ''    Set RIOSE_ZEPHYR_ELF to the Renode-profile Zephyr ELF.
    Skip If    '${STATIC_RESD}' == ''    Set RIOSE_LIS2DW12_STATIC_RESD to the STATIC RESD output.
    Configure LIS2DW12 RESD Playback
    Create Terminal Tester    sysbus.usart2    timeout=5    defaultPauseEmulation=False
    Execute Command    sysbus.i2c1.imu FeedAccelerationSamplesFromRESD @${STATIC_RESD}
    Execute Command    sysbus LoadELF @${ELF}
    Execute Command    emulation RunFor "0.25"
    Firmware State Should Be    2
    ${reads}=    Execute Command    sysbus.i2c1.imu OutputSampleReadCount
    ${raw_z}=    Execute Command    sysbus.i2c1.imu LastOutputZRaw
    Should Be True    int($reads.strip(), 0) > 0
    Firmware LIS2DW12 Output Should Match RESD First Sample    ${STATIC_RESD}
    ${trace}=    Wait For Line On Uart    SIMULATED_TRACE,v1,[0-9]+,[0-9]+,[0-9]+,IMU_READ,4,[0-9]+,0,-?[0-9]+,-?[0-9]+,-?[0-9]+,.*    treatAsRegex=True    timeout=10
    Firmware LIS2DW12 Trace Should Match RESD First Sample    ${STATIC_RESD}    ${trace}
    Log To Console    CAPTURED_FIRMWARE_TRACE profile=STATIC ${trace.Line}
    Log To Console    SIMULATED_STATIC_RESD_RAW_Z=${raw_z}
    [Setup]    Create RIOSE Platform

Firmware Reads LIS2DW12 While WALK RESD Is Loaded
    Skip If    '${ELF}' == ''    Set RIOSE_ZEPHYR_ELF to the Renode-profile Zephyr ELF.
    Skip If    '${WALK_RESD}' == ''    Set RIOSE_LIS2DW12_WALK_RESD to the WALK RESD output.
    Configure LIS2DW12 RESD Playback
    Create Terminal Tester    sysbus.usart2    timeout=5    defaultPauseEmulation=False
    Execute Command    sysbus.i2c1.imu FeedAccelerationSamplesFromRESD @${WALK_RESD}
    Execute Command    sysbus LoadELF @${ELF}
    Execute Command    emulation RunFor "0.25"
    Firmware State Should Be    2
    ${reads}=    Execute Command    sysbus.i2c1.imu OutputSampleReadCount
    ${raw_z}=    Execute Command    sysbus.i2c1.imu LastOutputZRaw
    Should Be True    int($reads.strip(), 0) > 0
    Firmware LIS2DW12 Output Should Match RESD First Sample    ${WALK_RESD}
    ${trace}=    Wait For Line On Uart    SIMULATED_TRACE,v1,[0-9]+,[0-9]+,[0-9]+,IMU_READ,4,[0-9]+,0,-?[0-9]+,-?[0-9]+,-?[0-9]+,.*    treatAsRegex=True    timeout=10
    Firmware LIS2DW12 Trace Should Match RESD First Sample    ${WALK_RESD}    ${trace}
    Log To Console    CAPTURED_FIRMWARE_TRACE profile=WALK ${trace.Line}
    Log To Console    SIMULATED_WALK_RESD_RAW_Z=${raw_z}
    [Setup]    Create RIOSE Platform

Firmware Reads LIS2DW12 While RUN RESD Is Loaded
    Skip If    '${ELF}' == ''    Set RIOSE_ZEPHYR_ELF to the Renode-profile Zephyr ELF.
    Skip If    '${RUN_RESD}' == ''    Set RIOSE_LIS2DW12_RUN_RESD to the RUN RESD output.
    Configure LIS2DW12 RESD Playback
    Create Terminal Tester    sysbus.usart2    timeout=5    defaultPauseEmulation=False
    Execute Command    sysbus.i2c1.imu FeedAccelerationSamplesFromRESD @${RUN_RESD}
    Execute Command    sysbus LoadELF @${ELF}
    Execute Command    emulation RunFor "0.25"
    Firmware State Should Be    2
    ${reads}=    Execute Command    sysbus.i2c1.imu OutputSampleReadCount
    ${raw_z}=    Execute Command    sysbus.i2c1.imu LastOutputZRaw
    Should Be True    int($reads.strip(), 0) > 0
    Firmware LIS2DW12 Output Should Match RESD First Sample    ${RUN_RESD}
    ${trace}=    Wait For Line On Uart    SIMULATED_TRACE,v1,[0-9]+,[0-9]+,[0-9]+,IMU_READ,4,[0-9]+,0,-?[0-9]+,-?[0-9]+,-?[0-9]+,.*    treatAsRegex=True    timeout=10
    Firmware LIS2DW12 Trace Should Match RESD First Sample    ${RUN_RESD}    ${trace}
    Log To Console    CAPTURED_FIRMWARE_TRACE profile=RUN ${trace.Line}
    Log To Console    SIMULATED_RUN_RESD_RAW_Z=${raw_z}
    [Setup]    Create RIOSE Platform

Firmware Reads Controlled Golden Axis Probe
    Skip If    '${ELF}' == ''    Set RIOSE_ZEPHYR_ELF to the Renode-profile Zephyr ELF.
    Skip If    '${GOLDEN_RESD}' == ''    Convert the controlled golden_axis_probe.csv fixture to RESD.
    Configure LIS2DW12 RESD Playback
    Create Terminal Tester    sysbus.usart2    timeout=5    defaultPauseEmulation=False
    Execute Command    sysbus.i2c1.imu FeedAccelerationSamplesFromRESD @${GOLDEN_RESD}
    Execute Command    sysbus LoadELF @${ELF}
    Execute Command    emulation RunFor "0.25"
    Firmware State Should Be    2
    ${reads}=    Execute Command    sysbus.i2c1.imu OutputSampleReadCount
    Should Be True    int($reads.strip(), 0) > 0
    Firmware LIS2DW12 Output Should Match RESD First Sample    ${GOLDEN_RESD}
    ${trace}=    Wait For Line On Uart    SIMULATED_TRACE,v1,[0-9]+,[0-9]+,[0-9]+,IMU_READ,4,[0-9]+,0,-?[0-9]+,-?[0-9]+,-?[0-9]+,.*    treatAsRegex=True    timeout=10
    Firmware LIS2DW12 Trace Should Match RESD First Sample    ${GOLDEN_RESD}    ${trace}
    Log To Console    CAPTURED_FIRMWARE_TRACE profile=GOLDEN_AXIS_PROBE ${trace.Line}
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
    Send SX1262 Command    0x83    0x00    0x00    0x00
    Execute Command    emulation RunFor "0.030"
    ${stuck_mode}=    Execute Command    sysbus.spi1.radio CurrentMode
    ${stuck_irq}=    Execute Command    sysbus.spi1.radio IRQStatus
    ${stuck_tx_count}=    Execute Command    sysbus.spi1.radio TxCount
    ${stuck_fault_count}=    Execute Command    sysbus.spi1.radio FaultCount
    Should Be Equal As Integers    ${stuck_mode}    20    base=16
    Should Be Equal As Integers    ${stuck_irq}    0000    base=16
    Should Be Equal As Integers    ${stuck_tx_count}    0
    Should Be Equal As Integers    ${stuck_fault_count}    1
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
    Send SX1262 Command    0x02    0x03    0xFF
    Send SX1262 Command    0x83    0x00    0x00    0x00
    Execute Command    emulation RunFor "0.030"
    ${completed_without_irq_status}=    Execute Command    sysbus.spi1.radio IRQStatus
    ${completed_without_irq_pin}=    Execute Command    sysbus.spi1.radio IRQAsserted
    ${completed_without_irq_pin}=    Strip String    ${completed_without_irq_pin}
    Should Be Equal As Integers    ${completed_without_irq_status}    0001    base=16
    Should Be Equal    ${completed_without_irq_pin}    False
    Execute Command    sysbus.spi1.radio SuppressIRQ false
    ${restored_irq_pin}=    Execute Command    sysbus.spi1.radio IRQAsserted
    ${restored_irq_pin}=    Strip String    ${restored_irq_pin}
    Should Be Equal    ${restored_irq_pin}    True
    Execute Command    sysbus.spi1.radio DropSPI true
    ${dropped_byte}=    Execute Command    sysbus.spi1.radio Transmit 0xC0
    Should Be Equal As Integers    ${dropped_byte}    FF    base=16
    Execute Command    sysbus.spi1.radio DropSPI false

*** Keywords ***
Configure LIS2DW12 RESD Playback
    # Configure through the public I2C interface, rather than assigning the
    # upstream private integer SampleRate property a fractional frequency.
    Execute Command    sysbus.i2c1.imu Write [0x20, 0x24]
    Execute Command    sysbus.i2c1.imu FinishTransmission

Firmware LIS2DW12 Output Should Match RESD First Sample
    [Arguments]    ${resd}
    ${payload}=    Evaluate    pathlib.Path($resd).read_bytes()    modules=pathlib
    ${metadata_size}=    Evaluate    struct.unpack_from('<Q', $payload, 37)[0]    modules=struct
    ${ug}=    Evaluate    struct.unpack_from('<iii', $payload, 45 + $metadata_size)    modules=struct
    # The existing firmware writes CTRL1=0x14, which Renode models as
    # high-performance 14-bit output at +/-2 g (244 ug/LSB, left-shift 2).
    FOR    ${axis}    ${index}    IN    X    0    Y    1    Z    2
        ${actual}=    Execute Command    sysbus.i2c1.imu LastOutput${axis}Raw
        ${actual}=    Evaluate    (int($actual.strip(), 0) + 2**31) % 2**32 - 2**31
        ${expected}=    Evaluate    int($ug[int($index)] / 244) * 4
        Should Be Equal As Integers    ${actual}    ${expected}
    END

Firmware LIS2DW12 Trace Should Match RESD First Sample
    [Arguments]    ${resd}    ${trace}
    ${payload}=    Evaluate    pathlib.Path($resd).read_bytes()    modules=pathlib
    ${metadata_size}=    Evaluate    struct.unpack_from('<Q', $payload, 37)[0]    modules=struct
    ${ug}=    Evaluate    struct.unpack_from('<iii', $payload, 45 + $metadata_size)    modules=struct
    ${trace_text}=    Set Variable    ${trace.Line}
    ${fields}=    Evaluate    ("SIMULATED_TRACE" + str($trace_text).split("SIMULATED_TRACE", 1)[1]).strip().split(',')
    Should Be Equal    ${fields}[5]    IMU_READ
    Should Be Equal As Integers    ${fields}[8]    0
    FOR    ${axis}    ${index}    IN    X    0    Y    1    Z    2
        ${register}=    Evaluate    int($ug[int($index)] / 244) * 4
        ${expected}=    Evaluate    int((int($register) >> 4) * 976 / 1000)
        ${actual}=    Evaluate    (int($fields[9 + int($index)]) + 2**31) % 2**32 - 2**31
        Should Be Equal As Integers    ${actual}    ${expected}    msg=firmware ${axis} trace value should match the selected RESD sample
    END

Create RIOSE Platform
    Execute Command    mach create
    Execute Command    machine LoadPlatformDescription @${PLATFORM}

Firmware State Should Be
    [Arguments]    ${expected}
    ${odr}=    Execute Command    sysbus ReadDoubleWord 0x50000014
    ${raw}=    Evaluate    int($odr.strip(), 0)
    ${state}=    Evaluate    ($raw & 0x03) | (($raw & 0x08) >> 1)
    Should Be Equal As Integers    ${state}    ${expected}

Send SX1262 Command
    [Arguments]    @{bytes}
    FOR    ${byte}    IN    @{bytes}
        Execute Command    sysbus.spi1.radio Transmit ${byte}
    END
    Execute Command    sysbus.spi1.radio FinishTransmission
