"""Optional bounded local polling; checkpoints persist outside this loop."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable


@dataclass(frozen=True)
class WaitPolicy:
    total_seconds: float
    max_polls: int = 20
    initial_interval: float = 2
    backoff: float = 1.5
    max_interval: float = 30

    def __post_init__(self):
        for name, value in (("total_seconds", self.total_seconds), ("initial_interval", self.initial_interval), ("backoff", self.backoff), ("max_interval", self.max_interval)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name}必须是有限数字")
        if not 0 < self.total_seconds <= 3600:
            raise ValueError("等待总时限必须大于0且不超过3600秒")
        if isinstance(self.max_polls, bool) or not isinstance(self.max_polls, int) or not 1 <= self.max_polls <= 1000:
            raise ValueError("轮询次数上限必须为1至1000的整数")
        if not 0 <= self.initial_interval <= self.max_interval <= 60 or not 1 <= self.backoff <= 10:
            raise ValueError("退避需满足0<=初始间隔<=最大间隔<=60秒，倍率1至10")


def run_with_wait(engine, storyboard: dict, *, max_jobs: int | None = None,
                  policy: WaitPolicy | None = None, checkpoint: Callable[[dict], None] | None = None,
                  clock=time.monotonic, sleep=time.sleep) -> dict:
    """Advance one job per round, retaining provider IDs on all wait exits.

    The deadline covers video advancement/polling, not the later render. Network
    operations have their own bounded timeouts. There is no background wakeup.
    """
    if policy is not None and max_jobs not in (None, 0):
        raise ValueError("有界等待不能同时使用非零max_jobs；请用max_polls限制状态请求，或取消等待后按镜头数推进")
    if policy is None or max_jobs == 0:
        result = engine.run(storyboard, max_jobs=max_jobs)
        if checkpoint:
            checkpoint(result)
        return result
    start = clock()
    deadline = start + policy.total_seconds
    remaining = policy.max_polls
    rounds = 0
    interval = policy.initial_interval
    terminal = {"failed", "retry_exhausted", "artifact_invalid", "submission_unknown", "blocked"}
    while True:
        result = engine.run(storyboard, max_jobs=1, deadline=deadline, poll_budget=remaining)
        rounds += 1
        used = result.get("wait_limits", {}).get("polls_used", 0)
        remaining -= used
        elapsed = max(0, clock() - start)
        statuses = {job["status"] for job in result["jobs"]}
        reason = ("completed" if result["all_succeeded"] else "operator_attention" if statuses & terminal
                  else "deadline" if clock() >= deadline or result.get("wait_limits", {}).get("deadline_reached")
                  else "poll_limit" if remaining <= 0 else "no_progress" if used == 0 else "waiting")
        result["wait"] = {"enabled": True, "reason": reason, "elapsed_seconds": round(elapsed, 6),
                          "total_seconds": policy.total_seconds, "max_polls": policy.max_polls,
                          "polls_used": policy.max_polls - remaining, "rounds": rounds,
                          "initial_interval": policy.initial_interval, "backoff": policy.backoff,
                          "max_interval": policy.max_interval, "background_service": False}
        if checkpoint:
            checkpoint(result)
        if reason != "waiting":
            return result
        delay = min(interval, max(0, deadline - clock()))
        if delay:
            sleep(delay)
        interval = min(policy.max_interval, interval * policy.backoff)
        # A final engine call at the deadline is safe: it must checkpoint without
        # submitting/polling. It also returns a complete view of all planned jobs.
