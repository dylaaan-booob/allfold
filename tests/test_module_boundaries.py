"""Keep business and Provider imports independent of the HTTP composition layer."""
import ast
import importlib
from pathlib import Path


def test_runtime_modules_import_and_dependencies_point_inward():
    root = Path(__file__).resolve().parents[1] / "src/allfold"
    for directory, forbidden in (("application", ("allfold.web",)),
                                 ("providers", ("allfold.application", "allfold.web"))):
        for file in (root / directory).rglob("*.py"):
            module = "allfold." + ".".join(file.relative_to(root).with_suffix("").parts)
            if file.name == "__init__.py":
                module = module.removesuffix(".__init__")
            importlib.import_module(module)
            for node in ast.walk(ast.parse(file.read_text())):
                names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [n.name for n in node.names] if isinstance(node, ast.Import) else []
                assert not any(name == prefix or name.startswith(prefix + ".") for name in names for prefix in forbidden), (file, names)
