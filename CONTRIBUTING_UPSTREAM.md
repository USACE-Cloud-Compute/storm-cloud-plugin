# Contributing Changes to Upstream StormHub

This guide explains how to contribute your fixes back to the upstream StormHub repository.

## Quick Start

### 1. First-time Setup (One-time)

```bash
# Fork the repo on GitHub first: https://github.com/Dewberry/stormhub -> Click "Fork"

# Add your fork as a remote
cd stormhub
git remote add fork https://github.com/YOUR_USERNAME/stormhub.git

# Verify remotes
git remote -v
# Should show:
#   origin  https://github.com/Dewberry/stormhub.git (fetch)
#   origin  https://github.com/Dewberry/stormhub.git (push)
#   fork    https://github.com/YOUR_USERNAME/stormhub.git (fetch)
#   fork    https://github.com/YOUR_USERNAME/stormhub.git (push)
```

### 2. For Each Fix/Feature

```bash
cd stormhub

# Create a feature branch from latest main
git fetch origin
git checkout origin/main
git checkout -b fix/descriptive-name

# Make your changes...
# Test your changes...

# Commit with a descriptive message
git add <files>
git commit -m "Short description

Detailed explanation of:
- What the problem was
- Why it occurred
- How this fix solves it
- Any edge cases handled"

# Push to your fork
git push fork fix/descriptive-name
```

### 3. Create Pull Request

1. Go to https://github.com/Dewberry/stormhub
2. Click "Pull Requests" → "New Pull Request"
3. Click "compare across forks"
4. Base repository: `Dewberry/stormhub` base: `main`
5. Head repository: `YOUR_USERNAME/stormhub` compare: `fix/descriptive-name`
6. Click "Create Pull Request"
7. Fill in the template (see below)
8. Submit!

## PR Template

```markdown
## Problem
[Clear description of the bug or limitation]

## Root Cause
[Technical explanation of why this happens]

## Solution
[What your changes do]
- Change 1
- Change 2

## Testing
[How you tested this]

## Backward Compatibility
[Any breaking changes? Usually "None - fully backward compatible"]

## Checklist
- [x] Code follows project style guidelines
- [x] Changes are backward compatible
- [x] Commit messages are descriptive
- [ ] Added/updated tests (if applicable)
- [ ] Updated documentation (if applicable)
```

## Best Practices

### Branch Naming
- `fix/` - Bug fixes
- `feature/` - New features
- `refactor/` - Code improvements
- `docs/` - Documentation updates

Examples:
- `fix/nan-values-after-reprojection`
- `feature/add-export-format`
- `refactor/simplify-interpolation`

### Commit Messages
```
Short one-line summary (50 chars or less)

Longer detailed explanation if needed:
- Why this change is necessary
- What problem it solves
- Any important implementation details
- References to issues: Fixes #123
```

### Code Style
- Follow existing code style in the file
- Add docstrings for new functions
- Add type hints where possible
- Keep changes focused and minimal

## Responding to Review

```bash
# Make requested changes
git add <files>
git commit -m "Address review feedback: <what changed>"

# Push updates (PR will auto-update)
git push fork fix/descriptive-name
```

## After PR is Merged

```bash
# Update your main repo
cd stormhub
git fetch origin
git checkout main
git pull origin main

# Update the submodule reference in main repo
cd ..
git submodule update --remote stormhub

# Commit the update
git add stormhub
git commit -m "Update stormhub submodule to latest main"

# Clean up local branch
cd stormhub
git branch -d fix/descriptive-name

# Optional: delete remote branch
git push fork --delete fix/descriptive-name
```

## Troubleshooting

### "Your branch has diverged"
```bash
# If your branch conflicts with upstream
git fetch origin
git rebase origin/main
git push fork fix/branch-name --force-with-lease
```

### "Merge conflicts"
```bash
# Resolve conflicts
git fetch origin
git rebase origin/main
# Fix conflicts in files
git add <resolved-files>
git rebase --continue
git push fork fix/branch-name --force-with-lease
```

### "Need to update submodule"
```bash
cd stormhub
git fetch origin
git checkout main
git pull origin main
cd ..
git add stormhub
git commit -m "Update stormhub submodule to latest"
```

## Tips

1. **Keep PRs small** - Easier to review and merge
2. **One fix per PR** - Don't bundle unrelated changes
3. **Test thoroughly** - Run all existing tests if available
4. **Be responsive** - Reply to review comments promptly
5. **Be patient** - Maintainers are volunteers, reviews take time
6. **Stay polite** - Open source thrives on collaboration

## Resources

- StormHub Repo: https://github.com/Dewberry/stormhub
- StormHub Docs: https://stormhub.readthedocs.io/
- Git Submodules: https://git-scm.com/book/en/v2/Git-Tools-Submodules
- GitHub PRs: https://docs.github.com/en/pull-requests
