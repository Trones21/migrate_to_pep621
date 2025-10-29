#!/usr/bin/env python3
\"\"\"
migrate_to_pep621.py
--------------------
Convert a Poetry-style pyproject.toml ([tool.poetry]) to PEP 621 ([project]).
- Translates dependencies (incl. ^/~ constraints) to PEP 440 ranges.
- Converts path/git deps to PEP 508 strings.
- Maps [tool.poetry.group.dev.dependencies] -> [project.optional-dependencies].
- Preserves scripts and basic metadata.
- Adds [build-system] for poetry-core if missing.
- Emits warnings for develop=true (editable) because PEP 621 can't encode it.
Usage:
    python migrate_to_pep621.py /path/to/pyproject.toml [--dry-run] [--out /path/to/output.toml]
\"\"\"

from __future__ import annotations

import argparse
import re
import sys
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import tomllib  # Python 3.11+
except Exception:
    tomllib = None  # type: ignore


def parse_authors(poetry_authors: List[str]) -> List[Dict[str, str]]:
    out = []
    pat = re.compile(r"^\\s*(?P<name>.+?)\\s*(?:<(?P<email>[^>]+)>)?\\s*$")
    for s in poetry_authors or []:
        m = pat.match(s)
        if not m:
            out.append({\"name\": s})
            continue
        d = {\"name\": m.group(\"name\").strip()}
        if m.group(\"email\"): d[\"email\"] = m.group(\"email\").strip()
        out.append(d)
    return out


def caret_to_range(ver: str) -> str:
    if not ver.startswith(\"^\"): return ver
    base = ver[1:]
    parts = [int(p) for p in base.split(\".\")]
    while len(parts) < 3: parts.append(0)
    maj, minor, patch = parts[:3]
    if maj > 0: upper = f\"{maj+1}.0.0\"
    elif minor > 0: upper = f\"0.{minor+1}.0\"
    else: upper = f\"0.0.{patch+1}\"
    return f\">={maj}.{minor}.{patch},<{upper}\"


def tilde_to_range(ver: str) -> str:
    if not ver.startswith(\"~\"): return ver
    base = ver[1:]
    parts = base.split(\".\")
    if len(parts) == 1:
        lower = f\"{parts[0]}.0\"
        upper = f\"{int(parts[0]) + 1}.0\"
        return f\">={lower},<{upper}\"
    if len(parts) == 2:
        major, minor = int(parts[0]), int(parts[1])
        return f\">={major}.{minor},<{major}.{minor+1}\"
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    return f\">={major}.{minor}.{patch},<{major}.{minor+1}.0\"


def normalize_version_constraint(ver: str) -> str:
    ver = ver.strip()
    if ver.startswith(\"^\"): return caret_to_range(ver)
    if ver.startswith(\"~\"): return tilde_to_range(ver)
    return ver


def dep_table_to_pep508(name: str, val: Any, warnings: List[str]) -> str:
    if isinstance(val, str):
        constraint = normalize_version_constraint(val)
        return f\"{name}{(' ' + constraint) if constraint else ''}\"
    if isinstance(val, dict):
        if \"path\" in val:
            path = Path(val[\"path\"]).expanduser()
            if val.get(\"develop\"):  # editable not supported in PEP 621
                warnings.append(f\"[editable-warning] {name} uses develop=true (editable). PEP 621 cannot encode this. "
                                f\"Use `pip install -e {path}` inside the venv for live edits.\")
            abs_path = path if path.is_absolute() else (Path.cwd() / path).resolve()
            return f\"{name} @ file://{abs_path}\"
        if \"git\" in val:
            url = val[\"git\"]
            ref = val.get(\"rev\") or val.get(\"tag\") or val.get(\"branch\")
            return f\"{name} @ git+{url}@{ref}\" if ref else f\"{name} @ git+{url}\"
        version = val.get(\"version\")
        extras = val.get(\"extras\") or []
        markers = val.get(\"markers\")
        pieces = [name]
        if extras: pieces[-1] = f\"{name}[{','.join(extras)}]\"
        if version: pieces.append(normalize_version_constraint(version))
        if markers: pieces.append(f\"; {markers}\")
        return \" \".join(pieces)
    return str(val)


def poetry_deps_to_pep621(deps: Dict[str, Any], warnings: List[str]) -> List[str]:
    out: List[str] = []
    for name, val in (deps or {}).items():
        if name.lower() == \"python\": continue
        out.append(dep_table_to_pep508(name, val, warnings))
    return sorted(out, key=str.lower)


def toml_escape(s: str) -> str:
    return s.replace(\"\\\\\", \"\\\\\\\\\").replace('\"', '\\\\\"')


def dump_toml_array_str(arr: List[str], indent: int = 0) -> str:
    pad = \" \" * indent
    items = \",\\n\".join(pad + f'\"{toml_escape(x)}\"' for x in arr)
    return \"[\\n\" + items + \"\\n\" + (\" \" * max(indent - 2, 0)) + \"]\"


def build_pep621_toml(poetry: Dict[str, Any], build_system: Dict[str, Any], warnings: List[str]) -> str:
    proj: Dict[str, Any] = {}
    proj[\"name\"] = poetry.get(\"name\", \"unknown-package\")
    proj[\"version\"] = poetry.get(\"version\", \"0.1.0\")
    if poetry.get(\"description\"): proj[\"description\"] = poetry[\"description\"]
    if poetry.get(\"readme\"): proj[\"readme\"] = poetry[\"readme\"]
    authors = parse_authors(poetry.get(\"authors\", []))
    if authors: proj[\"authors\"] = authors
    if poetry.get(\"license\"): proj[\"license\"] = {\"text\": poetry[\"license\"]}
    urls = {}
    for k in (\"homepage\", \"repository\", \"documentation\"):
        if poetry.get(k):
            label = {\"homepage\": \"Homepage\", \"repository\": \"Repository\", \"documentation\": \"Documentation\"}[k]
            urls[label] = poetry[k]
    if urls: proj[\"urls\"] = urls
    dep_list = poetry_deps_to_pep621(poetry.get(\"dependencies\", {}), warnings)
    if dep_list: proj[\"dependencies\"] = dep_list
    optional_deps = {}
    groups = poetry.get(\"group\", {}) if isinstance(poetry.get(\"group\", {}), dict) else {}
    dev_group = groups.get(\"dev\", {})
    dev_deps = poetry_deps_to_pep621(dev_group.get(\"dependencies\", {}), warnings)
    if dev_deps: optional_deps[\"dev\"] = dev_deps
    if optional_deps: proj[\"optional-dependencies\"] = optional_deps
    scripts = poetry.get(\"scripts\", {}) or {}
    if scripts: proj[\"scripts\"] = scripts
    bs = build_system or {\"requires\": [\"poetry-core>=1.9.0\"], \"build-backend\": \"poetry.core.masonry.api\"}
    lines: List[str] = []
    lines.append(\"[project]\")
    for key in (\"name\", \"version\", \"description\", \"readme\"):
        if key in proj: lines.append(f'{key} = \"{toml_escape(proj[key])}\"')
    if \"authors\" in proj:
        lines.append(\"authors = [\")
        for a in proj[\"authors\"]:
            if \"email\" in a:
                lines.append(f'  {{ name = \"{toml_escape(a[\"name\"])}\", email = \"{toml_escape(a[\"email\"])}\" }},')
            else:
                lines.append(f'  {{ name = \"{toml_escape(a[\"name\"])}\" }},')
        lines.append(\"]\")
    if \"license\" in proj:
        lic = proj[\"license\"]
        if isinstance(lic, dict) and \"text\" in lic:
            lines.append(f'license = {{ text = \"{toml_escape(lic[\"text\"]) }\" }}')
    if \"urls\" in proj:
        lines.append(\"[project.urls]\")
        for k, v in proj[\"urls\"].items():
            lines.append(f'{k} = \"{toml_escape(v)}\"')
    if \"dependencies\" in proj:
        lines.append(\"\")
        lines.append(\"dependencies = \" + dump_toml_array_str(proj[\"dependencies\"], indent=2))
    if \"optional-dependencies\" in proj:
        lines.append(\"\")
        lines.append(\"[project.optional-dependencies]\")
        for group, arr in proj[\"optional-dependencies\"].items():
            arr_txt = dump_toml_array_str(arr, indent=2)
            lines.append(f\"{group} = {arr_txt}\")
    if \"scripts\" in proj:
        lines.append(\"\")
        lines.append(\"[project.scripts]\")
        for k, v in proj[\"scripts\"].items():
            lines.append(f'{k} = \"{toml_escape(v)}\"')
    lines.append(\"\")
    lines.append(\"[build-system]\")
    requires = bs.get(\"requires\", [\"poetry-core>=1.9.0\"])
    requires_items = \", \".join(f'\"{toml_escape(x)}\"' for x in requires)
    lines.append(f\"requires = [{requires_items}]\")
    lines.append(f'build-backend = \"{toml_escape(bs.get(\"build-backend\", \"poetry.core.masonry.api\"))}\"')
    if warnings:
        lines.append(\"\")
        lines.append(\"# --- Migration notes ---\")
        for w in warnings: lines.append(\"# \" + w)
    return \"\\n\".join(lines) + \"\\n\"


def migrate_pyproject(pyproject_path: Path, dry_run: bool = False, out_path: Path | None = None) -> Tuple[str, List[str]]:
    if tomllib is None:
        raise RuntimeError(\"Python 3.11+ required (tomllib).\" )
    data = tomllib.loads(pyproject_path.read_text(encoding=\"utf-8\"))
    poetry = data.get(\"tool\", {}).get(\"poetry\", {})
    if not poetry:
        raise ValueError(\"No [tool.poetry] section found; nothing to migrate.\")
    build_system = data.get(\"build-system\", {})
    warnings: List[str] = []
    new_text = build_pep621_toml(poetry, build_system, warnings)
    if not dry_run:
        backup = pyproject_path.with_suffix(\".toml.bak\")
        shutil.copy2(pyproject_path, backup)
        target = out_path or pyproject_path
        target.write_text(new_text, encoding=\"utf-8\")
    return new_text, warnings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(\"pyproject\", type=Path, help=\"Path to pyproject.toml (Poetry style)\")
    ap.add_argument(\"--dry-run\", action=\"store_true\", help=\"Print converted TOML to stdout; do not write files\")
    ap.add_argument(\"--out\", type=Path, default=None, help=\"Optional output path. Defaults to overwrite pyproject.toml (with .bak backup)\" )
    args = ap.parse_args()

    text, warnings = migrate_pyproject(args.pyproject, dry_run=args.dry_run, out_path=args.out)
    if args.dry_run:
        sys.stdout.write(text)
    if warnings:
        print(\"\\nWarnings:\", file=sys.stderr)
        for w in warnings:
            print(\"- \" + w, file=sys.stderr)


if __name__ == \"__main__\":
    main()
