"""Run point verification with the configured HARP installation."""

import logging
import os
import shlex

from tactus.tasks.base import Task
from tactus.tasks.batch import BatchJob

from ..methods import ConfigHarpverify

logger = logging.getLogger(__name__)


class Verification(Task):
    """Generate the HARP run configuration and execute point verification."""

    def __init__(self, config):
        Task.__init__(self, config, __name__)
        self.config_verif = ConfigHarpverify(self.config)
        self.binary = "python3"
        self.batch = BatchJob(os.environ)

    @staticmethod
    def _snapshot_files(directory):
        """Record output file size and modification time to detect stale results."""
        snapshot = {}
        for path in ConfigHarpverify.iter_files(directory):
            stat = os.stat(path)
            snapshot[path] = (stat.st_size, stat.st_mtime_ns)
        return snapshot

    @staticmethod
    def _has_new_or_updated_files(before, after):
        return any(
            details[0] > 0 and (path not in before or before[path] != details)
            for path, details in after.items()
        )

    @staticmethod
    def _harp_command(cfg, harp_script, config_yaml_filename, parameters):
        return (
            "Rscript"
            f" {shlex.quote(harp_script)}"
            f" -config_file {shlex.quote(config_yaml_filename)}"
            f" -start_date {shlex.quote(cfg.startyyyymmddhh)}"
            f" -end_date {shlex.quote(cfg.endyyyymmddhh)}"
            f" -params_list={shlex.quote(parameters)}"
            f" -params_file {shlex.quote(cfg.set_params)}"
        )

    def execute(self):
        cfg = self.config_verif
        parameter = self.config.get("task.args.parameter")
        if parameter is not None:
            if parameter not in cfg.parameters:
                raise ValueError(
                    f"Verification task parameter {parameter!r} is not configured "
                    "in submission.tactusharpverif_group.PARAMETERS"
                )
            parameters = parameter
        else:
            parameters = ",".join(cfg.parameters)
        logger.info(
            "Starting HARP point verification for %s (%s through %s)",
            cfg.case,
            cfg.startyyyymmddhh,
            cfg.endyyyymmddhh,
        )

        config_yaml_filename, exp_args = cfg.write_config_yml()
        if not exp_args:
            raise RuntimeError("HARP configuration generation returned no configuration")

        harp_script = os.path.join(cfg.harpscripts_home, "verification", "point_verif.R")
        for path, description, is_directory in (
            (cfg.harpscripts_home, "HARP scripts directory", True),
            (harp_script, "HARP point verification script", False),
            (cfg.Renv_conf, "R environment activation script", False),
            (cfg.set_params, "HARP parameter scaling file", False),
            (cfg.obstables_path, "observation tables directory", True),
        ):
            exists = os.path.isdir(path) if is_directory else os.path.isfile(path)
            if not exists:
                raise FileNotFoundError(f"{description} not found: {path}")
        if not any(ConfigHarpverify.iter_files(cfg.obstables_path)):
            raise FileNotFoundError(
                f"No observation table files found under {cfg.obstables_path}"
            )

        output_paths = (
            *exp_args["verif"]["verif_path"],
            *exp_args["post"]["plot_output"],
        )
        for path in output_paths:
            os.makedirs(path, exist_ok=True)
            logger.info("Output directory ready: %s", path)
        rds_path = exp_args["verif"]["verif_path"][0]
        plot_path = exp_args["post"]["plot_output"][0]
        rds_before = self._snapshot_files(rds_path)
        create_png = bool(exp_args["post"].get("create_png", False))
        png_before = self._snapshot_files(plot_path) if create_png else {}

        activation = f"source {shlex.quote(cfg.Renv_conf)}"
        harp_command = self._harp_command(
            cfg, harp_script, config_yaml_filename, parameters
        )
        command = " && ".join((activation, harp_command))
        logger.info("Submitting HARP point verification for %s", parameters)

        logger.info("Using HARP point-verification script %s", harp_script)
        os.chdir(cfg.harpscripts_home)
        self.batch.run(command)
        rds_after = self._snapshot_files(rds_path)
        if not self._has_new_or_updated_files(rds_before, rds_after):
            raise RuntimeError(
                f"HARP completed without creating or updating RDS output under {rds_path}"
            )
        if create_png:
            png_after = self._snapshot_files(plot_path)
            if not self._has_new_or_updated_files(png_before, png_after):
                raise RuntimeError(
                    f"HARP completed without creating or updating plot output under {plot_path}"
                )
        logger.info("HARP point verification completed for %s", cfg.case)
