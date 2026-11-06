"""Pure structural validation for lesson 03 evidence; this cannot establish acceptance."""

import math


def _fail(message):
    raise ValueError(message)


def _record(value, name):
    if not isinstance(value, dict):
        _fail(f"{name} must be an object")
    return value


def _positive_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{name} must be a positive finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value <= 0:
        _fail(f"{name} must be a positive finite number")
    return value


def _positive_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _fail(f"{name} must be a positive integer")
    return value


def validate(evidence):
    """Validate normalized evidence and return structural status only.

    Expected keys: lesson_id, run_id, owner, source, provenance, expires_at,
    jobs (three registrations), cancellation, and queued/released/finished snapshots.
    """
    data = _record(evidence, "evidence")
    if data.get("lesson_id") != "03":
        _fail("lesson_id must be 03")
    run_id, owner = data.get("run_id"), data.get("owner")
    if not isinstance(run_id, str) or not run_id.strip() or not isinstance(owner, str) or not owner.strip():
        _fail("run_id and owner must be nonempty strings")
    source = data.get("source")
    if source not in ("fixture", "live"):
        _fail("source must be fixture or live")
    provenance = _record(data.get("provenance"), "provenance")
    if not isinstance(provenance.get("source"), str) or not provenance["source"].strip():
        _fail("provenance.source must be nonempty")
    if source == "live" and any(not isinstance(provenance.get(k), str) or not provenance[k].strip()
                                 for k in ("cluster_uid", "worker_uid", "collector")):
        _fail("live provenance requires cluster_uid, worker_uid, and collector")
    expiry = _positive_number(data.get("expires_at"), "expires_at")

    jobs = data.get("jobs")
    if not isinstance(jobs, list) or len(jobs) != 3:
        _fail("exactly three registered jobs are required")
    registered = {}
    for job in jobs:
        job = _record(job, "job")
        jid = _positive_int(job.get("job_id"), "job_id")
        if jid in registered:
            _fail("job IDs must be unique")
        if job.get("run_id") != run_id or job.get("owner") != owner or job.get("lesson_id") != "03":
            _fail("job ownership/run/lesson mismatch")
        if _positive_int(job.get("cpus"), "cpus") != 1:
            _fail("each job must request one CPU")
        limit = _positive_int(job.get("time_limit_seconds"), "time_limit_seconds")
        if limit > 60:
            _fail("time limit must not exceed 60 seconds")
        registered[jid] = job

    cancellation = _record(data.get("cancellation"), "cancellation")
    target = _positive_int(cancellation.get("job_id"), "cancellation.job_id")
    if target not in registered or cancellation.get("run_id") != run_id or cancellation.get("owner") != owner:
        _fail("cancellation must identify a registered lesson job owned by this run")
    canceled_at = _positive_number(cancellation.get("recorded_at"), "cancellation.recorded_at")

    snapshots = data.get("snapshots")
    stages = ("queued", "released", "finished")
    if not isinstance(snapshots, list) or len(snapshots) != 3:
        _fail("exactly queued, released, and finished snapshots are required")
    observed = []
    by_stage = {}
    for snapshot, stage in zip(snapshots, stages):
        snapshot = _record(snapshot, "snapshot")
        if snapshot.get("stage") != stage:
            _fail("snapshots must be chronological queued/released/finished")
        at = _positive_number(snapshot.get("observed_at"), "observed_at")
        if at >= expiry or (observed and at <= observed[-1]):
            _fail("snapshot timestamps must increase and occur before expiry")
        observed.append(at)
        entries = snapshot.get("jobs")
        if not isinstance(entries, list) or len(entries) != 3:
            _fail("each snapshot must contain exactly the three registered jobs")
        states = {}
        total = 0
        for entry in entries:
            entry = _record(entry, "snapshot job")
            jid = _positive_int(entry.get("job_id"), "snapshot job_id")
            if jid not in registered or jid in states:
                _fail("snapshot contains a foreign or duplicate job ID")
            state, cpus = entry.get("state"), entry.get("allocated_cpus")
            if state not in ("PENDING", "RUNNING", "CANCELLED", "COMPLETED"):
                _fail("unsupported or malformed job state")
            cpus = cpus if not isinstance(cpus, bool) and isinstance(cpus, int) and cpus >= 0 else -1
            if cpus < 0:
                _fail("allocated_cpus must be a nonnegative integer")
            if cpus > 1:
                _fail("a one-CPU job cannot allocate more than one CPU")
            if (state == "RUNNING" and cpus != 1) or (state != "RUNNING" and cpus != 0):
                _fail("allocation does not match observed job state")
            total += cpus
            states[jid] = (state, cpus)
        if total > 2:
            _fail("observed allocations exceed the two-slot limit")
        by_stage[stage] = states

    queued, released, finished = (by_stage[s] for s in stages)
    if sum(state == "RUNNING" for state, _ in queued.values()) != 2 or sum(state == "PENDING" for state, _ in queued.values()) != 1:
        _fail("queued snapshot must show two running and one pending job")
    pending = next(jid for jid, (state, _) in queued.items() if state == "PENDING")
    running = {jid for jid, (state, _) in queued.items() if state == "RUNNING"}
    if target not in running or not observed[0] <= canceled_at <= observed[1]:
        _fail("cancellation must target an initially running job between queued and released observations")
    if released[target] != ("CANCELLED", 0) or released[pending] != ("RUNNING", 1):
        _fail("released snapshot must show cancellation and pending job starting")
    if any(released[jid] not in (("RUNNING", 1), ("COMPLETED", 0)) for jid in running - {target}):
        _fail("other initially running jobs must remain running or complete")
    if finished[target] != ("CANCELLED", 0) or any(finished[jid] != ("COMPLETED", 0) for jid in registered if jid != target):
        _fail("finished snapshot must show cancellation retained and all other jobs completed")
    return {"structurally_valid": True, "source": source}
