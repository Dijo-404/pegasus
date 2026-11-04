"""Enforce dependency direction and package naming for the clean architecture."""

import ast
import importlib.util
from pathlib import Path
import re
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "pegasus"
LAYERS = ("domain", "application", "infrastructure", "presentation")


def imported_modules(path: Path):
    """Resolve absolute and relative imports, including imports inside functions."""
    relative = path.relative_to(PACKAGE_ROOT)
    package = ".".join(("pegasus", *relative.parts[:-1]))
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                module = importlib.util.resolve_name("." * node.level + (node.module or ""), package)
            else:
                module = node.module or ""
            yield module
            # "from pegasus import infrastructure" must not evade the layer rule.
            for alias in node.names:
                yield f"{module}.{alias.name}"


def is_within(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


@pytest.mark.parametrize("layer", LAYERS)
def test_dependencies_point_toward_the_domain(layer):
    assert (PACKAGE_ROOT / layer).is_dir(), f"Missing {layer} layer"
    violations = []
    for path in (PACKAGE_ROOT / layer).rglob("*.py"):
        for module in imported_modules(path):
            if layer in {"domain", "application"}:
                allowed_layers = ("domain",) if layer == "domain" else ("domain", "application")
                internal = any(is_within(module, f"pegasus.{item}") for item in allowed_layers)
                standard = module.partition(".")[0] in sys.stdlib_module_names
                allowed = internal or standard
            else:
                forbidden = (
                    ["pegasus.bootstrap", "pegasus.presentation"]
                    if layer == "infrastructure"
                    else [
                        "pegasus.bootstrap",
                        "pegasus.infrastructure",
                    ]
                )
                allowed = not any(is_within(module, prefix) for prefix in forbidden)
            if not allowed:
                violations.append(f"{path.relative_to(PACKAGE_ROOT)} imports {module}")
    assert not violations, "Layer dependency violations:\n" + "\n".join(violations)


def test_pegasus_uses_one_installed_source_package():
    import pegasus

    assert PACKAGE_ROOT.is_dir()
    assert Path(pegasus.__file__).resolve() == PACKAGE_ROOT / "__init__.py"
    assert not (PROJECT_ROOT / "veilagent").exists()
    assert not (PROJECT_ROOT / "pegasus").exists()


def test_runtime_modules_use_clean_names_and_current_imports():
    for path in PACKAGE_ROOT.rglob("*.py"):
        assert re.fullmatch(r"(?:[a-z][a-z0-9_]*|__init__)\.py", path.name), path
        assert not any(is_within(module, "veilagent") for module in imported_modules(path)), path
