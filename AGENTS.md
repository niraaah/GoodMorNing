# Sensitive-data handling

## Branch workflow

- Keep `main` as the deployable branch and `niraaah` as the user's persistent development branch. Make changes on `niraaah`, not directly on `main`; do not create topic branches unless the user asks.
- Before a new task, fetch and merge the latest `origin/main` into `niraaah`, preserving any ongoing work. Push `niraaah` and open a pull request to `main`. Run the applicable build and secret checks before merging; retain a clear description of changes and validation. Keep `niraaah` after merging, and synchronize it with main before the next task.
- Local runtime installs, credentials, database backups and `TODO.md` stay outside Git. A code merge does not mean a local database migration or model installation has run.

## Credentials

- Never print, paste into chat, commit, or publish actual API keys, access keys, bearer tokens, private connection URLs, or passwords. Report only the name, presence, and result of a check.
- Keep local credentials in ignored `data/` files or process environment variables. Tracked examples must contain empty credential values. GitHub Pages and Actions variables are public configuration only; never place secrets in frontend files or build arguments.
- Before every commit, run `python scripts/check_secrets.py` and the installed Gitleaks staged check. Keep `.githooks/pre-commit` enabled. Do not bypass hooks, suppress a real finding, add an allowlist, or disable the CI security gate to get a commit/deployment through.
- Before deployment, inspect the artifact for private files and known local credential values. Investigate findings without printing matched content. If a genuine credential was already pushed, report its type/location with the value redacted and coordinate rotation; deleting the current file does not remove Git history.
