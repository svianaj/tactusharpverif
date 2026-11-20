"""EcFlow suite definition for station-based HARP verification."""

import logging
from datetime import timedelta
from pathlib import Path

import tactus
from tactus.datetime_utils import as_datetime, as_julian, as_timedelta
from tactus.os_utils import tactusmakedirs
from tactus.suites.base import (
    EcflowSuiteFamily,
    EcflowSuiteTask,
    EcflowSuiteTrigger,
    EcflowSuiteTriggers,
    SuiteDefinition,
)

from ..methods import ConfigHarpverify

logger = logging.getLogger(__name__)


def _round_up_to_day(value):
    """Return midnight at the start of the next day unless already at midnight."""
    if value.hour == value.minute == value.second == value.microsecond == 0:
        return value
    return value.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


class TactusharpverifSuiteDefinition(SuiteDefinition):
    """Define the ordered link, verify, and archive stages."""

    def __init__(self, config, dry_run=False):
        SuiteDefinition.__init__(self, config, dry_run=dry_run)
        self.config = config
        self.config_verif = ConfigHarpverify(config)
        self.name = "Harp_point_verif"

        unix_group = self.platform.get_platform_value("unix_group")
        tactusmakedirs(self.joboutdir, unixgroup=unix_group)
        python_template = (
            Path(tactus.__path__[0]).resolve() / "templates/ecflow/default.py"
        ).as_posix()

        # Wait until the forecast has ended and observations are expected to be available.
        start_datetime = as_datetime(self.config_verif.start)
        forecast_range = as_timedelta(self.config_verif.forecast_range)
        delay = as_timedelta(config["submission.tactusharpverif_group.delay"])
        if delay < timedelta(0):
            raise ValueError("submission.tactusharpverif_group.delay must not be negative")
        end_date = _round_up_to_day(start_datetime + forecast_range)
        delay_date = _round_up_to_day(end_date + delay)
        delay_date_julian = as_julian(delay_date.strftime("%Y%m%d"))
        logger.info(
            "Verification suite will wait until %s (forecast ends %s)",
            delay_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
        )

        case_family = EcflowSuiteFamily(
            "Case_point_verification",
            self.suite,
            self.ecf_files,
        )

        # Stage 1: expose experiment and reference FCTABLES to HARP after the delay.
        linkobsfctables = EcflowSuiteTask(
            "LinkOBSFCTABLES",
            case_family,
            self.config,
            self.task_settings,
            self.ecf_files,
            input_template=python_template,
        )
        linkobsfctables.ecf_node.add_trigger(
            f"(:ECF_JULIAN ge {delay_date_julian})"
        )

        # Stage 2: run HARP after all forecast tables are linked successfully.
        verification_trigger = EcflowSuiteTriggers(
            EcflowSuiteTrigger(linkobsfctables)
        )
        if self.config_verif.parallel:
            verification_family = EcflowSuiteFamily(
                "Verification",
                case_family,
                self.ecf_files,
            )
            verification_tasks = []
            for index, parameter in enumerate(
                self.config_verif.surface_parameters
            ):
                family_name = (
                    f"{parameter}_plus_UA"
                    if index == 0 and self.config_verif.upper_air_parameters
                    else parameter
                )
                parameter_family = EcflowSuiteFamily(
                    family_name,
                    verification_family,
                    self.ecf_files,
                )
                verification_task = EcflowSuiteTask(
                    "Verification",
                    parameter_family,
                    self.config,
                    self.task_settings,
                    self.ecf_files,
                    input_template=python_template,
                    variables={
                        "TACTUS_TASK": "Verification",
                        "ARGS": f"parameter={parameter}",
                    },
                    trigger=verification_trigger,
                )
                verification_tasks.append(verification_task)
            verification_complete = verification_tasks
        else:
            verification_complete = EcflowSuiteTask(
                "Verification",
                case_family,
                self.config,
                self.task_settings,
                self.ecf_files,
                input_template=python_template,
                trigger=verification_trigger,
            )

        # Stage 3: archive only after verification completes successfully.
        EcflowSuiteTask(
            "Filesave",
            case_family,
            self.config,
            self.task_settings,
            self.ecf_files,
            input_template=python_template,
            trigger=(
                EcflowSuiteTriggers(
                    [
                        EcflowSuiteTrigger(task)
                        for task in verification_complete
                    ]
                )
                if isinstance(verification_complete, list)
                else EcflowSuiteTriggers(
                    EcflowSuiteTrigger(verification_complete)
                )
            ),
        )
