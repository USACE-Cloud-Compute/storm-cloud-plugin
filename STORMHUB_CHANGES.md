# StormHub Submodule Changes

This document tracks changes made to the StormHub submodule that are pending upstream contribution.

## Fix: NaN values during reprojection in DSS creation

**Branch**: `fix/nan-values-after-reprojection`
**Commit**: 1d95c70
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
**Use explicit `Resampling.average` method during reprojection**:
- Add `resampling=Resampling.average` parameter to `rio.reproject()` calls
- This properly aggregates sixteen 1km cells into one 4km cell
- Physically appropriate for precipitation data aggregation
- Prevents NaN creation at grid edges instead of fixing them afterward

This is the correct approach because:
1. **Prevents the problem** rather than working around it
2. **Physically meaningful** - averaging is the right method for precipitation
3. **Minimal code change** - only 4 lines modified
4. **No backward compatibility issues** - just specifying what was implicit

### Files Changed
- `stormhub/met/zarr_to_dss.py`:
  - Added `from rasterio.enums import Resampling` import (line 410)
  - Added `resampling=Resampling.average` to both reproject calls (lines 413, 423)

### Testing
Tested with watershed geometries that previously triggered NaN errors. DSS files now successfully created for all storm events with no NaN values.

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
