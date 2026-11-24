"""Configuration and filesystem helpers for the HARP verification tasks."""

import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta

import yaml
from tactus.toolbox import Platform

logger = logging.getLogger(__name__)


def _raise_walk_error(error):
    """Make os.walk permission and I/O failures visible to the task."""
    raise error


class ConfigHarpverify:
    """Resolve and validate the Tactus and plugin settings used by a run."""

    def __init__(self, config):
        self.config = config
        self.platform = Platform(config)

        self.home = self._configured_path(
            "submission.tactusharpverif_group.ENV.VERIF_HOME"
        )
        self.obstables_path = self._configured_path(
            "submission.tactusharpverif_group.ENV.OBSTABLES_PATH"
        )
        self.harpscripts_home = self._configured_path(
            "submission.tactusharpverif_group.ENV.HARPSCRIPTS_HOME"
        )
        self.use_renv = self._boolean_setting(
            "submission.tactusharpverif_group.use_Renv"
        )
        if self.use_renv:
            self.Renv_conf = self._configured_path(
                "submission.tactusharpverif_group.ENV.Renv_conf"
            )
        else:
            self.R_module_load = self._required_setting(
                "submission.tactusharpverif_group.ENV.R_module_load"
            )
            if not isinstance(self.R_module_load, str) or not self.R_module_load.strip():
                raise ValueError(
                    "submission.tactusharpverif_group.ENV.R_module_load "
                    "must be a non-empty shell command"
                )
        self.obs_step = self._positive_integer_setting(
            "submission.tactusharpverif_group.ENV.OBS_STEP"
        )
        self.surface_parameters = self._parameters_setting(
            "submission.tactusharpverif_group.PARAMETERS_SFC"
        )
        self.upper_air_parameters = self._parameters_setting(
            "submission.tactusharpverif_group.PARAMETERS_UA",
            allow_empty=True,
        )
        overlap = set(self.surface_parameters) & set(self.upper_air_parameters)
        if overlap:
            raise ValueError(
                "PARAMETERS_SFC and PARAMETERS_UA must not overlap: "
                + ", ".join(sorted(overlap))
            )
        upper_air_names = {"Z", "T", "Q", "D", "S", "RH"}
        invalid_upper_air = [
            parameter
            for parameter in self.upper_air_parameters
            if parameter not in upper_air_names
        ]
        misclassified_surface = [
            parameter
            for parameter in self.surface_parameters
            if parameter in upper_air_names
        ]
        if invalid_upper_air or misclassified_surface:
            raise ValueError(
                "Upper-air parameters must be configured in PARAMETERS_UA and "
                "surface parameters in PARAMETERS_SFC; "
                f"invalid UA entries: {invalid_upper_air}; "
                f"UA entries in SFC: {misclassified_surface}"
            )
        self.parameters = self.surface_parameters + self.upper_air_parameters
        self.parallel = self._boolean_setting(
            "submission.tactusharpverif_group.PARALLEL"
        )

        self.case = self.config["general.case"]
        if (
            not isinstance(self.case, str)
            or not self.case
            or self.case in {".", ".."}
            or os.path.basename(self.case) != self.case
        ):
            raise ValueError(f"Invalid verification case name: {self.case!r}")

        self.start = self._required_setting("general.times.start")
        start_datetime = self._parse_datetime(self.start, "general.times.start")
        self.forecast_range = self._required_setting("general.times.forecast_range")
        self.forecast_range_nr = self._duration_to_hours(self.forecast_range)
        if self.forecast_range_nr < 0:
            raise ValueError("general.times.forecast_range must not be negative")
        if self.forecast_range_nr % self.obs_step:
            raise ValueError(
                "general.times.forecast_range must be divisible by OBS_STEP so the "
                "generated HARP lead-time sequence reaches the forecast end"
            )

        end_datetime = start_datetime + timedelta(hours=self.forecast_range_nr)
        self.end = end_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.startyyyymmddhh = start_datetime.strftime("%Y%m%d%H")
        self.endyyyymmddhh = end_datetime.strftime("%Y%m%d%H")
        self.startyyyy = start_datetime.strftime("%Y")
        self.startmm = start_datetime.strftime("%m")
        self.startdd = start_datetime.strftime("%d")

        members = self.platform.get_value("eps.general.members")
        if members is None:
            members = []
        if not isinstance(members, (list, tuple)):
            raise ValueError("eps.general.members must be a list when set")
        self.eps = len(members) > 1

        self.experiment_name = self._required_setting("extractsqlite.sqlite_model_name")
        if (
            not isinstance(self.experiment_name, str)
            or not self.experiment_name
            or self.experiment_name in {".", ".."}
            or os.path.basename(self.experiment_name) != self.experiment_name
        ):
            raise ValueError(f"Invalid experiment model name: {self.experiment_name!r}")
        sqlite_setting = (
            "extractsqlite.merged_sqlite_path"
            if self.eps
            else "extractsqlite.sqlite_path"
        )
        self.sqlites_exp_path = self._required_setting(sqlite_setting)
        if not isinstance(self.sqlites_exp_path, str):
            raise ValueError(f"{sqlite_setting} must be a filesystem path")

        reference_names = self._required_setting(
            "submission.tactusharpverif_group.ENV.REFERENCE_MODEL_NAMES"
        )
        if not isinstance(reference_names, (list, tuple)) or not reference_names:
            raise ValueError("REFERENCE_MODEL_NAMES must be a non-empty list")
        if any(
            not isinstance(name, str)
            or not name
            or name in {".", ".."}
            or os.path.basename(name) != name
            for name in reference_names
        ):
            raise ValueError("Reference model names must be simple, non-empty names")
        if len(set(reference_names)) != len(reference_names):
            raise ValueError("REFERENCE_MODEL_NAMES must not contain duplicates")
        selected_references = [
            name
            for name in reference_names
            if ("ENS" in name.upper()) == self.eps
        ]
        if not selected_references:
            run_type = "ensemble" if self.eps else "deterministic"
            raise ValueError(f"No {run_type} reference models are configured")
        self.ref_name = selected_references
        self.ref_paths = self._reference_paths(reference_names, selected_references)

        self.rdss_path = "RDSs"
        self.pngs_path = "PNGs"
        self.plugin_path = self._configured_path(
            "general.plugin_registry.plugins.tactusharpverif"
        )
        self.tactusverify_path = os.path.join(self.plugin_path, "tactusharpverif")
        self.ecfs_archive_relpath_harpoutput = self._required_setting(
            "submission.tactusharpverif_group.ENV.ECFS_ARCHIVE_RELPATH_HARPOUTPUT"
        )
        self.set_params = os.path.join(
            self.tactusverify_path,
            "templates",
            "set_params_eps.R" if self.eps else "set_params_det.R",
        )
        self._validate_parameters_in_set_params()

        self.config_yaml_filename = os.path.join(
            self.home,
            "config_files",
            self.startyyyy,
            self.startmm,
            self.startdd,
            f"tactus_conf_{self.case}.yml",
        )

    def _required_setting(self, key):
        """Return a required Tactus setting with a useful error on empty values."""
        value = self.platform.get_value(key)
        if value is None or value == "":
            raise ValueError(f"Required configuration setting is missing: {key}")
        return value

    def _configured_path(self, key):
        value = self._required_setting(key)
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a filesystem path; got {value!r}")
        return os.path.abspath(os.path.expanduser(value))

    def _positive_integer_setting(self, key):
        value = self._required_setting(key)
        if isinstance(value, bool):
            raise ValueError(f"{key} must be a positive integer; got {value!r}")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{key} must be a positive integer; got {value!r}") from error
        if parsed <= 0:
            raise ValueError(f"{key} must be a positive integer; got {value!r}")
        return parsed

    def _parameters_setting(self, key, allow_empty=False):
        value = self._required_setting(key)
        if (
            not isinstance(value, (list, tuple))
            or (not value and not allow_empty)
        ):
            expected = "a list" if allow_empty else "a non-empty list"
            raise ValueError(f"{key} must be {expected}")
        if any(
            not isinstance(parameter, str)
            or not parameter
            or "," in parameter
            or any(character.isspace() for character in parameter)
            for parameter in value
        ):
            raise ValueError(
                f"{key} entries must be non-empty parameter names without commas or whitespace"
            )
        if len(set(value)) != len(value):
            raise ValueError(f"{key} must not contain duplicates")
        return list(value)

    def parameters_for_task(self, parameter=None):
        """Return parameters for one task or the complete serial run."""
        if parameter is None:
            if not self.surface_parameters:
                raise ValueError(
                    "At least one surface parameter is required to verify upper-air parameters"
                )
            return (
                self.surface_parameters[:1]
                + self.upper_air_parameters
                + self.surface_parameters[1:]
            )
        if parameter not in self.surface_parameters:
            raise ValueError(
                f"Verification task parameter {parameter!r} is not configured "
                "in PARAMETERS_SFC"
            )
        if parameter == self.surface_parameters[0]:
            return [parameter, *self.upper_air_parameters]
        return [parameter]

    def _boolean_setting(self, key):
        value = self._required_setting(key)
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false; got {value!r}")
        return value

    def _validate_parameters_in_set_params(self):
        if not os.path.isfile(self.set_params):
            raise FileNotFoundError(
                f"HARP parameter scaling file not found: {self.set_params}"
            )

        try:
            with open(self.set_params, "r", encoding="utf-8") as parameter_file:
                contents = parameter_file.read()
        except OSError as error:
            raise OSError(
                f"Could not read HARP parameter scaling file: {self.set_params}"
            ) from error

        configured = set(
            re.findall(r"(?m)^    ([A-Za-z][A-Za-z0-9_]*)\s*=\s*list\(", contents)
        )
        missing = [parameter for parameter in self.parameters if parameter not in configured]
        if missing:
            verification_type = "ensemble" if self.eps else "deterministic"
            raise ValueError(
                f"Configured verification parameters missing from "
                f"{os.path.basename(self.set_params)} "
                f"for {verification_type} verification: {', '.join(missing)}"
            )

    @staticmethod
    def _parse_datetime(value, setting):
        try:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"{setting} must use the UTC format YYYY-MM-DDTHH:MM:SSZ; got {value!r}"
            ) from error

    @staticmethod
    def _duration_to_hours(value):
        """Convert an ISO day/hour duration to whole hours."""
        if not isinstance(value, str):
            raise ValueError(f"Forecast duration must be a string; got {value!r}")
        match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?)?", value)
        if (
            not match
            or not any(match.groups())
            or value.endswith("T")
        ):
            raise ValueError(
                "Forecast duration must contain whole days and/or hours; "
                f"got {value!r}"
            )
        days, hours = (int(part or 0) for part in match.groups())
        return days * 24 + hours

    def _reference_paths(self, all_reference_names, selected_reference_names):
        """Map configured reference names to their source FCTABLES directories."""
        paths = self.platform.get_value(
            "submission.tactusharpverif_group.ENV.REFERENCE_MODEL_PATHS"
        )
        if not paths:
            paths = [
                self._required_setting(
                    "submission.tactusharpverif_group.ENV.REF_SQLITES"
                )
            ]
        if not isinstance(paths, (list, tuple)) or len(paths) not in (
            1,
            len(all_reference_names),
        ):
            raise ValueError(
                "REFERENCE_MODEL_PATHS must contain one shared root or one root per "
                "configured reference model"
            )

        reference_paths = {}
        for index, name in enumerate(all_reference_names):
            if name not in selected_reference_names:
                continue
            root = paths[0] if len(paths) == 1 else paths[index]
            if not isinstance(root, str) or not root:
                raise ValueError(f"Invalid reference path for {name}: {root!r}")
            root = os.path.abspath(os.path.expanduser(root))
            reference_paths[name] = (
                root if os.path.basename(os.path.normpath(root)) == name
                else os.path.join(root, name)
            )
        return reference_paths

    @staticmethod
    def iter_files(directory):
        """Yield files recursively and propagate traversal errors."""
        for root, _, filenames in os.walk(directory, onerror=_raise_walk_error):
            for filename in filenames:
                yield os.path.join(root, filename)

    def write_config_yml(self, write=True):
        """Load the selected HARP template and populate this run's paths and dates."""
        template_name = "tactus_conf_eps.yml" if self.eps else "tactus_conf_det.yml"
        config_template = os.path.join(self.tactusverify_path, "templates", template_name)
        if not os.path.isfile(config_template):
            raise FileNotFoundError(f"HARP configuration template not found: {config_template}")

        with open(config_template, encoding="utf-8") as stream:
            exp_args = yaml.safe_load(stream)
        if not isinstance(exp_args, dict) or not all(
            isinstance(exp_args.get(section), dict)
            for section in ("verif", "post", "scorecards")
        ):
            raise ValueError(f"Invalid HARP configuration template: {config_template}")

        # HARP consumes model lists in reference-first order, with the experiment last.
        exp_args["verif"]["fcst_model"] = list(self.ref_name) + [self.experiment_name]
        exp_args["verif"]["project_name"] = [self.case]
        exp_args["verif"]["lead_time"] = (
            f"seq(0,{self.forecast_range_nr},{self.obs_step})"
        )
        exp_args["verif"]["obs_path"] = [self.obstables_path]
        exp_args["verif"]["verif_path"] = [
            os.path.join(self.home, self.case, self.rdss_path)
        ]
        exp_args["post"]["plot_output"] = [
            os.path.join(self.home, self.case, self.pngs_path)
        ]
        exp_args["verif"]["fcst_path"] = [
            os.path.join(self.home, "FCTABLES", self.case)
        ]
        exp_args["scorecards"]["ref_model"] = [self.ref_name[0]]
        exp_args["scorecards"]["fcst_model"] = [self.experiment_name]
        if write:
            self.save_yaml(self.config_yaml_filename, exp_args)
            logger.info("Wrote HARP configuration to %s", self.config_yaml_filename)
        return self.config_yaml_filename, exp_args

    @staticmethod
    def save_yaml(config_file, data):
        """Atomically write a YAML file so consumers never see a partial config."""
        config_dir = os.path.dirname(config_file) or "."
        os.makedirs(config_dir, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=config_dir,
                prefix=".tactus_conf_",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_path = stream.name
                yaml.safe_dump(data, stream, default_flow_style=False, sort_keys=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, config_file)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.remove(temporary_path)

    @staticmethod
    def replicate_structure_to_ec(origin_path, ec_base_path):
        """Copy a non-empty local directory tree to ECFS, failing on any command error."""
        if not os.path.isdir(origin_path):
            raise FileNotFoundError(f"Local archive source directory not found: {origin_path}")

        copied_files = 0
        for dirpath, dirnames, filenames in os.walk(
            origin_path, onerror=_raise_walk_error
        ):
            dirnames.sort()
            filenames.sort()
            rel_dir = os.path.relpath(dirpath, origin_path)
            ec_target_dir = (
                ec_base_path if rel_dir == "." else os.path.join(ec_base_path, rel_dir)
            )
            ec_target_dir = ec_target_dir.replace("\\", "/")

            check = subprocess.run(
                ["els", ec_target_dir],
                capture_output=True,
                text=True,
                check=False,
            )
            if check.returncode == 1:
                subprocess.run(["emkdir", "-p", ec_target_dir], check=True)
                logger.info("Created ECFS directory %s", ec_target_dir)
            elif check.returncode != 0:
                raise subprocess.CalledProcessError(
                    check.returncode, check.args, check.stdout, check.stderr
                )

            for filename in filenames:
                local_file = os.path.join(dirpath, filename)
                ec_target_file = os.path.join(ec_target_dir, filename).replace("\\", "/")
                subprocess.run(["ecp", local_file, ec_target_file], check=True)
                copied_files += 1
                logger.debug("Copied %s to %s", local_file, ec_target_file)

        if copied_files == 0:
            raise FileNotFoundError(f"No files found to archive under {origin_path}")
        logger.info(
            "Archived %d files from %s to %s",
            copied_files,
            origin_path,
            ec_base_path,
        )
