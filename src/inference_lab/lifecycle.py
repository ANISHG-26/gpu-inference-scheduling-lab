"""Local, bounded lifecycle controller for the CPU inference lab."""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import time
import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit


MIN_TTL_MINUTES = 30
MAX_TTL_MINUTES = 240
MAX_PULUMI_SECONDS = 20 * 60
RUN_ID_RE = re.compile(r"^[0-9a-f]{12}$")
LABELS = {"managed-by": "inference-lab"}


class LabError(RuntimeError):
    """A safe, user-facing lifecycle failure."""


@dataclass(frozen=True)
class LabConfig:
    project_id: str
    zone: str
    foundation_stack: str
    session_stack: str
    ttl_minutes: int
    node_count: int

    @classmethod
    def load(cls, path: Path) -> "LabConfig":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise LabError(f"Missing private lab config: {path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise LabError(f"Cannot read lab config: {path}") from exc
        if not isinstance(raw, dict):
            raise LabError("Lab config must be a JSON object")
        required = ("project_id", "zone", "foundation_stack", "session_stack", "ttl_minutes", "node_count")
        missing = [key for key in required if key not in raw]
        if missing:
            raise LabError(f"Lab config is missing: {', '.join(missing)}")
        for key in ("project_id", "zone", "foundation_stack", "session_stack"):
            if not isinstance(raw[key], str) or not raw[key].strip():
                raise LabError(f"{key} must be a non-empty string")
            value = raw[key].strip()
            if value.startswith("-") or not re.fullmatch(r"[A-Za-z0-9._/-]+", value):
                raise LabError(f"{key} contains characters unsafe for Pulumi or cloud resource arguments")
            if key in ("project_id", "zone") and "/" in value:
                raise LabError(f"{key} must be a single cloud resource identifier")
            if key in ("foundation_stack", "session_stack") and any(
                part.startswith("-") for part in value.split("/")
            ):
                raise LabError(f"{key} contains an option-like Pulumi stack component")
        ttl = raw["ttl_minutes"]
        count = raw["node_count"]
        if type(ttl) is not int or not MIN_TTL_MINUTES <= ttl <= MAX_TTL_MINUTES:
            raise LabError(f"ttl_minutes must be between {MIN_TTL_MINUTES} and {MAX_TTL_MINUTES}")
        if type(count) is not int or count not in (1, 2):
            raise LabError("node_count must be 1 or 2")
        return cls(*(raw[key].strip() for key in required[:4]), ttl, count)


class Pulumi:
    """Thin argv-only wrapper; no shell interpolation is used."""

    def __init__(self, cwd: Path, timeout: int = MAX_PULUMI_SECONDS, runner: Callable[..., Any] = subprocess.run):
        self.cwd = cwd
        self.timeout = min(timeout, MAX_PULUMI_SECONDS)
        self.runner = runner

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            result = self.runner(
                ["pulumi", *args], cwd=self.cwd, capture_output=True, text=True,
                timeout=self.timeout, check=False,
            )
        except FileNotFoundError as exc:
            raise LabError("Pulumi CLI is required to manage the lab") from exc
        except subprocess.TimeoutExpired as exc:
            raise LabError("Pulumi command exceeded the 20 minute safety limit") from exc
        if check and result.returncode:
            # Provider output can contain account details; keep it off the console.
            raise LabError("Pulumi command failed; provider output was suppressed")
        return result

    def outputs(self, stack: str) -> dict[str, Any]:
        result = self.run("stack", "output", "--json", "--stack", stack)
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise LabError("Pulumi returned invalid stack outputs") from exc
        if not isinstance(value, dict):
            raise LabError("Pulumi outputs must be a JSON object")
        return value

    def existing_outputs(self, stack: str) -> dict[str, Any] | None:
        result = self.run("stack", "output", "--json", "--stack", stack, check=False)
        if result.returncode:
            detail = (result.stderr or result.stdout).lower()
            if "no stack named" in detail or "stack not found" in detail or "no stack selected" in detail:
                return None
            raise LabError(f"Cannot safely inspect Pulumi stack {stack}")
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise LabError("Pulumi returned invalid stack outputs") from exc
        if not isinstance(value, dict):
            raise LabError("Pulumi outputs must be a JSON object")
        return value

    def config_set(self, stack: str, key: str, value: str) -> None:
        self.run("config", "set", key, value, "--stack", stack)

    def up(self, stack: str) -> None:
        self.run("up", "--yes", "--stack", stack)

    def destroy(self, stack: str) -> None:
        self.run("destroy", "--yes", "--stack", stack)

    def refresh(self, stack: str) -> None:
        self.run("refresh", "--yes", "--stack", stack)


def required_labels(run_id: str, expires_at: int) -> dict[str, str]:
    return {**LABELS, "lab-run": run_id, "lab-expiry": str(expires_at)}


def write_exclusive_json(path: Path, record: Mapping[str, Any]) -> None:
    """Create one private, durable intent file; never replace an existing run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def read_record(path: Path) -> dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LabError("No local lab session record exists") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise LabError("The local lab session record is unreadable") from exc
    if not isinstance(record, dict):
        raise LabError("The local lab session record is invalid")
    return record


class CloudTasks:
    """Register an authenticated expiry request using lazily imported cloud deps."""

    def __init__(self, http_session: Any | None = None):
        self.http_session = http_session

    def create_expiry_task(self, project_id: str, location: str, queue_id: str,
                           url: str, invoker: str, payload: Mapping[str, Any],
                           schedule_at: int, task_id: str) -> str:
        session = self.http_session
        if session is None:
            try:
                import google.auth
                from google.auth.transport.requests import AuthorizedSession
            except ImportError as exc:
                raise LabError("Install the optional cloud dependencies to start a session") from exc
            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            session = AuthorizedSession(credentials)
        parent = f"projects/{project_id}/locations/{location}/queues/{queue_id}"
        task = {
            "name": f"{parent}/tasks/{task_id}",
            "scheduleTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(schedule_at)),
            "httpRequest": {
                "httpMethod": "POST", "url": url,
                "headers": {"Content-Type": "application/json"},
                "body": base64.b64encode(json.dumps(payload).encode()).decode(),
                "oidcToken": {
                    "serviceAccountEmail": invoker,
                    "audience": f"{urlsplit(url).scheme}://{urlsplit(url).netloc}",
                },
            },
        }
        try:
            response = session.post(
                f"https://cloudtasks.googleapis.com/v2/{parent}/tasks",
                json={"task": task}, timeout=30,
            )
        except Exception as exc:
            raise LabError("Cloud Tasks registration request failed") from exc
        if response.status_code == 409:
            try:
                existing = session.get(f"https://cloudtasks.googleapis.com/v2/{task['name']}?responseView=FULL", timeout=30)
            except Exception as exc:
                raise LabError("Existing Cloud Task verification request failed") from exc
            if existing.status_code != 200:
                raise LabError(f"Existing Cloud Task could not be verified (HTTP {existing.status_code})")
            try:
                existing_task = existing.json()
            except Exception as exc:
                raise LabError("Existing Cloud Task returned invalid data") from exc
            if not self._same_task(existing_task, task):
                raise LabError("An existing Cloud Task with this name has different expiry details")
            return task["name"]
        if not response.ok:
            raise LabError(f"Cloud Tasks registration failed with HTTP {response.status_code}")
        try:
            created = response.json()
        except Exception as exc:
            raise LabError("Cloud Tasks returned invalid creation data") from exc
        if not isinstance(created, dict) or created.get("name") != task["name"]:
            raise LabError("Cloud Tasks returned a different task name than requested")
        return created["name"]

    @staticmethod
    def _same_task(existing: Any, requested: Mapping[str, Any]) -> bool:
        if not isinstance(existing, dict):
            return False
        actual_http = existing.get("httpRequest")
        wanted_http = requested["httpRequest"]
        if not isinstance(actual_http, dict):
            return False
        actual_oidc = actual_http.get("oidcToken")
        wanted_oidc = wanted_http["oidcToken"]
        return (
            existing.get("name") == requested["name"] and
            existing.get("scheduleTime") == requested["scheduleTime"] and
            actual_http.get("httpMethod") == wanted_http["httpMethod"] and
            actual_http.get("url") == wanted_http["url"] and
            actual_http.get("body") == wanted_http["body"] and
            isinstance(actual_oidc, dict) and
            actual_oidc.get("serviceAccountEmail") == wanted_oidc["serviceAccountEmail"] and
            actual_oidc.get("audience") == wanted_oidc["audience"]
        )


class CloudGke:
    def labels(self, project_id: str, zone: str, cluster_name: str) -> dict[str, str]:
        labels = self.labels_or_absent(project_id, zone, cluster_name)
        if labels is None:
            raise LabError("Cannot verify live GKE cluster ownership (cluster is absent)")
        return labels

    def labels_or_absent(self, project_id: str, zone: str, cluster_name: str) -> dict[str, str] | None:
        try:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
        except ImportError as exc:
            raise LabError("Install the optional cloud dependencies to stop a session") from exc
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        from urllib.parse import quote
        url = ("https://container.googleapis.com/v1/projects/" + quote(project_id, safe="") + "/locations/" +
               quote(zone, safe="") + "/clusters/" + quote(cluster_name, safe=""))
        response = AuthorizedSession(credentials).get(url, timeout=20)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise LabError(f"Cannot verify live GKE cluster ownership (HTTP {response.status_code})")
        try:
            data = response.json()
        except Exception as exc:
            raise LabError("GKE returned invalid cluster data") from exc
        labels = data.get("resourceLabels") if isinstance(data, dict) else None
        if not isinstance(labels, dict):
            raise LabError("GKE cluster has no ownership labels")
        return {str(key): str(value) for key, value in labels.items()}


class LabController:
    def __init__(self, root: Path, *, pulumi: Pulumi | None = None,
                 foundation_pulumi: Pulumi | None = None,
                 pulumi_factory: Callable[[Path], Pulumi] = Pulumi,
                 task_client: CloudTasks | None = None, gke: CloudGke | None = None,
                 clock: Callable[[], float] = time.time,
                 run_id_factory: Callable[[], str] | None = None):
        self.root = root.resolve()
        self.private_dir = self.root / ".lab"
        self.config_path = self.private_dir / "config.json"
        self.record_dir = self.private_dir / "sessions"
        self.stopped_dir = self.private_dir / "stopped"
        self.lock_path = self.private_dir / "start.lock"
        self.config = LabConfig.load(self.config_path)
        self.pulumi = pulumi or pulumi_factory(self.root / "infra" / "session")
        self.foundation_pulumi = foundation_pulumi or (
            pulumi if pulumi is not None else pulumi_factory(self.root / "infra" / "foundation")
        )
        self.task_client = task_client or CloudTasks()
        self.gke = gke or CloudGke()
        self.clock = clock
        self.run_id_factory = run_id_factory or (lambda: secrets.token_hex(6))

    def _record_path(self, run_id: str) -> Path:
        return self.record_dir / f"{run_id}.json"

    def _assert_no_active_records(self) -> None:
        if not self.record_dir.exists():
            return
        for path in self.record_dir.glob("*.json"):
            record = read_record(path)
            run_id = record.get("run_id")
            if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
                raise LabError(f"Invalid run ownership record: {path.name}")
            if (record.get("project_id") != self.config.project_id or
                    record.get("cluster_name") != f"inference-lab-{run_id}" or
                    type(record.get("expires_at")) is not int):
                raise LabError(f"Invalid run ownership record: {path.name}")
            if (self.stopped_dir / f"{run_id}.marker").exists():
                continue
            expiry = int(record["expires_at"])
            if int(self.clock()) < expiry + 30 * 60:
                raise LabError("A previous session may still be active or within its expiry retry window")
            labels = self.gke.labels_or_absent(record["project_id"], record["zone"], record["cluster_name"])
            if labels is not None and all(
                labels.get(key) == value for key, value in required_labels(run_id, expiry).items()
            ):
                raise LabError("A previous owned GKE cluster is still active")
            if labels is not None:
                raise LabError("A cluster with a previous session name has mismatched ownership labels")

    @staticmethod
    def _task_location(zone: str) -> str:
        return re.sub(r"-[a-z]$", "", zone)

    def _foundation(self) -> dict[str, Any]:
        outputs = self.foundation_pulumi.outputs(self.config.foundation_stack)
        expected = ("projectId", "zone", "networkId", "subnetId", "nodeServiceAccount",
                    "expiryUrl", "taskQueueId", "taskInvokerServiceAccount")
        absent = [key for key in expected if not outputs.get(key)]
        if absent:
            raise LabError(f"Foundation stack is missing required outputs: {', '.join(absent)}")
        if outputs["projectId"] != self.config.project_id or outputs["zone"] != self.config.zone:
            raise LabError("Foundation stack project or zone does not match private lab config")
        return outputs

    def plan(self) -> dict[str, Any]:
        now = int(self.clock())
        return {
            "project_id": self.config.project_id,
            "zone": self.config.zone,
            "foundation_stack": self.config.foundation_stack,
            "session_stack": self.config.session_stack,
            "ttl_minutes": self.config.ttl_minutes,
            "node_count": self.config.node_count,
            "expires_at": now + self.config.ttl_minutes * 60,
            "cluster_name_prefix": "inference-lab-",
            "ttl_bounds_minutes": [MIN_TTL_MINUTES, MAX_TTL_MINUTES],
            "node_count_bounds": [1, 2],
        }

    def start(self) -> dict[str, Any]:
        self.private_dir.mkdir(parents=True, exist_ok=True)
        try:
            lock_fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise LabError("Another lab start is in progress; remove start.lock only after confirming it is stale") from exc
        try:
            with os.fdopen(lock_fd, "w", encoding="ascii") as lock:
                lock.write(str(os.getpid()))
                lock.flush()
            self._assert_no_active_records()
            # Existing outputs indicate that this stack still owns a session.
            current = self.pulumi.existing_outputs(self.config.session_stack)
            current = current or {}
            if current.get("runId"):
                raise LabError("A session already exists in the configured Pulumi stack; stop it first")
            if current:
                raise LabError("Configured Pulumi session stack has state without a recognized runId")

            foundation = self._foundation()
            run_id = self.run_id_factory()
            if not RUN_ID_RE.fullmatch(run_id):
                raise LabError("Run ID generator returned an invalid identifier")
            expires_at = int(self.clock()) + self.config.ttl_minutes * 60
            cluster_name = f"inference-lab-{run_id}"
            record = {
                "version": 1, "project_id": self.config.project_id, "zone": self.config.zone,
                "foundation_stack": self.config.foundation_stack,
                "session_stack": self.config.session_stack, "run_id": run_id,
                "cluster_name": cluster_name, "expires_at": expires_at,
                "node_count": self.config.node_count,
            }
            path = self._record_path(run_id)
            write_exclusive_json(path, record)
            task_payload = {"project_id": self.config.project_id, "zone": self.config.zone,
                            "run_id": run_id, "cluster_name": cluster_name, "expires_at": expires_at}
            # The task is guaranteed to exist before Pulumi can create billable resources.
            task_name = self.task_client.create_expiry_task(
                self.config.project_id, self._task_location(self.config.zone), str(foundation["taskQueueId"]),
                str(foundation["expiryUrl"]), str(foundation["taskInvokerServiceAccount"]),
                task_payload, expires_at, f"expire-{run_id}",
            )
            for key, value in {
                "lab:projectId": self.config.project_id, "lab:zone": self.config.zone,
                "lab:runId": run_id, "lab:expiresAt": str(expires_at),
                "lab:nodeCount": str(self.config.node_count),
                "lab:foundationStack": self.config.foundation_stack,
            }.items():
                self.pulumi.config_set(self.config.session_stack, key, value)
            remaining = expires_at - int(self.clock())
            if remaining <= 0:
                raise LabError("Session TTL expired before Pulumi could create resources")
            self.pulumi.timeout = min(MAX_PULUMI_SECONDS, remaining)
            self.pulumi.up(self.config.session_stack)
            outputs = self.pulumi.outputs(self.config.session_stack)
            self._verify_outputs(outputs, record)
            if int(self.clock()) >= expires_at:
                raise LabError("Session TTL expired while Pulumi was creating resources")
            # The intent is immutable. Task name is reproducible and can be derived from run_id.
            return {**record, "expiry_task": task_name, "status": "running"}
        finally:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _verify_outputs(outputs: Mapping[str, Any], record: Mapping[str, Any]) -> None:
        expected = {"projectId": record["project_id"], "zone": record["zone"],
                    "clusterName": record["cluster_name"], "runId": record["run_id"],
                    "expiresAt": record["expires_at"]}
        for key, value in expected.items():
            if outputs.get(key) != value and str(outputs.get(key)) != str(value):
                raise LabError(f"Session stack output {key} does not match this run")

    def status(self) -> dict[str, Any]:
        outputs = self.pulumi.existing_outputs(self.config.session_stack)
        if outputs is None or not outputs:
            return {"status": "absent"}
        return {"status": "present", "outputs": outputs}

    def stop(self) -> dict[str, Any]:
        outputs = self.pulumi.existing_outputs(self.config.session_stack)
        if outputs is None or not outputs:
            markers = sorted(self.stopped_dir.glob("*.marker"), key=lambda path: path.stat().st_mtime, reverse=True)
            if markers:
                run_id = markers[0].stem
                record = read_record(self._record_path(run_id))
                if markers[0].read_text(encoding="ascii").strip() != run_id:
                    raise LabError("Stopped-session marker does not match its local run record")
                return {"status": "stopped", "run_id": run_id, "cluster_name": record["cluster_name"]}
            raise LabError("No session outputs or stopped-session marker exist; refusing to destroy")
        run_id = outputs.get("runId")
        if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
            raise LabError("Session stack has no valid runId output; refusing to destroy")
        record = read_record(self._record_path(run_id))
        self._verify_outputs(outputs, record)
        expected = required_labels(run_id, int(record["expires_at"]))
        live_labels = self.gke.labels_or_absent(record["project_id"], record["zone"], record["cluster_name"])
        if live_labels is not None and any(live_labels.get(key) != value for key, value in expected.items()):
            raise LabError("Live GKE cluster labels do not match the local ownership record")
        if live_labels is None:
            self.pulumi.refresh(self.config.session_stack)
            refreshed = self.pulumi.outputs(self.config.session_stack)
            self._verify_outputs(refreshed, record)
        self.pulumi.destroy(self.config.session_stack)
        self.stopped_dir.mkdir(parents=True, exist_ok=True)
        marker = self.stopped_dir / f"{run_id}.marker"
        try:
            with marker.open("x", encoding="ascii") as stream:
                stream.write(f"{run_id}\n")
        except FileExistsError:
            if marker.read_text(encoding="ascii").strip() != run_id:
                raise LabError("Stopped-session marker belongs to a different run")
        return {"status": "stopped", "run_id": run_id, "cluster_name": record["cluster_name"]}


def default_root() -> Path:
    return Path.cwd()


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="inference-lab")
    parser.add_argument("command", choices=("plan", "start", "stop", "status"))
    parser.add_argument("--root", type=Path, default=default_root())
    args = parser.parse_args(argv)
    try:
        controller = LabController(args.root)
        if args.command == "plan":
            result = controller.plan()
        elif args.command == "start":
            result = controller.start()
        elif args.command == "stop":
            result = controller.stop()
        else:
            result = controller.status()
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except LabError as exc:
        print(f"inference-lab: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
