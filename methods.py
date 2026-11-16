"""ExampleMethod."""
import os
from datetime import datetime, timedelta
from dateutil import parser
import pandas as pd
import yaml
import pyproj
import glob
import subprocess
import re
from tactus.toolbox import Platform


class ConfigHarpverify(object):
    """description"""

    def __init__(self, config):
        """Construct base task.

        Args:
            config (tactus.ParsedConfig): Configuration

        """
        def forecast_range_to_hours(forecast_range):
            match = re.fullmatch(r'P(\d+)D|PT(\d+)H', forecast_range)
            if match:
                days = match.group(1)
                hours = match.group(2)
                
                if days:
                    return int(days) * 24  # Convert days to hours
                elif hours:
                    return int(hours)  # Already in hours
            raise ValueError(f"Invalid forecast_range format: {forecast_range}")

        self.config = config
        self.platform = Platform(config)
        self.home = self.platform.get_value("submission.tactusharpverif_group.ENV.VERIF_HOME")
        self.obs_step= self.platform.get_value("submission.tactusharpverif_group.ENV.OBS_STEP")
        self.obstables_path= self.platform.get_value("submission.tactusharpverif_group.ENV.OBSTABLES_PATH")
        self.harpscripts_home=self.platform.get_value("submission.tactusharpverif_group.ENV.HARPSCRIPTS_HOME")
        self.cnmexp = self.config["general.cnmexp"]
        self.csc = self.config["general.csc"]
        self.cycle = self.config["general.cycle"]
        self.domain_name = self.config["domain.name"]
        self.start = self.platform.get_value("general.times.start")
        self.end = self.platform.get_value("general.times.end")
        self.startyyyymmddhh=datetime.strptime(self.start, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y%m%d%H")
        self.startyyyy=datetime.strptime(self.start, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y")
        self.startmm=datetime.strptime(self.start, "%Y-%m-%dT%H:%M:%SZ").strftime("%m")
        self.startdd=datetime.strptime(self.start, "%Y-%m-%dT%H:%M:%SZ").strftime("%d")
        self.cycle_length = self.platform.get_value("general.times.cycle_length")
        self.forecast_range = self.platform.get_value("general.times.forecast_range")
        self.cycle_length_nr = forecast_range_to_hours(self.cycle_length)
        self.forecast_range_nr = forecast_range_to_hours(self.forecast_range)
        self.endyyyymmddhh = (datetime.strptime(self.start, "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=self.forecast_range_nr)).strftime("%Y%m%d%H")
        self.exp = self._set_exp()
        self.eps=True if len(self.platform.get_value("eps.general.members"))> 1 else False
        self.experiment_name = self.platform.get_value("extractsqlite.sqlite_model_name")
        self.sqlites_exp_path=self.platform.get_value("extractsqlite.merged_sqlite_path") if self.eps==True else self.platform.get_value("extractsqlite.sqlite_path")
        self.sqlites_ref_path=self.platform.get_value("submission.tactusharpverif_group.ENV.REF_SQLITES")
        self.sqlites_obs_path=self.platform.get_value("submission.tactusharpverif_group.ENV.OBSTABLES_PATH")
        self.rdss_path=self.platform.get_value("submission.tactusharpverif_group.ENV.RDSS_PATH")
        self.pngs_path=self.platform.get_value("submission.tactusharpverif_group.ENV.PNGS_PATH")
        self.Renv_conf=self.platform.get_value("submission.tactusharpverif_group.ENV.Renv_conf")
        self.case = self.config["general.case"]
        self._case_args = None
        self._exp_args = None
        self.config_yaml = None
        self.config_yaml_filename = None
        self.tactusverify_path=self.platform.get_value("general.plugin_registry.plugins.tactusharpverify")
        self.eps=  True if len(self.platform.get_value("eps.general.members"))> 1 else False
        #all_refs = self.platform.get_value("submission.tactusharpverif_group.ENV.REF_NAME")
        all_refs=["GDT_iekm","IFS","IFSENS"]
        if self.eps: # Select the model references according to the type of run
           self.ref_name = [r for r in all_refs if "ENS" in r.upper()]
        else:
           self.ref_name = [r for r in all_refs if "ENS" not in r.upper()]
        self.sqlites_exp_path=self.platform.get_value("extractsqlite.merged_sqlite_path") if self.eps else self.platform.get_value("extractsqlite.sqlite_path")
        self.plugin_path=self.platform.get_value("general.plugin_registry.plugins.tactusharpverif")
        self.set_params=os.path.join(self.plugin_path,'templates','set_params_eps.R' if self.eps else 'set_params_det.R')


    def write_config_yml(self,write=True):
        """descrp.

        Args:
            case (str): Recipient of the greeting
        """
        print('self.home es ' + self.home)
        config_template = os.path.join(self.tactusverify_path,"templates/tactus_conf_eps.yml" if self.eps else "templates/tactus_conf_det.yml")
        self.config_yaml_filename = os.path.join(self.home, f"config_files/",self.startyyyy,self.startmm,self.startdd,f"tactus_conf_{self.case}.yml")
        print("config_template es")
        print(config_template)
        sqlites_relpath=self.sqlites_exp_path
        yyyy_mm_string=str(self.startyyyy)+'/'+str(self.startmm) # get that 2025/02 part to get exp_scratch in the next line:
        exp_scratch=self.sqlites_exp_path
        #Construct local_fctables:
        local_fctables=os.path.join(self.home,f"FCTABLES/",self.case,self.case,self.startyyyy,self.startmm)
        Construct local_fctables_ref:
        local_fctables_ref=os.path.join(self.home,f"FCTABLES/",self.case) #This is where REF's folder with FCTABLES should be linked    
        if os.path.isfile(config_template):
            self._exp_args = ConfigHarpverify.load_yaml(config_template)
            self._exp_args["verif"]["fcst_model"]=list(self.ref_name) + [self.csc_resol]
            self._exp_args["verif"]["project_name"]=[self.case]
            self._exp_args["verif"]["lead_time"]= f"seq(0,{self.forecast_range_nr},{self.obs_step})"
            self._exp_args["verif"]["obs_path"]=[self.obstables_path]
            if self.use_operational_indexing=="yes":
                self._exp_args["verif"]["verif_path"]=[os.path.join(self.rdss_path,exp_relpath.lstrip('/').split(self.csc)[0])]
                self._exp_args["post"]["plot_output"]=[os.path.join(self.pngs_path,exp_relpath.lstrip('/').split(self.csc)[0])]
                self._exp_args["verif"]["fcst_path"]=[local_fctables.split(self.csc)[0]]
            else:
                self._exp_args["verif"]["verif_path"]=[os.path.join(self.rdss_path)]
                self._exp_args["post"]["plot_output"]=[os.path.join(self.pngs_path)]
                self._exp_args["verif"]["fcst_path"]=[os.path.join(self.home,f"FCTABLES/",self.case)]
            self._exp_args["scorecards"]["ref_model"]=[self.ref_name[0]]
            self._exp_args["scorecards"]["fcst_model"]=[self.csc_resol]
            if write==True:
               ConfigHarpverify.save_yaml(self.config_yaml_filename, self._exp_args)
               print("wrote yml file at"+self.config_yaml_filename)
        else:
            print("not found template config file")
        return self.config_yaml_filename,self._exp_args

    def _set_exp(self):
        """

        """
        return "_".join([self.cnmexp, self.csc, self.cycle, self.domain_name])

    @staticmethod
    def link_files(source_dir, destination_dir):
        # Get all files in the source directory
        files = glob.glob(os.path.join(source_dir, "*"))
        # Ensure the destination directory exists
        if not os.path.exists(destination_dir):
           os.makedirs(destination_dir) 
	   # Link each file individually

        for file in files:
               # Get the basename of the file (i.e., the file name without the path)
               filename = os.path.basename(file)
               destination_file = os.path.join(destination_dir, filename)
               # Create a hard link for the file
               # Check if the file already exists in the destination directory
               if not os.path.exists(destination_file):
                  # Create a hard link for the file if it doesn't already exist
                  os.symlink(file, destination_file)
               else:
                  print(f"File {destination_file} already exists, skipping.")
    @staticmethod
    def load_yaml(config_file):
        with open(config_file, 'r') as stream:
             data_loaded = yaml.load(stream, Loader=yaml.SafeLoader)
        return data_loaded
    @staticmethod
    def save_yaml(config_file, data):
        # Ensure the directory exists
        os.makedirs(os.path.dirname(config_file), exist_ok=True)												
        with open(config_file, "w") as stream:
             yaml.dump(data, stream, default_flow_style=False, sort_keys=False)
    @staticmethod
    def replicate_structure_to_ec(origin_path, ec_base_path):
        print('start replicate function')
        print(origin_path)
        print(ec_base_path)
        # Walk through all directories and files in the origin path
        for dirpath, dirnames, filenames in os.walk(origin_path):
            print(dirpath)
            print(dirnames)
            print(filenames)

            # Compute relative path from the origin path
            rel_dir = os.path.relpath(dirpath, origin_path)
            print('rel_dir')
            print(rel_dir)
            # Construct the target directory path on the HPC (ec:../username/)
            ec_target_dir = os.path.join(ec_base_path, rel_dir)

            # Replace local file path separators with '/' for the HPC system (if necessary)
            ec_target_dir = ec_target_dir.replace("\\", "/")  # Ensure proper path format
            print('ec_target_dir')
            print(ec_target_dir)
            # Check if the target directory already exists on the HPC
            if ( subprocess.run(["els", ec_target_dir], capture_output=True, text=True).returncode == 1 ): #check_ec_directory_exists(ec_target_dir):
                # Create the target directory on the HPC using 'emkdir'
                try:
                    subprocess.run(["emkdir", ec_target_dir], check=True)
                    print(f"Created directory: {ec_target_dir}")
                except subprocess.CalledProcessError as e:
                    print(f"Error creating directory {ec_target_dir}: {e}")
            else:
                print(f"Directory {ec_target_dir} already exists, skipping creation.")

            # Copy each file in the current directory
            for filename in filenames:
                local_file = os.path.join(dirpath, filename)
                ec_target_file = os.path.join(ec_target_dir, filename)
    
                # Use 'ecp' to copy files to the HPC
                try:
                    subprocess.run(["ecp", local_file, ec_target_file], check=True)
                    print(f"Copied file: {local_file} to {ec_target_file}")
                except subprocess.CalledProcessError as e:
                    print(f"Error copying file {local_file} to {ec_target_file}: {e}")

