cmake_minimum_required(VERSION 3.16)
project(cattle_tag_firmware C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

add_library(tag_firmware STATIC src/tag_firmware.c src/sx1262.c src/reset_cause.c)
target_include_directories(tag_firmware PUBLIC include)
target_compile_options(tag_firmware PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(tag_host_demo host/main.c)
target_link_libraries(tag_host_demo PRIVATE tag_firmware)
target_compile_options(tag_host_demo PRIVATE -Wall -Wextra -Wpedantic -Werror)
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(tag_firmware PRIVATE -fstack-usage)
    target_compile_options(tag_host_demo PRIVATE -fstack-usage)
endif()

enable_testing()
add_test(NAME tag_host_cycle COMMAND tag_host_demo)
foreach(profile NORMAL ACTIVE ALERT WORST_REASONABLE_CASE)
    add_test(NAME tag_host_longrun_${profile}
             COMMAND tag_host_demo --long-run-days 1 --scenario ${profile} --seed 7)
endforeach()
add_test(NAME tag_host_counter_wrap
         COMMAND tag_host_demo --long-run-days 1 --scenario NORMAL --seed 7
                 --start-time-ms 4294900000 --start-sequence 4294967295)
add_test(NAME tag_host_fault_spi_timeout COMMAND tag_host_demo --fault spi_timeout_once --seed 7)
add_test(NAME tag_host_fault_i2c_timeout COMMAND tag_host_demo --fault imu_i2c_timeout_once --seed 7)
add_test(NAME tag_host_fault_irq_missing COMMAND tag_host_demo --fault irq_missing --seed 7)
