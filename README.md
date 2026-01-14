# StormHub with Cloud Compute

### 1. Pull submodules
This command pull and update all submodules in this repository
```bash
git submodule update --init
```

### 2. Run a quick test
This command runs a quick test that spins up two Docker containers:
* MinIO instance -- stores inputs and outputs
* StormHub MinIO instance -- contains the environment to run the main script

Need to attach to the StormHub MinIO container to run `python3.12 main.py` when the containers are ready.
```bash
bash cc/scripts/quicktest.sh
```

### 3. Build/Save StormHub Cloud image
```bash
# Build image
bash cc/scripts/build-storm-cloud-plugin-image.sh
# Save image
bash cc/scripts/save-storm-cloud-plugin-image.sh
```

