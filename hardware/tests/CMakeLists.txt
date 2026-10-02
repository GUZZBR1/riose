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
add_test(NAME firmware_trace_export
  COMMAND hardware_integration --trace-output ${CMAKE_CURRENT_BINARY_DIR}/firmware-trace.jsonl)
foreach(scenario NORMAL ACTIVE ALERT WORST_REASONABLE_CASE)
  string(TOLOWER ${scenario} scenario_slug)
  add_test(NAME firmware_trace_${scenario_slug}
    COMMAND hardware_integration
      --trace-output ${CMAKE_CURRENT_BINARY_DIR}/${scenario_slug}-trace.jsonl
      --trace-scenario ${scenario})
endforeach()
find_package(Python3 COMPONENTS Interpreter REQUIRED)
add_test(NAME firmware_trace_schema
  COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/check_trace_schema.py
    ${CMAKE_CURRENT_BINARY_DIR})
set_tests_properties(firmware_trace_schema PROPERTIES
  DEPENDS "firmware_trace_normal;firmware_trace_active;firmware_trace_alert;firmware_trace_worst_reasonable_case")
foreach(days 1 7 30)
  foreach(scenario NORMAL ACTIVE ALERT WORST_REASONABLE_CASE)
    string(TOLOWER ${scenario} scenario_slug)
    add_test(NAME virtual_${scenario_slug}_${days}d
      COMMAND hardware_integration --long-run-days ${days} --scenario ${scenario})
    set_tests_properties(virtual_${scenario_slug}_${days}d PROPERTIES
      PASS_REGULAR_EXPRESSION "status.*COMPLETED")
  endforeach()
endforeach()

add_executable(sx1262_driver_config sx1262_driver_config.c)
target_link_libraries(sx1262_driver_config PRIVATE tag_firmware sx1262_model)
target_compile_options(sx1262_driver_config PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_test(NAME sx1262_driver_config COMMAND sx1262_driver_config)
