cmake_minimum_required(VERSION 3.16)
project(lis2dw12_virtual_model C)

add_library(lis2dw12_model lis2dw12_model.c)
target_include_directories(lis2dw12_model PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_features(lis2dw12_model PUBLIC c_std_11)
target_compile_options(lis2dw12_model PRIVATE -Wall -Wextra -Wpedantic -Werror)
target_link_libraries(lis2dw12_model PUBLIC m)

add_executable(test_lis2dw12 tests/test_lis2dw12.c)
target_link_libraries(test_lis2dw12 PRIVATE lis2dw12_model)
target_compile_options(test_lis2dw12 PRIVATE -Wall -Wextra -Wpedantic -Werror)
enable_testing()
add_test(NAME lis2dw12_model COMMAND test_lis2dw12)
