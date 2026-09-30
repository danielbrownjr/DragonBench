#pragma once

// A DragonBench image is one board profile (CONFIG_DB_TARGET_NAME) plus one
// experiment profile, chosen by the mutually exclusive Kconfig choice
// DB_EXPERIMENT_PROFILE. Code that belongs to an experiment is compiled only
// under its DB_EXPERIMENT_* macro; baseline carries no fixture I/O at all.
//
// Adding a profile: add a choice entry in Kconfig.projbuild, a branch below,
// an sdkconfig.defaults.<name> overlay, and a CI build. See
// docs/EXPERIMENT_PROFILES.md.

#if defined(ESP_PLATFORM)
#include "sdkconfig.h"
#endif

#if defined(CONFIG_DB_EXPERIMENT_FAN_CHARACTERIZATION) && CONFIG_DB_EXPERIMENT_FAN_CHARACTERIZATION
#define DB_EXPERIMENT_FAN_CHARACTERIZATION 1
#define DB_EXPERIMENT_PROFILE_NAME "fan-characterization"
#else
#define DB_EXPERIMENT_FAN_CHARACTERIZATION 0
#define DB_EXPERIMENT_PROFILE_NAME "baseline"
#endif

#if defined(ESP_PLATFORM) && DB_EXPERIMENT_FAN_CHARACTERIZATION == 0 && !defined(CONFIG_DB_EXPERIMENT_BASELINE)
#error "Unknown DB_EXPERIMENT_PROFILE selection: add it to db_experiment.h"
#endif
