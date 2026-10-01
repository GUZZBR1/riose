cmake_minimum_required(VERSION 3.16)
project(cattle_tag_firmware C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

add_library(tag_firmware STATIC src/tag_firmware.c src/sx1262.c)
target_include_directories(tag_firmware PUBLIC include)
target_compile_options(tag_firmware PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(tag_host_demo host/main.c)
target_link_libraries(tag_host_demo PRIVATE tag_firmware)
target_compile_options(tag_host_demo PRIVATE -Wall -Wextra -Wpedantic -Werror)

enable_testing()
add_test(NAME tag_host_cycle COMMAND tag_host_demo)
