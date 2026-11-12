import importlib.util
from pathlib import Path
assert Path("/evaluation/hidden.py").is_file()
spec = importlib.util.spec_from_file_location("solution", "/workspace/solution.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
assert m.first([1, 2, 3], 2) == [1, 2]
assert m.first([1], 0) == []
assert m.first([], 3) == []
