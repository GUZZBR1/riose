cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(cattle_tag_zephyr)

if(CONFIG_BOARD_NATIVE_SIM)
  # native_sim runs the same firmware command protocol against the C
  # peripheral models; this avoids a second Zephyr bus-emulator stack.
  target_sources(app PRIVATE
    src/native_sim_main.c
    ../src/tag_firmware.c
    ../src/sx1262.c
    ../src/reset_cause.c
    ../../models/sx1262/src/sx1262_model.c
    ../../models/lis2dw12/lis2dw12_model.c
  )
  target_include_directories(app PRIVATE
    ../include
    ../../models/sx1262/include
    ../../models/lis2dw12
  )
else()
  target_sources(app PRIVATE src/main.c ../src/tag_firmware.c ../src/sx1262.c ../src/reset_cause.c)
  target_include_directories(app PRIVATE ../include)
endif()
