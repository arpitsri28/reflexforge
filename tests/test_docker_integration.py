"""Real sandbox tests, never execute fixture source on the host."""

import os

import pytest
from conftest import ROOT

from reflexforge.evaluation.evaluator import Evaluator, make_patch
from reflexforge.sandbox.manager import DockerSandbox, SandboxTimeout
from reflexforge.tasks import fixture_files, load_tasks

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.getenv("REFLEXFORGE_DOCKER_TESTS") != "1",
        reason="set REFLEXFORGE_DOCKER_TESTS=1 after building image",
    ),
]


def factory(seconds, command):
    return DockerSandbox(
        os.getenv("REFLEXFORGE_IMAGE", "reflexforge-sandbox:local"), seconds, command
    )


FIXED = [
    "def first(items, n):\n    return items[:n]\n",
    "def paginate(items, page, size):\n    start = (page - 1) * size\n    return items[start:start + size]\n",
    'def enabled(records):\n    return [r for r in records if r.get("enabled", False)]\n',
]


@pytest.mark.parametrize("index", range(3))
def test_known_defect_then_independent_repaired_patch(index):
    task, directory = sorted(load_tasks(ROOT / "tasks"), key=lambda t: t[0].id)[index]
    original = fixture_files(task, directory)
    hidden = (directory / task.hidden_test).read_text()
    evaluator = Evaluator(factory)
    assert (
        evaluator.evaluate(
            task, original, make_patch(original, {}, task.editable), hidden
        ).exit_code
        != 0
    )
    with factory(30, 10) as box:
        box.upload(original)
        assert box.shell(task.reproduction).exit_code != 0
        assert box.shell("test ! -f /evaluation/hidden.py").exit_code == 0
        box.upload({"solution.py": FIXED[index]})
        assert box.shell(task.reproduction).exit_code == 0
        patch = make_patch(original, {"solution.py": box.read("solution.py")}, task.editable)
    assert evaluator.evaluate(task, original, patch, hidden).exit_code == 0


def test_permissions_network_and_cleanup():
    with factory(30, 10) as box:
        container = box.container
        assert box.shell("id -u").output.strip() == "1000"
        assert box.shell("touch /root-write-test").exit_code != 0
        box.upload({"hidden.py": 'print("protected")'}, evaluation=True)
        assert box.shell("echo bad > /evaluation/hidden.py").exit_code != 0
        assert box.shell("rm /evaluation/hidden.py").exit_code != 0
        assert box.shell("test ! -S /var/run/docker.sock").exit_code == 0
        assert (
            box.shell(
                "python -c 'import socket; socket.create_connection((\"1.1.1.1\", 443), 1)'"
            ).exit_code
            != 0
        )
    import docker

    with pytest.raises(docker.errors.NotFound):
        container.reload()


def test_command_timeout_removes_container():
    with pytest.raises(SandboxTimeout):
        with factory(10, 1) as box:
            container = box.container
            box.shell("sleep 30")
    import docker

    with pytest.raises(docker.errors.NotFound):
        container.reload()
