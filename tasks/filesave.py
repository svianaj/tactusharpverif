"""Archive completed HARP results to ECFS."""

import logging
import os
import posixpath

from tactus.tasks.base import Task

from ..methods import ConfigHarpverify

logger = logging.getLogger(__name__)


class Filesave(Task):
    """Copy verification results and plots to the configured ECFS archive."""

    def __init__(self, config):
        Task.__init__(self, config, __name__)
        self.config_verif = ConfigHarpverify(self.config)
        self.binary = "python3"

    @staticmethod
    def _has_output_files(path, description):
        if not os.path.isdir(path):
            logger.warning("%s directory not found; skipping archive: %s", description, path)
            return False
        if any(
            os.path.getsize(filename) > 0
            for filename in ConfigHarpverify.iter_files(path)
        ):
            return True
        logger.warning("No %s files were produced under %s; skipping archive", description, path)
        return False

    def execute(self):
        cfg = self.config_verif
        _, exp_args = cfg.write_config_yml(write=False)

        # HARP places each project's results beneath the configured output root.
        rds_source = os.path.join(exp_args["verif"]["verif_path"][0], cfg.case)
        plot_source = os.path.join(exp_args["post"]["plot_output"][0], cfg.case)
        if not self._has_output_files(rds_source, "verification result"):
            return

        configured_archive_root = cfg.ecfs_archive_relpath_harpoutput
        if not isinstance(configured_archive_root, str):
            raise ValueError(
                "ECFS_ARCHIVE_RELPATH_HARPOUTPUT must be a non-empty relative path "
                "without '.' or '..' components"
            )
        configured_archive_root = configured_archive_root.strip()
        if (
            not configured_archive_root
            or configured_archive_root.startswith("/")
            or "\\" in configured_archive_root
        ):
            raise ValueError(
                "ECFS_ARCHIVE_RELPATH_HARPOUTPUT must be a non-empty relative path "
                "without '.' or '..' components"
            )
        archive_parts = configured_archive_root.rstrip("/").split("/")
        if any(part in {"", ".", ".."} for part in archive_parts):
            raise ValueError(
                "ECFS_ARCHIVE_RELPATH_HARPOUTPUT must not contain empty, '.' or '..' components"
            )
        archive_root = posixpath.join(*archive_parts)
        archive_root = posixpath.join(archive_root, cfg.case)

        rds_destination = "ec:" + posixpath.join(archive_root, cfg.rdss_path)
        logger.info("Archiving verification results: %s -> %s", rds_source, rds_destination)
        cfg.replicate_structure_to_ec(rds_source, rds_destination)

        if exp_args["post"].get("create_png", False):
            if self._has_output_files(plot_source, "verification plot"):
                plot_destination = "ec:" + posixpath.join(archive_root, cfg.pngs_path)
                logger.info("Archiving verification plots: %s -> %s", plot_source, plot_destination)
                cfg.replicate_structure_to_ec(plot_source, plot_destination)
        else:
            logger.info("Plot generation is disabled; skipping plot archive")
