# Sandbox threat model and limitations

The host-side controller owns API credentials, configuration, task metadata, traces, and
SQLite. Task code is untrusted and runs only in Linux Docker containers. The controller
never imports fixture modules or executes task setup on the host. Docker itself and the
sandbox image are trusted.

No task container receives host bind mounts, host networking, privileged mode, devices,
API keys, experiment storage, or the Docker socket. Task and tool processes run as UID
1000 with all Linux capabilities dropped and privilege escalation disabled. The root
filesystem is read-only. `/workspace` (64 MiB), `/tmp` (32 MiB), and `/evaluation` (4 MiB)
are explicit tmpfs mounts. Memory, swap, CPU, process count, command output, source size,
and time are bounded. All container lifecycle operations use the Docker SDK.

The controller stages ordinary files through constant Python programs executed in the
container. Path arguments and file bytes are separate argv entries, never interpolated
into shell commands. Base64 chunks keep argv sizes bounded. This accesses the live tmpfs
without Docker archive extraction or untrusted archive parsing on the host. Workspace
staging uses UID 1000. Hidden-test staging uses a trusted root exec in the pristine
independent evaluator container; files are root-owned and changed to mode 0444 after the
last chunk. `/evaluation` is root-owned mode 0755. Task setup and evaluation still run
as UID 1000. No worker request can select an exec user.

Only source paths designated in a trusted task manifest are exported. Snapshotting uses
`O_NOFOLLOW`, regular-file checks, bounded reads, and UTF-8 validation; symlink snapshots
are rejected. Changes to visible tests, shell-created files, and task workspace state
are discarded. The fresh evaluator uses its own original fixture, repeats setup, and
loads the authoritative hidden tests. Source replacement is validated again before use.

Docker shares the host/VM kernel and is not a strong boundary against kernel or runtime
vulnerabilities. Use a patched, dedicated Docker daemon and trusted, pinned images for
serious experiments. The current Dockerfile has a floating base tag; pin its digest when
freezing an experiment. This is a debugging-agent research prototype, not a hardened
multi-tenant execution service.

The evaluator protects hidden tests against file modification by the task user. It does
not make those tests secret from hostile code executing in the same evaluator process:
code can inspect readable files, monkeypatch Python, or deliberately terminate a process.
A malicious patch could spoof test success. These small deterministic fixtures assume
non-adversarial repairs. Higher-assurance evaluation needs an out-of-process oracle and
an authenticated result protocol with separate identities. Do not use current scores as
a security claim about adversarial submissions.

Normal exceptions, Ctrl-C, and command timeouts remove containers through context-manager
cleanup. SIGKILL, daemon failure, or host failure cannot guarantee cleanup; inspect Docker
manually after such failures. Automatic orphan reaping and recovery of `running` database
rows are future work. Docker request timeouts and model transport timeouts can also add
controller cleanup latency beyond the task's execution deadline.

Logs redact configured environment values whose names contain KEY, TOKEN, SECRET,
PASSWORD, or CREDENTIAL, plus recognizable OpenAI key strings. This is best-effort
redaction, not a full secret scanner; do not put credentials into fixtures or issue text.
The worker never receives the controller's environment. Trace directories are host-side
research data and may contain proprietary code or natural-language content.

Official interface references used for this implementation:

- [OpenAI function-call lifecycle](https://developers.openai.com/api/docs/guides/function-calling)
- [Docker SDK container options](https://docker-py.readthedocs.io/en/stable/containers.html)
- [Moby container archive behavior](https://github.com/moby/moby/blob/master/daemon/archive_unix.go)
