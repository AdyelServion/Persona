"""Engagement / outbound analytics from the Events collection (read-only).

Usage:
    python scripts/engagement_report.py               # last 7 days
    python scripts/engagement_report.py --days 30 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from persona_runtime.db import COLLECTION_NAMES, get_db  # noqa: E402
from persona_runtime.db.time_utils import utcnow  # noqa: E402

EVENT_TYPES = (
    "user_created",
    "proactive_evaluated",
    "proactive_skipped",
    "proactive_interval_selected",
    "proactive_quiet_queued",
    "proactive_duplicate_prevented",
    "proactive_scheduled",
    "proactive_sent",
    "proactive_replied",
    "proactive_ignored",
    "proactive_suppressed",
    "proactive_cancelled",
    "proactive_blocked",
    "proactive_opt_out",
    "proactive_settings_changed",
    "memory_deleted",
)


def build_report(db, *, days: float = 7.0) -> dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    events = list(
        db[COLLECTION_NAMES["events"]].find(
            {"event_type": {"$in": list(EVENT_TYPES)}, "created_at": {"$gte": since}},
            {"_id": 0},
        )
    )
    counts = Counter(e["event_type"] for e in events)
    by_type: dict[str, Counter] = defaultdict(Counter)
    suppressed: Counter = Counter()
    cancelled: Counter = Counter()
    skipped: Counter = Counter()
    intervals: list[int] = []
    bubbles: list[int] = []
    for e in events:
        if e["event_type"] == "proactive_skipped":
            skipped[e.get("reason") or "unknown"] += 1
        if e["event_type"] == "proactive_interval_selected" and e.get("minutes"):
            intervals.append(int(e["minutes"]))
        if e["event_type"] in {"proactive_sent", "proactive_replied"} and e.get("proactive_type"):
            by_type[e["proactive_type"]][e["event_type"]] += 1
        if e["event_type"] == "proactive_suppressed":
            suppressed[e.get("reason") or "unknown"] += 1
        if e["event_type"] == "proactive_cancelled":
            cancelled[e.get("reason") or "unknown"] += 1
        if e["event_type"] == "proactive_sent" and e.get("bubbles"):
            bubbles.append(int(e["bubbles"]))

    sent = counts["proactive_sent"]
    replied = counts["proactive_replied"]
    settings_col = db[COLLECTION_NAMES["proactive_settings"]]
    return {
        "window_days": days,
        "since": since.isoformat(),
        "counts": {t: counts.get(t, 0) for t in EVENT_TYPES},
        "reply_rate": round(replied / sent, 3) if sent else None,
        "avg_bubbles_per_outbound": round(sum(bubbles) / len(bubbles), 2) if bubbles else None,
        "by_proactive_type": {
            t: {
                "sent": c["proactive_sent"],
                "replied": c["proactive_replied"],
                "reply_rate": round(c["proactive_replied"] / c["proactive_sent"], 3) if c["proactive_sent"] else None,
            }
            for t, c in sorted(by_type.items())
        },
        "suppressed_reasons": dict(suppressed.most_common()),
        "skipped_reasons": dict(skipped.most_common()),
        "interval_minutes_selected": intervals,
        "cancelled_reasons": dict(cancelled.most_common()),
        "users": {
            "total": db[COLLECTION_NAMES["app_users"]].count_documents({}),
            "opted_in": settings_col.count_documents({"enabled": True}),
            "awaiting_reply": settings_col.count_documents({"unanswered_outbound_id": {"$ne": None}}),
            "auto_paused": settings_col.count_documents({"opt_out_reason": "auto_paused_no_engagement"}),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=float, default=7.0)
    parser.add_argument("--json", action="store_true", help="print raw JSON")
    args = parser.parse_args()
    report = build_report(get_db(), days=args.days)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0
    print(f"Engagement report — last {args.days:g} days")
    for name, value in report["counts"].items():
        print(f"  {name:28s} {value}")
    print(f"  reply rate                   {report['reply_rate']}")
    print(f"  avg bubbles per outbound     {report['avg_bubbles_per_outbound']}")
    for t, row in report["by_proactive_type"].items():
        print(f"  {t:28s} sent={row['sent']} replied={row['replied']} rate={row['reply_rate']}")
    if report["suppressed_reasons"]:
        print(f"  suppressed: {report['suppressed_reasons']}")
    if report["cancelled_reasons"]:
        print(f"  cancelled:  {report['cancelled_reasons']}")
    print(f"  users: {report['users']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
