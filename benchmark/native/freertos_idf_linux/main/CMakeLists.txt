idf_component_register(SRCS "main.c" INCLUDE_DIRS "." "${EUNO_COMMON}" REQUIRES freertos)
target_link_options(${COMPONENT_LIB} INTERFACE -Wl,--wrap=main)
