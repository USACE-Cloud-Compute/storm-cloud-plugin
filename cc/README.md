# StormHub with Cloud Compute

This guide provides instructions to set up and run StormHub with Cloud Compute using Python, Docker, and MinIO. The
working directory for this instruction is the `{PROJECT_ROOT}/cc` directory.

## A. Running via shell script
The following script start by initializing the MinIO instance, and then spin up a StormHub instance in Docker which
uses inputs from the MinIO instance. To run the script, within `scripts` directory in the terminal, run:
```shell
./start-stormhub-minio.sh
```

## Extra: Modifying the Inputs
To modify the arguments used by the **StormHub script**, update the `payload` JSON file located in: `minio/inputs`. 
This payload file is parsed by `main.py` using the `cc_py_sdk::PluginManager`.

### Uploading the Updated Payload
After making changes to the payload file, you have two options to upload it to **MinIO**:

**Option 1 (Manually via the MinIO Web UI)**
* Access the MinIO Web UI (http://localhost:9001)
* The credentials are in `minio/minio.env`
* Navigate to `$CC_AWS_BUCKET/$CC_ROOT/$CC_PAYLOAD`
* Upload the modified payload file.

**Option 2 (Restart MinIO and MinIO-init for Automatic Upload)**
This clears existing data and re-uploads the inputs using the MinIO client. Run the following commands in the terminal:
```shell
docker compose -f minio/docker-compose.yml down
docker compose -f minio/docker-compose.yml up -d
```

#### Notes
* **Option 1** is recommended if you only modified the `payload`
* **Option 2** is recommended if you modified more than one input
* If running via the shell script (B), inputs will always be up-to-date

## B. Running with IDE (e.g. PyCharm)
### 1. Set Up Python Environment

Ensure you have **PyCharm** (or another Python IDE) installed, then configure a **Python 3.12** interpreter (`venv`).

Open a terminal in the `cc` directory and install the required dependencies:
```shell
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

### 2. Start MinIO (S3 Simulation)
MinIO simulates an AWS S3 bucket for local testing. To start MinIO, run:
```shell
docker compose -f minio/docker-compose.yml up -d
```

### 3. Run the `main.py` script
The `main.py` script uses `cc_py_sdk` to:
* Read from the payload JSON file. 
* Parse its arguments. 
* Use the parsed arguments to run stormhub.

#### Setting Up Environment Variables
Before running `main.py`, you must set up the necessary environment variables.
The environment variables for this example are located in: `minio/minio.env`.

There are two ways to load these environment variables and run the `main.py` script:

**Option 1 (Recommended - In Your IDE)**
  * Create a new **Run Configuration** in your IDE.
  * Set `main.py` as the script to execute.
  * Assign `minio/minio.env` as the environment variables file.

**Option 2 (Linux Command Line)**
```shell
set -a
source minio/minio.env
set +a
python3 main.py
```