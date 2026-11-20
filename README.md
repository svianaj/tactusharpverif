# Tactusharpverif

A Tactus plugin that builds an ecFlow suite to verify a forecast against station
observations and configured reference models using the HARP point-verification
scripts.

The suite runs three ordered tasks:

1. **LinkOBSFCTABLES** waits until the configured post-forecast delay has passed,
   then validates and links experiment and reference FCTABLES into `VERIF_HOME`.
   Forecasts that cross a month boundary are linked month by month.
2. **Verification** writes a run-specific HARP YAML configuration, activates the
   configured R environment, and runs `point_verif.R` for the full forecast
   period.
3. **Filesave** checks that the expected RDS results (and PNGs, when enabled)
   exist, then copies them to ECFS.

An error in configuration, input discovery, environment activation, HARP, or
archiving fails the corresponding task rather than being treated as success.

## Prerequisites

1. Install the operational HARP scripts from
   [oper-harp-verif](https://github.com/harphub/oper-harp-verif).
2. Install the R packages required by those scripts. An isolated `renv`
   installation can be created with `renv_harp/isolated_install.sh`; the
   generated `Setenv` script is then referenced by the plugin configuration.
   Alternatively, install HARP (version 0.2.2 or newer) and the extra packages
   used by the operational scripts, including `here`, `argparse`, `pracma`,
   `pals`, `shinyWidgets`, `cowplot`, `scico`, and `sf`.
3. Configure the plugin settings in
   [`tactusharpverif_plugin.toml`](./tactusharpverif_plugin.toml). In particular:
   - `HARPSCRIPTS_HOME` must contain `verification/point_verif.R`.
   - `VERIF_HOME` must be writable by the Tactus task user.
   - `OBSTABLES_PATH` must point to the observation tables.
   - `REFERENCE_MODEL_NAMES` determines which references are used. Names
     containing `ENS` are selected for ensemble runs; other names are selected
     for deterministic runs. At least one suitable reference is required.
   - `REFERENCE_MODEL_PATHS` accepts one shared parent directory or one parent
     per configured reference name. Each parent contains that model's FCTABLES
     directory, unless the parent itself is already named after the model.
   - `OBS_STEP` must be a positive whole-hour interval, and the forecast range
     must be divisible by it so the generated lead-time sequence reaches the
     forecast end.
   - `PARAMETERS` in `[submission.tactusharpverif_group]` must be a non-empty
     list of HARP parameter names to verify. Every name must be present as a
     top-level entry in `set_params_det.R` for deterministic runs or
     `set_params_eps.R` for ensemble runs.
   - `PARALLEL` controls execution mode. The default `false` runs all parameters
     in one HARP process. `true` launches one HARP process per configured
     parameter and waits for every process to finish. Parallel processes share
     observation and forecast inputs as read-only inputs, but write RDS and PNG
     outputs to the configured shared directories. It can therefore increase
     memory, CPU, and filesystem I/O usage. Keep it disabled unless the selected
     HARP scripts and shared output layout have been verified to support
     concurrent parameter runs.
   - `Renv_conf` must point to a readable shell script that activates the
     required R environment.
   - `ECFS_ARCHIVE_RELPATH_HARPOUTPUT` must be a relative ECFS path without
     `..` components.

## Prepare and launch a verification

Use the expanded configuration of the Tactus experiment so that the original
SQLite paths are retained when the verification case is created.

1. Expand the experiment configuration (for example,
   `my_second_test_develop.toml`) using an `expand_for_verif.toml` containing:

   ```toml
   [macros]

   [macros.case]
   gen_macros = [
     "general.csc",
     "general.case",
     "platform.archive_root",
     { sqlite_path = "extractsqlite.sqlite_path" },
     { sqlite_path = "extractsqlite.sqlite_path" },
     { merged_sqlite_path = "extractsqlite.merged_sqlite_path" },
     { sqlite_model_name = "extractsqlite.sqlite_model_name" }
   ]
   group_macros = ["system"]
   os_macros = ["USER"]
   ```

   ```sh
   tactus case --config-file my_second_test_develop.toml expand_for_verif.toml \
     --expand-config --o my_second_test_develop_expanded_from_config.toml
   ```

2. Launch the verification using both the expanded experiment configuration and
   the plugin configuration:

   ```sh
   tactus case ?configure_verif --case-name my_first_tactusverif_from_expanded_config \
     --start-suite
   ```

   Supply these config files to the command:

   ```text
   --config-file
   /path/to/my_second_test_develop_expanded_from_config.toml
   /path/to/tactusharpverif_plugin.toml
   ```

The suite uses `general.times.start` plus `general.times.forecast_range` for the
verification date bounds and rounds the forecast end and configured delay up to
the next midnight for its ecFlow start trigger. Ensure the plugin's Tactus
version is compatible with the one used to run the experiment.

## References and output

Reference FCTABLES must be present in the configured model directories before
the linking task starts. The task checks that each selected reference contains
FCTABLE SQLite files and fails if a configured reference is missing or empty.

HARP RDS output and optional plots are written under `VERIF_HOME/<case>/RDSs`
and `VERIF_HOME/<case>/PNGs`; the corresponding `config_files` directory holds
the generated HARP YAML. Filesave copies results to the ECFS path configured by
`ECFS_ARCHIVE_RELPATH_HARPOUTPUT`.

For variables whose units differ between the experiment and references, review
the scaling settings in the selected `set_params_det.R` or `set_params_eps.R`
file. The corresponding operational scaling file is maintained in the HARP
scripts installation under `verification/set_params.R`.
