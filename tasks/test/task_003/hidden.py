import importlib.util
from pathlib import Path
assert Path("/evaluation/hidden.py").is_file()
spec = importlib.util.spec_from_file_location("solution", "/workspace/solution.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
assert m.enabled([{"enabled": False}, {"enabled": True}, {}]) == [{"enabled": True}]
assert m.enabled([]) == []
assert m.enabled([{"enabled": True, "id": 1}, {"enabled": True, "id": 2}]) == [{"enabled": True, "id": 1}, {"enabled": True, "id": 2}]
