# A_FILE and the disc image.
#
# The game's data is not in this repository: every file of the disc but the EXE and
# A_FILE, and the members of A_FILE that are not overlays, are extracted from the
# original disc image at build time. The EXE and the 13 overlays are this project's.
#
#   cmake -S . -B build -DORIGINAL_DISC=/path/to/disc.bin
#
# Without ORIGINAL_DISC the targets afile and disc do not exist and check covers the
# 14 binaries only.

set(ORIGINAL_DISC "" CACHE FILEPATH
    "The original disc image (its .bin, MODE2/2352) the game's data is extracted from")
if(NOT ORIGINAL_DISC)
    message(STATUS "ORIGINAL_DISC is not set: A_FILE and the disc image are not built")
    return()
endif()
if(NOT EXISTS ${ORIGINAL_DISC})
    message(FATAL_ERROR "ORIGINAL_DISC: ${ORIGINAL_DISC} does not exist")
endif()

set(PSX_EXE SLUS_011.15)
set(original ${CMAKE_BINARY_DIR}/original)
set(layout ${CMAKE_SOURCE_DIR}/disc/disc.xml)
set(members ${CMAKE_SOURCE_DIR}/disc/a_file.txt)
set(afile_bin ${CMAKE_BINARY_DIR}/A_FILE.BIN)
set(afile_hdt ${CMAKE_BINARY_DIR}/A_FILE.HDT)
set(translated_original ${CMAKE_BINARY_DIR}/translated_A_FILE)
set(translation_stamp ${CMAKE_BINARY_DIR}/translations.stamp)

# The original's files (original/disc/) and A_FILE's members (original/A_FILE/).
add_custom_command(
    OUTPUT ${original}.stamp
    COMMAND ${CMAKE_COMMAND} -E rm -rf ${original}
    COMMAND ${Python3_EXECUTABLE} tools/psx_disc.py extract ${ORIGINAL_DISC} --out ${original}/disc
    COMMAND ${Python3_EXECUTABLE} tools/afile.py unpack --members ${members}
        --bin ${original}/disc/A_FILE.BIN --hdt ${original}/disc/A_FILE.HDT --out ${original}/A_FILE
    COMMAND ${CMAKE_COMMAND} -E touch ${original}.stamp
    DEPENDS ${ORIGINAL_DISC} ${members} ${CMAKE_SOURCE_DIR}/tools/psx_disc.py
        ${CMAKE_SOURCE_DIR}/tools/afile.py
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    COMMENT "Extracting the game's data from ${ORIGINAL_DISC}"
    VERBATIM)
# Keep the extracted original members untouched and apply translations only to this copy.
set(translation_csvs
    ${CMAKE_SOURCE_DIR}/translations/messege0_translation_template.csv
    ${CMAKE_SOURCE_DIR}/translations/messege1_translation_template.csv
    ${CMAKE_SOURCE_DIR}/translations/messege2_translation_template.csv
    ${CMAKE_SOURCE_DIR}/translations/messege3_translation_template.csv
    ${CMAKE_SOURCE_DIR}/translations/messege4_translation_template.csv
)
add_custom_command(
    OUTPUT ${translation_stamp}
    COMMAND ${CMAKE_COMMAND} -E rm -rf ${translated_original}
    COMMAND ${CMAKE_COMMAND} -E copy_directory ${original}/A_FILE ${translated_original}
    COMMAND ${Python3_EXECUTABLE} tools/Modifikasi/translate_messages.py
        --all
        --bin-dir ${translated_original}
        --csv-dir ${CMAKE_SOURCE_DIR}/translations
        --output-dir ${translated_original}
        --report-json ${CMAKE_BINARY_DIR}/translations-report.json
    COMMAND ${CMAKE_COMMAND} -E touch ${translation_stamp}
    DEPENDS ${original}.stamp ${CMAKE_SOURCE_DIR}/tools/Modifikasi/translate_messages.py
        ${translation_csvs}
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    COMMENT "Applying Indonesian translations to messege0..messege4"
    VERBATIM)

# A_FILE: the overlays built here, the other members the original's.
file(STRINGS ${members} rows REGEX "^ *[0-9]+ +[^ ]+ +built ")
set(built)
foreach(row IN LISTS rows)
    string(REGEX MATCH "^ *[0-9]+ +([^ ]+)" _ ${row})
    list(APPEND built ${CMAKE_BINARY_DIR}/${CMAKE_MATCH_1})
endforeach()
add_custom_command(
    OUTPUT ${afile_bin} ${afile_hdt}
    COMMAND ${Python3_EXECUTABLE} tools/afile.py pack --members ${members}
        --original ${original}/A_FILE --built ${CMAKE_BINARY_DIR} --bin ${afile_bin} --hdt ${afile_hdt}
    DEPENDS ${original}.stamp ${members} ${built} ${CMAKE_SOURCE_DIR}/tools/afile.py
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    COMMENT "Packing A_FILE"
    VERBATIM)
add_custom_target(afile ALL DEPENDS ${afile_bin} ${afile_hdt})
add_dependencies(afile program)

# The disc: the original's layout and files, with the EXE and A_FILE built here.
add_custom_command(
    OUTPUT ${CMAKE_BINARY_DIR}/disc.bin ${CMAKE_BINARY_DIR}/disc.cue
    COMMAND ${Python3_EXECUTABLE} tools/psx_disc.py build ${layout} --files ${original}/disc
        --replace ${PSX_EXE}=${CMAKE_BINARY_DIR}/${PSX_EXE}
        --replace A_FILE.BIN=${afile_bin} --replace A_FILE.HDT=${afile_hdt}
        -o ${CMAKE_BINARY_DIR}/disc.bin --cue ${CMAKE_BINARY_DIR}/disc.cue
    DEPENDS ${layout} ${original}.stamp ${CMAKE_BINARY_DIR}/${PSX_EXE} ${afile_bin} ${afile_hdt}
        ${CMAKE_SOURCE_DIR}/tools/psx_disc.py
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    COMMENT "Building the disc image"
    VERBATIM)
add_custom_target(disc ALL DEPENDS ${CMAKE_BINARY_DIR}/disc.bin)
add_dependencies(disc afile program)
