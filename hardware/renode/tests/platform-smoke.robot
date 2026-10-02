*** Settings ***
Documentation     Headless smoke check for the RIOSE STM32L0 Renode platform.
Library           RenodeLibrary
Suite Setup       Setup
Suite Teardown    Teardown

*** Variables ***
${PLATFORM}       ${CURDIR}/../riose_stm32l0.repl
${ELF}            %{RIOSE_ZEPHYR_ELF=}

*** Test Cases ***
Loads MCU Surrogate And Custom Peripherals
    Execute Command    mach create
    Execute Command    machine LoadPlatformDescription @${PLATFORM}
    ${listing}=    Execute Command    peripherals
    Should Contain    ${listing}    SX1262
    Should Contain    ${listing}    LIS2DW12

Loads Firmware When Provided
    Skip If    '${ELF}' == ''    Set RIOSE_ZEPHYR_ELF to a Zephyr ELF built for the STM32L0 profile.
    Execute Command    sysbus LoadELF @${ELF}
    Execute Command    start

*** Keywords ***
Setup
    Setup Renode
    Execute Command    include @${CURDIR}/../src/RiosePeripherals.cs

Teardown
    Teardown Renode
