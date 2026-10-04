"""OpenRouter Batch lane for OFFLINE work only (backend U11, W15).

Recipe proposals, the weekly learn pass and judge runs may be deferred by
hours; they go through here at batch prices. This module must never be
imported by the live turn path (pipeline, brain, routing, act, ipc, the
daemon loop): tests/test_batch.py enforces that structurally.

Wire shape (mirrors Pace-Server internal/openrouter/batch/client.go,
commit 3e4ff060, UNVERIFIED against the live OpenRouter API; Pace marks
it "to confirm against staging" too):
    POST {base}/batches            JSONL body, one request per line
         {"custom_id","method":"POST","url":"/v1/chat/completions","body"}
         headers: Authorization: Bearer <key>, Idempotency-Key: <job id>
    GET  {base}/batches/{id}       {"id","status","request_counts"}
    GET  {base}/batches/{id}/results   JSONL, one per custom_id
    POST {base}/batches/{id}/cancel
Statuses: validating, in_progress, completed, failed, expired, cancelled.

Spend: the model must be on the cheap allowlist (plain slug, price at or
under the repo ceiling, never anthropic/). Before submit the job's
estimated cost, plus the estimates of jobs still in flight, must fit under
the W14 daily and monthly caps; otherwise the submit is refused and
nothing is sent or recorded. Actual cost is recorded in the ledger per
succeeded item when results arrive. Estimates use realtime prices (no
batch discount assumed). An unreadable ledger refuses the submit.

State lives in DATA_DIR/batch/<job_id>.json (no key, atomic writes), so
polling resumes after a restart and a resubmit of the same job id reuses
the same Idempotency-Key. Failed items are reported, never retried on the
realtime path.
"""
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import config, ledger, learn

BASE_URL = "https://openrouter.ai/api/v1"
CEILING = (1.60, 4.80)           # USD per Mtok in/out, repo price ceiling
DENY_PREFIXES = ("anthropic/",)
ALLOWED = tuple(sorted(
    m for m, (pin, pout) in ledger.PRICES.items()
    if pin <= CEILING[0] and pout <= CEILING[1]
    and not m.startswith(DENY_PREFIXES)))
TERMINAL = ("completed", "failed", "expired", "cancelled")
DEFAULT_MODEL = "meta-llama/llama-4-scout"
_JOB_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class BatchRefused(Exception):
    """Refused locally, before any request. `code` is stable."""

    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"openrouter batch: HTTP {status}: {message}")

    @property
    def temporary(self) -> bool:
        return self.status in (0, 429) or self.status >= 500


def allowed(model: str) -> bool:
    return (model or "").strip() in ALLOWED


def estimate_usd(model: str, items: list, max_tokens: int) -> float:
    """Upper-ish bound: ~3 chars per prompt token, every item may use all
    of max_tokens. Priced at realtime rates (unknown model = max price)."""
    tin = sum(len(json.dumps(i.get("messages", []))) // 3 + 8
              for i in items)
    return ledger.price(model, tin, len(items) * int(max_tokens))


class Client:
    """Thin stdlib client. The key is fetched per call and never stored,
    logged, or placed in an error message."""

    def __init__(self, base=BASE_URL, key_fn=None, timeout=60):
        self.base = (base or BASE_URL).rstrip("/")
        self.key_fn = key_fn or config.load_api_key
        self.timeout = timeout

    def _do(self, method, path, body=None, headers=None, limit=32 << 20):
        try:
            key = self.key_fn()
        except Exception:  # noqa: BLE001
            key = ""
        if not key:
            raise BatchRefused("no_key", "no OpenRouter key")
        from . import brain
        h = {**brain.app_headers(self.base), **(headers or {}),
             "Authorization": "Bearer " + key}
        req = urllib.request.Request(self.base + path, data=body,
                                     headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read(limit + 1)
        except urllib.error.HTTPError as e:
            msg = e.read(2000).decode("utf-8", "replace").replace(
                key, "[REDACTED]")
            try:
                msg = json.loads(msg)["error"]["message"]
            except Exception:  # noqa: BLE001
                pass
            raise ApiError(e.code, msg[:300]) from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise ApiError(0, "transport error") from None
        if len(raw) > limit:
            raise ApiError(0, "response exceeds size bound")
        return raw

    def submit(self, model, items, idempotency_key, max_tokens=0) -> dict:
        lines = []
        for it in items:
            body = {"model": model, "messages": it["messages"]}
            if max_tokens:
                body["max_tokens"] = int(max_tokens)
            lines.append(json.dumps({
                "custom_id": it["custom_id"], "method": "POST",
                "url": "/v1/chat/completions", "body": body}))
        h = {"Content-Type": "application/x-ndjson"}
        if idempotency_key:
            h["Idempotency-Key"] = idempotency_key
        raw = self._do("POST", "/batches",
                       ("\n".join(lines) + "\n").encode(), h, 1 << 20)
        return _parse_batch(raw)

    def get(self, bid) -> dict:
        return _parse_batch(self._do("GET", f"/batches/{_q(bid)}",
                                     limit=1 << 20))

    def cancel(self, bid) -> dict:
        return _parse_batch(self._do("POST", f"/batches/{_q(bid)}/cancel",
                                     limit=1 << 20))

    def results(self, bid) -> list:
        raw = self._do("GET", f"/batches/{_q(bid)}/results")
        out = []
        for ln in raw.decode("utf-8", "replace").splitlines():
            if not ln.strip():
                continue
            try:
                d = json.loads(ln)
                cid = d["custom_id"]
            except (ValueError, KeyError, TypeError):
                raise ApiError(0, "unparseable results line") from None
            out.append(_parse_result(cid, d))
        return out


def _q(s):
    return urllib.request.quote(str(s), safe="")


def _parse_batch(raw: bytes) -> dict:
    try:
        d = json.loads(raw)
        bid, st = str(d["id"]), str(d["status"])
    except (ValueError, KeyError, TypeError):
        raise ApiError(0, "unparseable batch response") from None
    c = d.get("request_counts") or {}
    return {"id": bid, "status": st, "total": c.get("total", 0),
            "completed": c.get("completed", 0), "failed": c.get("failed", 0)}


def _parse_result(cid, d) -> dict:
    r = {"custom_id": cid, "content": "", "cost": None, "in": 0, "out": 0,
         "error": ""}
    resp = d.get("response")
    if isinstance(d.get("error"), dict):
        r["error"] = str(d["error"].get("message") or "item error")[:300]
    elif not isinstance(resp, dict):
        r["error"] = "no response"
    else:
        body = resp.get("body") or {}
        choices = body.get("choices") or []
        if (resp.get("status_code") or 0) >= 400 or (
                not choices and not resp.get("status_code")):
            msg = (body.get("error") or {}).get("message", "http error")
            r["error"] = f"status {resp.get('status_code')}: {msg}"[:300]
        else:
            if choices:
                r["content"] = (choices[0].get("message") or {}).get(
                    "content", "") or ""
            u = body.get("usage") or {}
            r["in"] = int(u.get("prompt_tokens") or 0)
            r["out"] = int(u.get("completion_tokens") or 0)
            r["cost"] = u.get("cost")
    return r


class Lane:
    """Job lifecycle over a Client, persisted under DATA_DIR/batch."""

    def __init__(self, cfg: dict, client=None):
        self.cfg = cfg or {}
        self.client = client

    # -- state ------------------------------------------------------------
    def _dir(self):
        return config.DATA_DIR / "batch"

    def _file(self, job_id):
        if not _JOB_RE.match(job_id or ""):
            raise BatchRefused("bad_job_id", "job ids are [A-Za-z0-9._-]")
        return self._dir() / f"{job_id}.json"

    def _load(self, job_id):
        try:
            return json.loads(self._file(job_id).read_text())
        except FileNotFoundError:
            return None

    def _save(self, job):
        f = self._file(job["job_id"])
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(job, indent=1))
        os.replace(tmp, f)

    def status(self, job_id=None):
        """One job dict (None if unknown) or every job, newest first."""
        if job_id:
            return self._load(job_id)
        jobs = []
        try:
            for f in self._dir().glob("*.json"):
                try:
                    jobs.append(json.loads(f.read_text()))
                except ValueError:
                    continue
        except OSError:
            pass
        return sorted(jobs, key=lambda j: j.get("created", ""),
                      reverse=True)

    def reserved(self, exclude=None) -> float:
        return round(sum(j.get("est_usd", 0.0) for j in self.status()
                         if not j.get("settled")
                         and j["job_id"] != exclude), 8)

    # -- cap check --------------------------------------------------------
    def _check_cap(self, est, job_id):
        try:
            st = ledger.status(self.cfg)
        except Exception:  # noqa: BLE001
            raise BatchRefused("ledger_unreadable",
                               "cannot read the usage ledger") from None
        if st["blocked"]:
            raise BatchRefused("budget_exceeded", st["reason"])
        extra = est + self.reserved(exclude=job_id)
        for spent, cap, name in ((st["today_usd"], st["cap_usd"], "daily"),
                                 (st["month_usd"], st["monthly_cap_usd"],
                                  "monthly")):
            if cap is not None and spent + extra > cap:
                raise BatchRefused(
                    "budget_exceeded",
                    f"{name} cap ${cap:.2f}: spent ${spent:.4f} + "
                    f"batch ${extra:.4f}")

    # -- verbs ------------------------------------------------------------
    def submit(self, job_id, kind, model, items, max_tokens=600):
        model = (model or "").strip()
        if not allowed(model):
            raise BatchRefused("model_not_allowed", model or "(empty)")
        if not items:
            raise BatchRefused("no_items", "nothing to submit")
        job = self._load(job_id)
        if job and job.get("remote_id"):
            return job                      # already submitted: idempotent
        est = estimate_usd(model, items, max_tokens)
        self._check_cap(est, job_id)
        if job is None:
            job = {"job_id": job_id, "kind": kind, "model": model,
                   "max_tokens": int(max_tokens), "items": items,
                   "est_usd": round(est, 8), "status": "submitting",
                   "remote_id": None, "settled": False, "failed": {},
                   "recorded": [], "applied": False,
                   "created": datetime.now(timezone.utc).isoformat()}
        self._save(job)
        try:
            b = self.client.submit(model, job["items"], job_id,
                                   job["max_tokens"])
        except ApiError as e:
            if not e.temporary:         # provider said no: free the reserve
                job.update(status="rejected", settled=True,
                           error=e.message)
                self._save(job)
            raise
        job.update(remote_id=b["id"], status=b["status"])
        self._save(job)
        return job

    def poll(self, job_id, apply=None):
        job = self._load(job_id)
        if job is None:
            raise BatchRefused("unknown_job", job_id)
        if job["settled"] or not job.get("remote_id"):
            return job
        b = self.client.get(job["remote_id"])
        job["status"] = b["status"]
        if b["status"] in TERMINAL:
            self._settle(job, apply)
        self._save(job)
        return job

    def poll_all(self, apply_for=None):
        out = []
        for j in self.status():
            if j["settled"] or not j.get("remote_id"):
                continue
            ap = apply_for(j) if apply_for else None
            out.append(self.poll(j["job_id"], ap))
        return out

    def cancel(self, job_id, apply=None):
        job = self._load(job_id)
        if job is None:
            raise BatchRefused("unknown_job", job_id)
        if job["settled"]:
            return job
        if not job.get("remote_id"):
            job.update(status="cancelled", settled=True)
            self._save(job)
            return job
        job["status"] = self.client.cancel(job["remote_id"])["status"]
        self._settle(job, apply)
        self._save(job)
        return job

    def _settle(self, job, apply):
        """Record spend for each succeeded item exactly once, collect
        failures, apply the good results once, then mark settled."""
        try:
            results = self.client.results(job["remote_id"])
        except ApiError as e:
            if e.temporary and job["status"] != "cancelled":
                raise
            results = []
        seen, ok = set(), {}
        for r in results:
            seen.add(r["custom_id"])
            if r["error"]:
                job["failed"][r["custom_id"]] = r["error"]
                continue
            ok[r["custom_id"]] = r["content"]
            if r["custom_id"] not in job["recorded"]:
                ledger.record("openrouter", job["model"], r["in"], r["out"],
                              usd=r["cost"], paid=True)
                job["recorded"].append(r["custom_id"])
                self._save(job)
        for it in job["items"]:
            if it["custom_id"] not in seen:
                job["failed"].setdefault(it["custom_id"],
                                         "no result from provider")
        ledger.publish()
        if apply and ok and not job["applied"]:
            apply(job, ok)
        job["applied"] = True
        job["settled"] = True


# -- offline consumers ------------------------------------------------------

def _week(now=None):
    y, w, _ = (now or datetime.now(timezone.utc)).isocalendar()
    return f"{y}-W{w:02d}"


def learn_items(recs: list) -> list:
    lines = "\n".join(
        f"- heard {r.get('heard')!r}, picked {r.get('picked')}, assistant "
        f"said app={(r.get('jev_said') or {}).get('app')}" for r in recs)
    prompt = ("These are this week's voice-assistant corrections. For each "
              "picked target suggest one short criteria cue (a phrase the "
              "router should associate with it). Plain list, no preamble.\n"
              + lines)
    return [{"custom_id": "learn-cues",
             "messages": [{"role": "user", "content": prompt}]}]


def submit_learn(lane: Lane, model=None, days=7,
                 corrections_file=config.CORRECTIONS):
    """Submit this ISO week's learn pass. None when there is nothing to
    learn from. The job id is the week, so a second call is a no-op."""
    recs = learn.recent(days, corrections_file)
    if not recs:
        return None
    model = model or lane.cfg.get("batch", {}).get("model", DEFAULT_MODEL)
    return lane.submit(f"learn-{_week()}", "learn", model,
                       learn_items(recs), max_tokens=500)


def applier(out_dir=None):
    """Default `apply` for learn jobs: stage a human-reviewed proposal
    file. Nothing auto-applies (learn.approve stays human-gated)."""
    out_dir = out_dir or learn.PROPOSALS_DIR

    def apply(job, ok):
        out_dir.mkdir(parents=True, exist_ok=True)
        name = job["job_id"].removeprefix("learn-")
        body = "\n\n".join(ok.values())
        (out_dir / f"{name}-batch.md").write_text(
            f"# Wisp learn proposal (batch, {job['model']}) {name}\n\n"
            f"{body}\n\nReview, then `learn.approve` what you keep.\n",
            encoding="utf-8")
    return apply
