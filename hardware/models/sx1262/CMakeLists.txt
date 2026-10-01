cmake_minimum_required(VERSION 3.16)
project(sx1262_model C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

add_library(sx1262_model src/sx1262_model.c)
target_include_directories(sx1262_model PUBLIC include)
target_compile_options(sx1262_model PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(sx1262_model_smoke tests/model_smoke.c)
target_link_libraries(sx1262_model_smoke PRIVATE sx1262_model)
target_compile_options(sx1262_model_smoke PRIVATE -Wall -Wextra -Wpedantic -Werror)

enable_testing()
add_test(NAME sx1262_model_smoke COMMAND sx1262_model_smoke)
