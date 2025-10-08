# StormHub with Cloud Compute

```bash
# Initialize StormHub Git submodule
git submodule update --init
# Spin up sample container (attach to shell and run `python3.12 main.py`)
bash cc/scripts/start-stormhub-minio.sh
# Build image
bash cc/scripts/build-stormhub-cloud-image.sh
# Save image
bash cc/scripts/save-stormhub-cloud-image.sh
```

