import json
import logging
import multiprocessing
from pathlib import Path
from cc.plugin_manager import PluginManager, DataSource, DataSourceOpInput
from stormhub.logger import initialize_logger
from stormhub.met.storm_catalog import new_catalog, new_collection

# Initialize logger
initialize_logger(level=logging.INFO)

class StormHubProcessor:
    """Handles downloading, processing, and uploading storm data."""

    def __init__(self):
        """Initialize settings, load payload, and create necessary directories."""
        self.plugin_manager = PluginManager()
        self.payload = self.plugin_manager.get_payload()

        # Define local directory for processing storm data
        self.local_root_dir = "Local"  # Root directory for storing downloaded and processed files

        # Define cloud storage settings
        self.output_store_name = "StormHubStore"  # Remote data source store name for output files
        self.remote_base = self.payload.attributes["output_path"]  # Base remote directory for uploads

        # Extract catalog-specific information from the payload
        self.catalog_id = self.payload.attributes["catalog_id"]  # Unique identifier for the storm catalog
        self.config_path = f"{self.local_root_dir}/config.json"  # Path to the configuration file
        self.local_output_dir = f"{self.local_root_dir}/{self.catalog_id}"  # Local storage for processed storm data

        # Extract storm analysis parameters from the payload
        try:
            attrs = self.payload.attributes
            
            self.storm_params = {
                # Start date for storm analysis (String) - Required
                "start_date": attrs["start_date"],
                # Optional end date (String)
                "end_date": attrs.get("end_date", ""),
                # Duration of storms to analyze (Integer)
                "storm_duration": int(attrs.get("storm_duration", 72)),
                # Minimum precipitation threshold (Float)
                "min_precip_threshold": float(attrs.get("min_precip_threshold", 0.0)),
                # Number of top storm events to retain (Integer)
                "top_n_events": int(attrs.get("top_n_events", 10)),
                # Frequency of storm checks (Integer)
                "check_every_n_hours": int(attrs.get("check_every_n_hours", 24)),
                # Specific dates for storm selection (List of Strings)
                "specific_dates": json.loads(attrs.get("specific_dates", "[]")) if attrs.get("specific_dates") else []
            }
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            raise ValueError(f"Invalid storm parameters in payload: {e}")

        # Ensure the local root directory exists for storing files
        Path(self.local_root_dir).mkdir(parents=True, exist_ok=True)

    def download_files(self):
        """Download all input files to local storage from various data sources."""
        for source in self.payload.inputs:
            for key, remote_path in source.paths.items():
                # Define the local file path based on the remote file name
                local_path = f"{self.local_root_dir}/{Path(remote_path).name}"

                # Create an operation input object for tracking file downloads
                op = DataSourceOpInput(name=source.name, pathkey=key, datakey=None)
                print(f"Downloading {remote_path} -> {local_path}")
                self.plugin_manager.copy_file_to_local(ds=op, localpath=local_path)

    def create_config_file(self):
        """Generate the config.json file with dynamically assigned values."""
        input_paths = self.payload.inputs[0].paths
        watershed_filename = Path(input_paths["watershed"]).name
        transposition_filename = Path(input_paths["transposition"]).name

        config_data = {
            "watershed": {
                "id": f"{self.catalog_id}-watershed",
                "geometry_file": f"{self.local_root_dir}/{watershed_filename}",
                "description": "!!!Watershed for use in development of storm catalog"
            },
            "transposition_region": {
                "id": f"{self.catalog_id}-transposition",
                "geometry_file": f"{self.local_root_dir}/{transposition_filename}",
                "description": "!!!Transposition Domain for use in development of storm catalog"
            }
        }

        # Convert dictionary to JSON string first
        json_string = json.dumps(config_data, indent=4)

        # Write the string to the file manually
        with open(self.config_path, "w", encoding="utf-8") as json_file:
            json_file.write(json_string)

        print(f"Config file created at {self.config_path}")

    def upload_files(self):
        """Upload processed storm data to remote storage while maintaining directory structure."""
        if not Path(self.local_output_dir).exists():
            raise FileNotFoundError(f"Output directory not found: {self.local_output_dir}")

        # Create a new DataSource object to represent the output storage
        output_source = DataSource(
            name="StormProcessedData", paths={}, data_paths={}, store_name=self.output_store_name
        )
        self.plugin_manager.outputs().append(output_source)

        # Iterate through all files in the output directory and upload them
        for file in Path(self.local_output_dir).rglob("*"):
            if file.is_file():
                # Determine relative path within the output directory
                rel_path = file.relative_to(self.local_output_dir)
                # Construct the full remote path where the file will be stored
                remote_path = f"{self.remote_base}/{rel_path}"

                # Store the mapping of relative local path to remote path
                output_source.paths[str(rel_path)] = remote_path

                # Create an operation input object for tracking file uploads
                op = DataSourceOpInput(name=output_source.name, pathkey=str(rel_path), datakey=None)
                print(f"Uploading {file} -> {remote_path}")
                self.plugin_manager.copy_file_to_remote(ds=op, localpath=str(file))

    def process_storm_data(self):
        """Create and process a storm catalog using defined parameters."""
        # Use 'spawn' instead of 'fork' for stability across platforms/architectures
        multiprocessing.set_start_method("spawn", force=True)
        # Create a new storm catalog using provided configurations
        catalog = new_catalog(
            self.catalog_id,
            self.config_path,
            local_directory=self.local_root_dir,
            catalog_description=self.payload.attributes["catalog_description"],
        )

        # Generate and return a new storm collection using the provided parameters
        return new_collection(catalog, **self.storm_params)

    def run(self):
        """Execute the full workflow: Download, Process, Upload."""
        try:
            print("\n--- Step 1: Downloading Files ---")
            self.download_files()

            print("\n--- Step 2: Creating Storm Catalog Config File ---")
            self.create_config_file()

            print("\n--- Step 3: Processing Storm Data ---")
            self.process_storm_data()
            print("StormHub Catalog and Collection created!")

            print("\n--- Step 4: Uploading Files ---")
            self.upload_files()

            print("\nProcessing completed successfully!")
        except (FileNotFoundError, ValueError) as e:
            print(f"\nERROR: {e}")


if __name__ == "__main__":
    StormHubProcessor().run()