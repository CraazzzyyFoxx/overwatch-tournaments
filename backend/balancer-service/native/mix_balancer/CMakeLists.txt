cmake_minimum_required(VERSION 3.12)
project(mix_balancer LANGUAGES CXX)

# Set C++ standard
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find Python
find_package(Python 3.10 REQUIRED COMPONENTS Interpreter Development)

# Add pybind11
find_package(pybind11 CONFIG REQUIRED)

# Source files
set(SOURCES
    mix_balancer.cpp
    pybind11_bindings.cpp
)

# Create the extension module with underscore prefix for internal use
pybind11_add_module(_core MODULE ${SOURCES})

# For scikit-build-core, tell it to install in the mix_balancer package
install(TARGETS _core DESTINATION mix_balancer)

# Install the __init__.py file
install(FILES mix_balancer/__init__.py DESTINATION mix_balancer)

# Link Python libraries
target_link_libraries(_core PRIVATE Python::Python)

# Explicit libstdc++: on some toolchains CMake resolves CMAKE_CXX_COMPILER to
# the `gcc` driver (it happily compiles .cpp files, given -std=gnu++XX) rather
# than `g++`/`c++` -- `gcc` compiles C++ fine but, unlike `g++`, does NOT
# automatically add `-lstdc++` at link time. The link step then succeeds
# (shared libraries are allowed undefined symbols), but the module fails to
# *import*: "undefined symbol: _ZTVN10__cxxabiv117__class_type_infoE" (a C++
# RTTI vtable symbol), because `_core.so`'s NEEDED list never got
# `libstdc++.so`. Linking it explicitly is correct regardless of which
# driver ended up doing the link.
if(NOT MSVC)
    target_link_libraries(_core PRIVATE stdc++)
endif()

# The ISA this module is allowed to use. NOT ``native``: the release images are
# built on a GitHub runner and run on whatever the production host is, and those
# are different machines. ``-march=native`` on an AVX-512 Ice Lake runner emitted
# EVEX ``vmovdqu64 %zmm0`` into ``_core.so``; importing it on the production AMD
# EPYC-Rome (Zen 2, no AVX-512) raised SIGILL, which killed the whole worker the
# first time a mix was balanced and took every balancer RPC down with it.
#
# ``x86-64-v2`` (SSE4.2 + POPCNT, everything since 2009) is the floor that still
# gives the search's hot loop a hardware popcount for its bit iteration. Override
# for a machine-specific build: ``-DMIX_BALANCER_ARCH=native``.
set(MIX_BALANCER_ARCH "x86-64-v2" CACHE STRING "-march= value for the search kernel")

# Set compile flags for optimization
if(MSVC)
    target_compile_options(_core PRIVATE /O2 /Oi /Ot /GL)
else()
    target_compile_options(_core PRIVATE -O3 -march=${MIX_BALANCER_ARCH})
endif()

# NOTE: LTO deliberately NOT enabled. Upstream had it on twice over (a
# manual -flto compile flag here *and* CMAKE_INTERPROCEDURAL_OPTIMIZATION in
# pyproject.toml, which injects its own -flto=auto -fno-fat-lto-objects) --
# removed as a precaution against LTO-related link fragility, though the
# undefined-RTTI-symbol failure above turned out to have a separate root
# cause (missing -lstdc++, fixed above). -O3 alone already covers the
# overwhelming majority of the available speedup for a search this small;
# not worth LTO's fragility on top.

# For scikit-build, don't set custom output directory
# It will handle the installation automatically
