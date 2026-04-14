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

> Local dev runs serialize storm-search by default (1 worker) because
> no container memory limit is enforced. For a faster loop, set
> `CC_NUM_WORKERS=4` in `test/local.env` or pass `num_workers` in
> the payload `attributes`.

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
| `num_workers` | no | auto | Parallel workers for storm search. Auto-sized from container memory (cgroup). Use `CC_NUM_WORKERS` env for a fleet default. Falls back to 1 worker when no memory limit is set. |
| `input_path` | yes | | S3 path to watershed/transposition geometries |
| `output_path` | yes | | S3 path for results |

## Dev Tasks

```bash
python run.py build     # Init submodule + build Docker image
python run.py package   # Build image and save as storm-cloud-plugin.tar
python run.py lint      # Ruff linter + format check
python run.py format    # Auto-format with ruff
python run.py freeze    # Regenerate constraints.txt
python run.py clean     # Remove containers, volumes, Local/
python run.py down      # Stop containers
```

## Reproducing the OOM Failure Mode

The vendored stormhub library would spawn `os.cpu_count() - 2` workers,
which inside a container reads the *host* CPU count and can exceed the
container's memory ceiling. To reproduce the original failure under a
3 GB cap:

```bash
docker compose -f docker-compose.yaml -f docker-compose.mem-limit.yaml build
docker compose -f docker-compose.yaml -f docker-compose.mem-limit.yaml run --rm seed
docker compose -f docker-compose.yaml -f docker-compose.mem-limit.yaml run --rm storm-cloud-plugin
```

With the fix, the resolver reads the cgroup limit and picks 1 worker;
without it, the library would pick 6 and `BrokenProcessPool`.

## Known Limitations

- **stormhub v0.5.0**: Workers hang during storm collection. Pinned to v0.4.0.
