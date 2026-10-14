"""The deployed container must include every local Python module it imports."""

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DeploymentPackageTest(unittest.TestCase):
    def test_dockerfile_copies_local_imports(self):
        copied = set()
        for line in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if parts and parts[0] == "COPY":
                copied.update(part for part in parts[1:-1] if part.endswith(".py"))
        modules = {path.stem: path.name for path in ROOT.glob("*.py")}
        for filename in copied:
            tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in modules:
                    self.assertIn(modules[node.module], copied,
                                  f"{filename} imports {modules[node.module]} but Dockerfile omits it")
                elif isinstance(node, ast.Import):
                    for item in node.names:
                        if item.name in modules:
                            self.assertIn(modules[item.name], copied)
