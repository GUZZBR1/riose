cmake_minimum_required(VERSION 3.16)
project(cattle_hardware_integration C)

add_subdirectory(../firmware firmware)
add_subdirectory(../models/sx1262 sx1262_model)
add_subdirectory(../models/lis2dw12 lis2dw12_model)

add_executable(hardware_integration integration.c)
target_link_libraries(hardware_integration PRIVATE tag_firmware sx1262_model lis2dw12_model m)
target_compile_options(hardware_integration PRIVATE -Wall -Wextra -Wpedantic -Werror)
enable_testing()
add_test(NAME hardware_integration COMMAND hardware_integration)

add_executable(sx1262_driver_config sx1262_driver_config.c)
target_link_libraries(sx1262_driver_config PRIVATE tag_firmware sx1262_model)
target_compile_options(sx1262_driver_config PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_test(NAME sx1262_driver_config COMMAND sx1262_driver_config)
