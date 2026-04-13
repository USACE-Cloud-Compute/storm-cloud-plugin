# StormHub Cloud Plugin

A [USACE Cloud Compute](https://github.com/USACE-Cloud-Compute/cloudcompute) plugin that creates storm catalogs from NOAA AORC precipitation data and converts them to HEC-DSS files.

```
S3 payload  -->  download-inputs  -->  process-storms  -->  convert-to-dss  -->  upload-outputs
```

## Quick Start

Requires **Python 3** and **Docker**.

```bash
python run.py          # Builds image, starts MinIO, runs plugin (~2 min first run)
```

Results at http://localhost:9001 (ccuser/ccpassword).

## Custom Payloads

Edit `test/examples/payload.json` or copy it and pass the path:

```bash
cp test/examples/payload.json test/examples/mine.json
python run.py test/examples/mine.json
```

Storm parameters are in `attributes`. All values are strings (CC SDK convention).

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `catalog_id` | yes | | Unique ID for this storm catalog |
| `catalog_description` | yes | | Human-readable description for STAC metadata |
| `start_date` | yes | | Start of analysis period (`YYYY-MM-DD`) |
| `end_date` | no | `start_date` | End of analysis period (`YYYY-MM-DD`) |
| `storm_duration` | no | `"72"` | Storm event duration in hours |
| `top_n_events` | no | `"10"` | Number of top storms to keep |
| `min_precip_threshold` | no | `"0.0"` | Minimum mean precipitation (mm) |
| `check_every_n_hours` | no | `"24"` | How often to sample storm start times |
| `specific_dates` | no | | JSON array of dates to force-include |
| `input_path` | yes | | S3 path to watershed/transposition geometries |
| `output_path` | yes | | S3 path for results |

## Dev Tasks

```bash
python run.py build     # Init submodule + build Docker image
python run.py lint      # Ruff linter + format check
python run.py format    # Auto-format with ruff
python run.py freeze    # Regenerate constraints.txt
python run.py clean     # Remove containers, volumes, Local/
python run.py down      # Stop containers
```

## Known Limitations

- **stormhub v0.5.0**: Workers hang during storm collection. Pinned to v0.4.0.
