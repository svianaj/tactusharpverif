"""Ecflow suites."""
from pathlib import Path
from ecflow import Trigger
import tactus
from tactus.os_utils import tactusmakedirs
from tactus.datetime_utils import as_datetime, as_timedelta, as_julian
from tactus.suites.base import (
    EcflowSuiteFamily,
    EcflowSuiteTask,
    EcflowSuiteTrigger,
    EcflowSuiteTriggers,
    SuiteDefinition,
)
import pandas as pd
from datetime import datetime, timezone, time

from ..methods import ConfigHarpverify 


class TactusharpverifSuiteDefinition(SuiteDefinition):
    """Definition of suite."""

    def __init__(
        self,
        config,
        dry_run=False,
    ):
        """Construct the definition.

        Args:
            config (tactus.ParsedConfig): Configuration file
            dry_run (bool, optional): Dry run not using ecflow. Defaults to False.

        """
        SuiteDefinition.__init__(self, config, dry_run=dry_run)

        self.config = config
        self.name = "Harp_point_verif" #config["general.case"]

        unix_group = self.platform.get_platform_value("unix_group")
        tactusmakedirs(self.joboutdir, unixgroup=unix_group)

        # Set the python_template path
        python_template = Path(tactus.__path__[0]).resolve() / "templates/ecflow/default.py" 	 		 		
        python_template = python_template.as_posix()

        ###Set up suite start with a delay to make time for the observations and references 
        ###to be available
        start_datetime = as_datetime(config["general.times.start"])  # datetime object
        forecast_range = as_timedelta(config["general.times.forecast_range"])  # timedelta
        delay = as_timedelta(config["submission.tactusharpverif_group.delay"])  # timedelta

        # Compute end_date before rounding (still datetime)
        raw_end_date = start_datetime + forecast_range

        # Round up to the next full day if not exactly at 00:00
        if raw_end_date.time() != datetime.min.time():
            end_date = (raw_end_date + pd.Timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            end_date = raw_end_date

        # Compute delay_date (end_date + delay), then round up to the next full day
        raw_delay_date = end_date + delay
        if raw_delay_date.time() != datetime.min.time():
            delay_date = (raw_delay_date + pd.Timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            delay_date = raw_delay_date

        print("start_date:",   start_datetime.strftime("%Y%m%d"))
        print("end_date:",     end_date.strftime("%Y%m%d"))
        print("delay_date:",   delay_date.strftime("%Y%m%d"))

        # We want retrieval to begin with a delay, to make sure obs data is available in OBSTABLES
        # Use _JULIAN for looking at differences > 1 day.

        delay_date_julian=as_julian(delay_date.strftime("%Y%m%d"))
        time_trigger = (
                f"(:ECF_JULIAN  ge {delay_date_julian})"
                )
        print("time_trigger is")
        print(time_trigger)
        self.config_verif = ConfigHarpverify(self.config)
        case = "Case_point_verification"

        case_family = EcflowSuiteFamily(
            case,
            self.suite,
            self.ecf_files
        )

        linkobsfctables = EcflowSuiteTask(
            "LinkOBSFCTABLES",
            case_family,
            self.config,
            self.task_settings,
            self.ecf_files,
            input_template=python_template,
        )
        # A "time-based" trigger is added differently (through ecflow).
        # Not sure if currently tactus has its own capabilities of a time trigger
        linkobsfctables.ecf_node.add_trigger(time_trigger)

        verification = EcflowSuiteTask(
            "Verification",
            case_family,
            self.config,
            self.task_settings,
            self.ecf_files,
            input_template=python_template,
            trigger=EcflowSuiteTriggers(EcflowSuiteTrigger(linkobsfctables))
        )

        filesave = EcflowSuiteTask(
            "Filesave",
            case_family,
            self.config,
            self.task_settings,
            self.ecf_files,
            input_template=python_template,
            trigger=EcflowSuiteTriggers(EcflowSuiteTrigger(verification))
        )

