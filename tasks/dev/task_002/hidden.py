import importlib.util
from pathlib import Path
assert Path("/evaluation/hidden.py").is_file()
spec = importlib.util.spec_from_file_location("solution", "/workspace/solution.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
assert m.paginate([1, 2, 3, 4], 1, 2) == [1, 2]
assert m.paginate([1, 2, 3], 2, 2) == [3]
assert m.paginate([], 1, 5) == []
