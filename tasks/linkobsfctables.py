"""LinkOBSFCTABLES task.

Links the FCTABLE sqlite files of the experiment and of the reference models
into the common directory that harp uses as ``fcst_path``.

Resulting layout (non-operational indexing)::

    <VERIF_HOME>/FCTABLES/<case>/                  <- harp fcst_path
        <exp_model>/<YYYY>/<MM>/FCTABLE_*.sqlite   <- one symlink per file (experiment)
        <ref_model>                                <- symlink to <REF_SQLITES>/<ref_model>
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

    # ------------------------------------------------------------------ helpers
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
            logger.warning(f"{destination} exists and is not a symlink, skipping")
            return False
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
        """Link every FCTABLE sqlite file of ``source_dir`` into ``destination_dir``."""
        if not os.path.isdir(source_dir):
            raise FileNotFoundError(
                f"Experiment FCTABLE directory not found: {source_dir}. "
                "Has ExtractSQLite run, and is the data still in the scratch of the TACTUS user?"
            )
        files = sorted(f for f in os.listdir(source_dir) if f.startswith("FCTABLE_") and f.endswith(".sqlite"))
        if not files:
            raise FileNotFoundError(f"No FCTABLE_*.sqlite files found in {source_dir}")

        os.makedirs(destination_dir, exist_ok=True)
        n_new = sum(self._link(os.path.join(source_dir, f), os.path.join(destination_dir, f)) for f in files)
        logger.info(f"Experiment FCTABLES: {len(files)} files, {n_new} new/updated links in {destination_dir}")

    def _link_references(self, reference_root, destination_root):
        """Link the folder of each reference model into ``destination_root``."""
        missing = []
        for ref_model in self.config_verif.ref_name:
            source = os.path.join(reference_root, ref_model)
            if not os.path.isdir(source):
                logger.error(f"FCTABLES for reference {ref_model} not found in {source}")
                missing.append(ref_model)
                continue
            created = self._link(source, os.path.join(destination_root, ref_model))
            logger.info(f"Reference {ref_model}: {'linked' if created else 'link already in place'}")
        if missing:
            raise FileNotFoundError(f"Missing reference FCTABLES: {missing} (looked in {reference_root})")

    # ------------------------------------------------------------------ task
    def execute(self):
        """Link experiment and reference FCTABLES to the harp fcst_path."""
        cfg = self.config_verif
        exp_source = cfg.sqlites_exp_path
        if "@" in exp_source:
            raise ValueError(f"Unresolved macro in experiment sqlite path: {exp_source}")

        # Must match verif.fcst_path in write_config_yml, and the fcst_model name used there
        local_fctables_root = os.path.join(cfg.home, "FCTABLES", cfg.case)
        local_fctables_exp = os.path.join(local_fctables_root, cfg.experiment_name, cfg.startyyyy, cfg.startmm)

        logger.info(f"Experiment FCTABLES: {exp_source} -> {local_fctables_exp}")
        os.makedirs(local_fctables_root, exist_ok=True)

        self._link_experiment(exp_source, local_fctables_exp)
        self._link_references(cfg.sqlites_ref_path, local_fctables_root)
