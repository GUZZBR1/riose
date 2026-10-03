*** Settings ***
Documentation     SIMULATED controller register timeout, distinct from a dropped response byte or radio timeout.
Library           RenodeLibrary

*** Variables ***
${FAULT_MODEL}    ${CURDIR}/../src/SPITransferFault.cs
${FAULT_OVERLAY}  ${CURDIR}/../spi-transfer-fault.repl

*** Test Cases ***
SPI Stall Reaches Deadline On Virtual Time And Recovers
    [Setup]    Create SPI Fault Platform
    Execute Command    sysbus.spi1Fault TimeoutUs 10000
    Execute Command    sysbus.spi1Fault StallTransfers true
    Execute Command    sysbus WriteWord 0x4001300C 0xC0
    SPI Status Should Be    0x80
    Timeout Count Should Be    0
    Execute Command    emulation RunFor "0.009"
    SPI Status Should Be    0x80
    Timeout Count Should Be    0
    # Repeated register polls and attempted writes do not move the deadline.
    Execute Command    sysbus WriteByte 0x4001300C 0x00
    ${pending_data}=    Execute Command    sysbus ReadByte 0x4001300C
    Should Be Equal As Integers    ${pending_data}    0
    Execute Command    emulation RunFor "0.001"
    Timeout Count Should Be    1
    SPI Status Should Be    0x02
    Execute Command    emulation RunFor "0.020"
    Timeout Count Should Be    1
    Execute Command    sysbus.spi1Fault StallTransfers false
    Execute Command    sysbus WriteByte 0x4001300C 0xC0
    SPI Status Should Be    0x03
    Execute Command    sysbus ReadByte 0x4001300C
    Execute Command    sysbus WriteByte 0x4001300C 0x00
    ${status_byte}=    Execute Command    sysbus ReadByte 0x4001300C
    Should Be Equal As Integers    ${status_byte}    0x22
    Execute Command    sysbus.spi1.radio FinishTransmission
    SPI Status Should Be    0x02
    ${radio_faults}=    Execute Command    sysbus.spi1.radio FaultCount
    Should Be Equal As Integers    ${radio_faults}    0

SPI Disable And Reset Cancel Pending Deadline
    [Setup]    Create SPI Fault Platform
    Execute Command    sysbus.spi1Fault TimeoutUs 10000
    Execute Command    sysbus.spi1Fault StallTransfers true
    Execute Command    sysbus WriteDoubleWord 0x4001300C 0xC0
    Execute Command    emulation RunFor "0.005"
    Execute Command    sysbus WriteWord 0x40013000 0x304
    Execute Command    emulation RunFor "0.010"
    Timeout Count Should Be    0
    SPI Status Should Be    0x02
    Execute Command    sysbus WriteWord 0x40013000 0x344
    Execute Command    sysbus WriteDoubleWord 0x4001300C 0xC0
    SPI Status Should Be    0x80
    Execute Command    sysbus.spi1Fault Reset
    Execute Command    emulation RunFor "0.010"
    Timeout Count Should Be    0
    SPI Status Should Be    0x02

SPI Dropped Response Is Immediate And Is Not A Timed Controller Failure
    [Setup]    Create SPI Fault Platform
    Execute Command    sysbus.spi1.radio DropSPI true
    Execute Command    sysbus WriteByte 0x4001300C 0xC0
    SPI Status Should Be    0x03
    ${response}=    Execute Command    sysbus ReadByte 0x4001300C
    Should Be Equal As Integers    ${response}    0xFF
    Execute Command    emulation RunFor "0.020"
    Timeout Count Should Be    0
    SPI Status Should Be    0x02

*** Keywords ***
Create SPI Fault Platform
    Execute Command    mach create
    Execute Command    include @${FAULT_MODEL}
    Execute Command    machine LoadPlatformDescription @${FAULT_OVERLAY}
    Execute Command    cpu IsHalted true
    # SPE, master mode, software chip select, internal select asserted.
    Execute Command    sysbus WriteWord 0x40013000 0x344

SPI Status Should Be
    [Arguments]    ${expected}
    ${status}=    Execute Command    sysbus ReadWord 0x40013008
    Should Be Equal As Integers    ${status}    ${expected}

Timeout Count Should Be
    [Arguments]    ${expected}
    ${count}=    Execute Command    sysbus.spi1Fault TimeoutCount
    Should Be Equal As Integers    ${count}    ${expected}
