# Submodule Changes

This document tracks changes made to submodules and branch requirements.

---

## hec-dss-python: Using `docs/message_levels` branch

**Branch**: `docs/message_levels` (instead of `main`)
**Commit**: ef39067
**Status**: Required until merged to main

### Why This Branch?
The `main` branch of hec-dss-python does not handle NaN values in gridded data. When reprojecting meteorological grids (e.g., from 1km AORC to 4km SHG), NaN values can be introduced at grid edges due to CRS transformation artifacts.

The `docs/message_levels` branch includes commit `aef5af0` ("Added support for numpy arrays with NaN values in GriddedData.create") which:
- Uses `np.nanmax/nanmin/nanmean` instead of `np.max/min/mean`
- Converts NaN to DSS null value (`-3.4028234663852886e+38`) before writing

### Error Without This Fix
```
ValueError: cannot convert float NaN to integer
  File "hec-dss-python/src/hecdss/gridded_data.py", line 112, in update_grid_info
    bin_range = (int)(math.ceil(self.maxDataValue) - math.floor(self.minDataValue))
```

### To Update Submodule
```bash
cd hec-dss-python
git checkout docs/message_levels
git pull origin docs/message_levels
```

### When to Switch Back to Main
Once the NaN fix is merged to `main` in the upstream hec-dss-python repository, update to main:
```bash
cd hec-dss-python
git checkout main
git pull origin main
```

---

## StormHub Submodule Changes

This section tracks changes made to the StormHub submodule that are pending upstream contribution.

## Fix: NaN values during reprojection in DSS creation

**Branch**: `fix/nan-values-after-reprojection`
**Commit**: e1ab944
**Status**: Ready for upstream PR

### Problem
When calling `noaa_zarr_to_dss()` to create DSS files, the function fails with:
```
ValueError: cannot convert float NaN to integer
```

This occurs in `hec-dss-python`'s `GriddedData.update_grid_info()` when it tries to calculate `bin_range` from min/max values that contain NaN.

### Root Cause
The `write_to_dss()` function reprojects data from 1km AORC (WGS84) to 4km SHG (Albers Equal Area). The reprojection was using the **default resampling method**, which creates NaN values at grid edges due to:
- Grid misalignment between source (1km lat/lon) and target (4km Albers)
- Default resampling method not properly handling edge cases
- CRS transformation artifacts at boundaries

While StormHub already handles NaN values **before** reprojection (in `get_s3_zarr_data()`), the reprojection itself was introducing new NaN values.

### Solution
**Two-part fix for robust NaN handling**:

1. **Use proper resampling method**:
   - Add `resampling=Resampling.average` to `rio.reproject()` calls
   - Physically appropriate for aggregating precipitation from 1km to 4km
   - Reduces but doesn't completely eliminate edge NaN values

2. **Add fallback NaN handling**:
   - Check for NaN after reprojection with `data.isnull().any()`
   - Fill remaining NaN values with 0 using `data.fillna(0)`
   - Handles edge cases where CRS transformation still introduces NaN

This combination ensures robustness:
- `Resampling.average` = correct physical method + fewer NaN values
- `fillna(0)` = safety net for edge cases that can't be avoided
- Minimal code change (8 lines added)
- No backward compatibility issues

### Files Changed
- `stormhub/met/zarr_to_dss.py`:
  - Added `from rasterio.enums import Resampling` import (line 410)
  - Added `resampling=Resampling.average` to both reproject calls (lines 413, 423)
  - Added NaN check and fillna() after reprojection (lines 414-418)

### Testing
Tested with Duwamish watershed. All 5 storm events now successfully convert to DSS files with no NaN errors.

### Future: Contributing Upstream

#### Prerequisites
1. Fork the StormHub repository on GitHub: https://github.com/Dewberry/stormhub
2. Add your fork as a remote:
   ```bash
   cd stormhub
   git remote add fork https://github.com/YOUR_USERNAME/stormhub.git
   ```

#### Creating a Pull Request

1. **Push your branch to your fork**:
   ```bash
   cd stormhub
   git push fork fix/nan-values-after-reprojection
   ```

2. **Create PR on GitHub**:
   - Go to https://github.com/Dewberry/stormhub
   - Click "Pull Requests" → "New Pull Request"
   - Click "compare across forks"
   - Select your fork and the `fix/nan-values-after-reprojection` branch
   - Title: "Fix NaN values introduced during reprojection in DSS creation"
   - Description: Use the content from this document

3. **PR Description Template**:
   ```markdown
   ## Problem
   The `noaa_zarr_to_dss()` function fails with `ValueError: cannot convert float NaN to integer`
   when reprojection introduces NaN values at grid edges during DSS file creation.

   ## Root Cause
   While StormHub handles NaN values before reprojection (in `get_s3_zarr_data()`), it doesn't
   handle NaN values introduced BY the reprojection from 1km AORC to 4km SHG grid in `write_to_dss()`.

   ## Solution
   - Generalized `interpolate_nan_values()` to work with any spatial dimensions
   - Added post-reprojection NaN handling using the same bidirectional interpolation strategy
   - Maintains backward compatibility

   ## Testing
   Tested with watershed geometries that trigger edge NaN values. DSS files now successfully
   created for all storm events.

   ## Checklist
   - [x] Code follows project style guidelines
   - [x] Changes are backward compatible
   - [x] Commit messages are descriptive
   - [ ] Added tests (if applicable)
   ```

4. **Respond to review feedback**:
   - Make requested changes in the same branch
   - Push updates: `git push fork fix/nan-values-after-reprojection`
   - The PR will automatically update

5. **After PR is merged**:
   - Update the submodule to the new version
   - Delete the local branch: `git branch -d fix/nan-values-after-reprojection`
   - Update this document to mark the change as "Merged upstream"

## Notes
- Always create a new branch for each fix/feature
- Use descriptive branch names: `fix/`, `feature/`, `bugfix/`
- Write clear commit messages explaining the "why" not just the "what"
- Keep changes focused and minimal
- Test thoroughly before submitting PR
