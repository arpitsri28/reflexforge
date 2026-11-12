"""No bind mounts or host execution of task code. All uploaded files are data."""

import base64
import threading
import time
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

import docker

from reflexforge.schema import CommandResult

MAX_FILE = 512_000
MAX_OUTPUT = 64_000


class SandboxError(RuntimeError):
    pass


class InvalidPatchError(ValueError):
    pass


class SandboxTimeout(SandboxError):
    pass


UPLOAD = r"""
import base64, os, pathlib, sys
root, name, encoded, append, protected = sys.argv[1:]
root = pathlib.Path(root)
p = root / name
if not p.resolve().is_relative_to(root): raise ValueError('path escapes staging directory')
p.parent.mkdir(parents=True, exist_ok=True)
flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | (os.O_APPEND if append == '1' else os.O_TRUNC)
fd = os.open(p, flags, 0o644)
with os.fdopen(fd, 'wb') as file: file.write(base64.b64decode(encoded, validate=True))
if protected == '1': os.chmod(p, 0o444)
"""

READ = r"""
import base64, os, pathlib, stat, sys
p = pathlib.Path('/workspace') / sys.argv[1]
if not p.resolve().is_relative_to('/workspace'): raise ValueError('path escapes workspace')
fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
with os.fdopen(fd, 'rb') as file:
    info = os.fstat(file.fileno())
    if not stat.S_ISREG(info.st_mode) or info.st_size > 512000:
        raise ValueError('source must be a bounded regular file')
    content = file.read(512001)
    if len(content) > 512000: raise ValueError('source too large')
    print(base64.b64encode(content).decode())
"""


class DockerSandbox:
    def __init__(self, image: str, seconds: int, command_seconds: int, client: Any = None) -> None:
        self.owns_client = client is None
        try:
            self.client = client if client is not None else docker.from_env(timeout=10)
        except docker.errors.DockerException as exc:
            raise SandboxError(f"Docker connection failed: {exc}") from exc
        self.image = image
        self.seconds = seconds
        self.command_seconds = command_seconds
        self.container: Any = None
        self.timer: threading.Timer | None = None
        self.expired = threading.Event()
        self.deadline = 0.0

    def __enter__(self) -> "DockerSandbox":
        try:
            self.container = self.client.containers.create(
                self.image,
                network_disabled=True,
                read_only=True,
                user="1000:1000",
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                privileged=False,
                mem_limit="512m",
                memswap_limit="512m",
                nano_cpus=1_000_000_000,
                pids_limit=64,
                working_dir="/workspace",
                tmpfs={
                    "/workspace": "rw,nosuid,nodev,size=64m,uid=1000,gid=1000,mode=0700",
                    "/tmp": "rw,nosuid,nodev,size=32m,mode=1777",
                    "/evaluation": "rw,nosuid,nodev,size=4m,uid=0,gid=0,mode=0755",
                },
            )
            self.container.start()
            self.deadline = time.monotonic() + self.seconds
            self.timer = threading.Timer(self.seconds, self._expire)
            self.timer.daemon = True
            self.timer.start()
            return self
        except Exception as exc:
            self.close()
            raise SandboxError(f"container startup failed: {exc}") from exc

    def _expire(self) -> None:
        self.expired.set()
        container = self.container
        if container is None:
            return
        try:
            container.kill()
        except docker.errors.NotFound:
            pass
        except docker.errors.APIError:
            # close() still force-removes the container; caller receives timeout.
            pass

    def check(self) -> None:
        if self.expired.is_set() or time.monotonic() >= self.deadline:
            raise SandboxTimeout("sandbox execution deadline exceeded")

    def upload(self, files: dict[str, str], *, evaluation: bool = False) -> None:
        # Exec sees the live tmpfs. Docker's archive API does not reliably do so.
        for name, content in files.items():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError("unsafe staging path")
            data = content.encode()
            if len(data) > MAX_FILE:
                raise ValueError("file exceeds size limit")
            chunks = [data[i : i + 24000] for i in range(0, len(data), 24000)] or [b""]
            for index, chunk in enumerate(chunks):
                result = self.execute(
                    [
                        "python",
                        "-I",
                        "-c",
                        UPLOAD,
                        "/evaluation" if evaluation else "/workspace",
                        name,
                        base64.b64encode(chunk).decode(),
                        "1" if index else "0",
                        "1" if evaluation and index == len(chunks) - 1 else "0",
                    ],
                    _user="0:0" if evaluation else "1000:1000",
                )
                if result.exit_code:
                    raise SandboxError(f"staging failed: {result.output}")

    def execute(
        self, argv: list[str], *, _user: str = "1000:1000", _limit: int = MAX_OUTPUT
    ) -> CommandResult:
        self.check()
        command_timer = threading.Timer(
            min(self.command_seconds, max(0.01, self.deadline - time.monotonic())),
            self._expire,
        )
        command_timer.daemon = True
        command_timer.start()
        try:
            execution = self.client.api.exec_create(
                self.container.id, argv, user=_user, workdir="/workspace"
            )
            chunks: list[bytes] = []
            size = 0
            for chunk in self.client.api.exec_start(execution["Id"], stream=True):
                size += len(chunk)
                if size > _limit:
                    self._expire()
                    raise SandboxError("command output exceeded limit; sandbox terminated")
                chunks.append(chunk)
            self.check()
            status = self.client.api.exec_inspect(execution["Id"])["ExitCode"]
            if status is None:
                raise SandboxError("execution ended without an exit code")
            return CommandResult(exit_code=status, output=b"".join(chunks).decode(errors="replace"))
        except docker.errors.DockerException as exc:
            self.check()
            raise SandboxError(f"Docker execution failed: {exc}") from exc
        finally:
            command_timer.cancel()

    def shell(self, command: str) -> CommandResult:
        return self.execute(["/bin/sh", "-c", command])

    def read(self, name: str) -> str:
        """Snapshot a bounded regular file through the live container namespace."""
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("unsafe file path")
        result = self.execute(["python", "-I", "-c", READ, name], _limit=MAX_FILE * 2)
        if result.exit_code:
            raise InvalidPatchError(f"source snapshot failed: {result.output}")
        try:
            return base64.b64decode(result.output.strip(), validate=True).decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise InvalidPatchError("source snapshot is not valid UTF-8") from exc

    def close(self) -> None:
        if self.timer:
            self.timer.cancel()
        try:
            if self.container is not None:
                try:
                    self.container.remove(force=True, v=True)
                except docker.errors.NotFound:
                    pass
                finally:
                    self.container = None
        finally:
            if self.owns_client:
                self.client.close()

    def __exit__(self, *args: object) -> None:
        self.close()


SandboxFactory = Callable[[int, int], DockerSandbox]
