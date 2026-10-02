*** Settings ***
Documentation     Headless checks for the RIOSE STM32L0 Renode surrogate.
Suite Setup       Setup
Suite Teardown    Teardown
Test Teardown     Test Teardown
Resource          ${RENODEKEYWORDS}

*** Variables ***
${PLATFORM}       ${CURDIR}/../riose_stm32l0.repl
${ELF}            %{RIOSE_ZEPHYR_ELF=}
${STATE_MASK}     0x0B

*** Test Cases ***
Loads MCU Surrogate And Custom Peripherals
    Create RIOSE Platform
    ${listing}=    Execute Command    peripherals
    Should Contain    ${listing}    SX1262
    Should Contain    ${listing}    LIS2DW12

Firmware Boots Sleeps Services IRQ And Returns To Sleep
    Skip If    '${ELF}' == ''    Set RIOSE_ZEPHYR_ELF to a Zephyr ELF built for the STM32L0 profile.
    Create RIOSE Platform
    Execute Command    sysbus LoadELF @${ELF}
    Execute Command    emulation RunFor "0.1"
    Firmware State Should Be    2
    Execute Command    sysbus.imu TriggerWakeup
    ${irq}=    Execute Command    sysbus.imu WakeupIRQAsserted
    Should Be Equal    ${irq}    True
    Execute Command    emulation RunFor "0.1"
    Firmware State Should Be    2
    ${irq}=    Execute Command    sysbus.imu WakeupIRQAsserted
    Should Be Equal    ${irq}    False

*** Keywords ***
Create RIOSE Platform
    Execute Command    mach create
    Execute Command    machine LoadPlatformDescription @${PLATFORM}

Firmware State Should Be
    [Arguments]    ${expected}
    ${odr}=    Execute Command    sysbus ReadDoubleWord 0x50000014
    ${state}=    Evaluate    int("${odr}", 0) & ${STATE_MASK}
    Should Be Equal As Integers    ${state}    ${expected}
