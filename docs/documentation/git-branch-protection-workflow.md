# Git Workflow With Protected `main`

`main` must be branch-protected.

What this means:
- work on feature branches
- open PR to `main`
- merge only with green required checks
- no direct push to `main`

## Daily Flow

1. Sync local main

```bash
git checkout main
git pull origin main
```

2. Create branch

```bash
git checkout -b feat/<short-change-name>
```

3. Run local gates

```bash
make check
make ci-local
```

4. Rebase before push

```bash
git fetch origin
git rebase origin/main
make check
git push --force-with-lease
```

5. Open PR

```bash
gh pr create --fill --base main
```

6. Watch checks and merge when green

```bash
gh pr checks <PR_NUMBER> --watch
gh pr merge <PR_NUMBER> --merge --delete-branch
```
