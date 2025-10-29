## Migration Script — Convert `[tool.poetry]` to `[project]`

To simplify switching formats, use the helper script below. It automatically converts Poetry-style `pyproject.toml` files to **PEP 621-compliant** versions.

📜 **`migrate_to_pep621.py`**

```bash
# Dry run (prints converted TOML to stdout)
python migrate_to_pep621.py /path/to/pyproject.toml --dry-run

# Write in-place (creates pyproject.toml.bak)
python migrate_to_pep621.py /path/to/pyproject.toml

# Write to a different file
python migrate_to_pep621.py /path/to/pyproject.toml --out /tmp/new-pyproject.toml
```

### ✨ Features

* Converts `[tool.poetry]` → `[project]` (PEP 621)
* Translates version specs:

  * `^1.2.3` → `>=1.2.3,<2.0.0`
  * `~1.4` → `>=1.4,<1.5`
* Converts path/git deps to PEP 508 strings

  * `{ path = "…", develop = true }` → `pkg @ file:///abs/path`
  * `{ git = "…", rev = "main" }` → `pkg @ git+…@main`
* Maps `[tool.poetry.group.dev.dependencies]` → `[project.optional-dependencies].dev`
* Preserves `[tool.poetry.scripts]` as `[project.scripts]`
* Adds `[build-system]` if missing (uses `poetry-core`)
* Creates `.bak` backup before overwriting

📦 Download: [`migrate_to_pep621.py`]()
