"""LinkOBSFCTABLES task.

Links the FCTABLE sqlite files of the experiment and of the reference models
into the common directory that harp uses as ``fcst_path``.

Resulting layout (non-operational indexing)::

    <VERIF_HOME>/FCTABLES/<case>/                  <- harp fcst_path
        <exp_model>/<YYYY>/<MM>/FCTABLE_*.sqlite   <- one symlink per file (experiment)
        <ref_model>                                <- symlink to the configured reference path
"""
import os
from datetime import datetime

from tactus.tasks.base import Task

from ..methods import ConfigHarpverify

try:
    from tactus.logs import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)


class LinkOBSFCTABLES(Task):
    """Link the FCTABLES of the experiment and of the references to VERIF_HOME."""

    def __init__(self, config):
        """Construct object.

        Args:
            config (tactus.ParsedConfig): Configuration

        """
        Task.__init__(self, config, __name__)
        self.config_verif = ConfigHarpverify(self.config)
        self.binary = "python3"

    @staticmethod
    def _link(source, destination):
        """Create the symlink ``destination -> source``.

        Existing correct links are kept, stale links (broken, or pointing
        somewhere else) are replaced, and real files/dirs are never touched.

        Returns:
            bool: True if a link was created or replaced.

        """
        if os.path.islink(destination):
            if os.path.exists(destination) and os.path.realpath(destination) == os.path.realpath(source):
                return False
            logger.info(f"Replacing stale link {destination}")
            os.remove(destination)
        elif os.path.exists(destination):
            raise FileExistsError(
                f"Cannot link {source} to {destination}: destination exists and is not a symlink"
            )
        os.symlink(source, destination)
        return True

    @staticmethod
    def _months(start, end):
        """Return the (YYYY, MM) pairs from the month of ``start`` to the month of ``end``.

        If ``end`` is not set, only the month of ``start`` is returned.
        """
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        first = datetime.strptime(start, fmt)
        last = datetime.strptime(end, fmt) if end else first
        if last < first:
            raise ValueError(f"general.times.end ({end}) is earlier than general.times.start ({start})")
        months = []
        year, month = first.year, first.month
        while (year, month) <= (last.year, last.month):
            months.append((f"{year:04d}", f"{month:02d}"))
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return months

    @staticmethod
    def _shift_month(path, ref_year, ref_month, year, month):
        """Replace the last ``/ref_year/ref_month`` component of ``path`` by ``/year/month``."""
        token = f"/{ref_year}/{ref_month}"
        idx = path.rfind(token)
        if idx < 0:
            raise ValueError(f"Cannot find '{token}' in experiment sqlite path {path}")
        return path[:idx] + f"/{year}/{month}" + path[idx + len(token):]

    def _link_experiment(self, source_dir, destination_dir):
        """Link each forecast month into the matching HARP year/month directory."""
        cfg = self.config_verif
        months = self._months(cfg.start, cfg.end)
        total_files = 0
        total_links = 0

        for year, month in months:
            month_source = (
                source_dir
                if (year, month) == (cfg.startyyyy, cfg.startmm)
                else self._shift_month(
                    source_dir, cfg.startyyyy, cfg.startmm, year, month
                )
            )
            if not os.path.isdir(month_source):
                raise FileNotFoundError(
                    f"Experiment FCTABLE directory not found: {month_source}. "
                    "Confirm ExtractSQLite completed and the run's scratch data is available."
                )

            names = sorted(
                name
                for name in os.listdir(month_source)
                if name.startswith("FCTABLE_") and name.endswith(".sqlite")
            )
            if not names:
                raise FileNotFoundError(
                    f"No FCTABLE_*.sqlite files found for {year}-{month} in {month_source}"
                )
            invalid_files = [
                name for name in names if not os.path.isfile(os.path.join(month_source, name))
            ]
            if invalid_files:
                raise FileNotFoundError(
                    f"Unreadable experiment FCTABLE files in {month_source}: {invalid_files}"
                )
            empty_files = [
                name for name in names if os.path.getsize(os.path.join(month_source, name)) == 0
            ]
            if empty_files:
                raise ValueError(
                    f"Empty experiment FCTABLE files in {month_source}: {empty_files}"
                )

            month_destination = os.path.join(destination_dir, year, month)
            os.makedirs(month_destination, exist_ok=True)
            created = sum(
                self._link(
                    os.path.join(month_source, name),
                    os.path.join(month_destination, name),
                )
                for name in names
            )
            total_files += len(names)
            total_links += created
            logger.info(
                f"Experiment FCTABLES for {year}-{month}: {len(names)} files, "
                f"{created} new or updated links"
            )
        logger.info(
            f"Linked {total_files} experiment FCTABLE files "
            f"({total_links} new or updated links)"
        )

    def _link_references(self, reference_root, destination_root):
        """Link the folder of each reference model into ``destination_root``."""
        missing = []
        for ref_model, source in reference_root.items():
            if not os.path.isdir(source):
                logger.error(f"FCTABLES for reference {ref_model} not found in {source}")
                missing.append(ref_model)
                continue
            has_fctables = any(
                os.path.basename(path).startswith("FCTABLE_")
                and path.endswith(".sqlite")
                and os.path.getsize(path) > 0
                for path in ConfigHarpverify.iter_files(source)
            )
            if not has_fctables:
                logger.error(
                    f"No non-empty FCTABLE_*.sqlite files found for reference "
                    f"{ref_model} in {source}"
                )
                missing.append(ref_model)
                continue
            created = self._link(source, os.path.join(destination_root, ref_model))
            status = "linked" if created else "link already in place"
            logger.info(f"Reference {ref_model}: {status}")
        if missing:
            raise FileNotFoundError(f"Missing or empty reference FCTABLES: {missing}")

    def execute(self):
        """Link experiment and reference FCTABLES to the harp fcst_path."""
        cfg = self.config_verif
        exp_source = cfg.sqlites_exp_path
        if "@" in exp_source:
            raise ValueError(f"Unresolved macro in experiment sqlite path: {exp_source}")

        # Must match verif.fcst_path in write_config_yml, and the fcst_model name used there
        local_fctables_root = os.path.join(cfg.home, "FCTABLES", cfg.case)
        local_fctables_exp = os.path.join(local_fctables_root, cfg.experiment_name)

        logger.info(f"Preparing experiment FCTABLES from {exp_source}")
        os.makedirs(local_fctables_root, exist_ok=True)

        self._link_experiment(exp_source, local_fctables_exp)
        self._link_references(cfg.ref_paths, local_fctables_root)
