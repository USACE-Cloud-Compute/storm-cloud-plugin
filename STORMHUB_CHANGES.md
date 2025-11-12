# StormHub Submodule Changes

This document tracks changes made to the StormHub submodule that are pending upstream contribution.

## Fix: NaN values after reprojection in DSS creation

**Branch**: `fix/nan-values-after-reprojection`
**Commit**: d7072d1
**Status**: Ready for upstream PR

### Problem
When calling `noaa_zarr_to_dss()` to create DSS files, the function fails with:
```
ValueError: cannot convert float NaN to integer
```

This occurs in `hec-dss-python`'s `GriddedData.update_grid_info()` when it tries to calculate `bin_range` from min/max values that contain NaN.

### Root Cause
The `write_to_dss()` function reprojects data from 1km AORC (WGS84) to 4km SHG grid. This reprojection can introduce NaN values at grid edges due to:
- Misalignment between source and target grid boundaries
- CRS transformation artifacts
- Resolution change from 1km to 4km

While StormHub already handles NaN values **before** reprojection (in `get_s3_zarr_data()`), it didn't handle NaN values **introduced by** reprojection.

### Solution
1. **Generalized `interpolate_nan_values()` function**:
   - Added `dim1` and `dim2` parameters (default: "latitude", "longitude")
   - Now works with any spatial dimensions (e.g., "x", "y" after reprojection)
   - Preserves original units instead of hardcoding "K"
   - Fully backward compatible

2. **Added post-reprojection NaN handling in `write_to_dss()`**:
   - Detects NaN values after reprojection
   - Applies bidirectional interpolation per time slice
   - Uses the same averaging strategy as pre-reprojection handling
   - Falls back to `fillna(0)` for corner NaNs

### Files Changed
- `stormhub/met/zarr_to_dss.py`:
  - Modified `interpolate_nan_values()` (lines 286-315)
  - Added NaN handling in `write_to_dss()` after reprojection (lines 424-439)

### Testing
Tested with watershed geometries that trigger edge NaN values during reprojection. DSS files now successfully created for all storm events.

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
