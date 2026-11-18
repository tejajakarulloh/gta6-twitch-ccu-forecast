"""GTA VI Launch-Day Twitch CCU Forecaster.

An empirical kernel-weighted comparable launch curve forecaster for make.fun's
'Forecast GTA VI's launch-day Twitch viewers hour by hour' bounty.
"""

import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure directory is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z_BASELINE = [-1.645, -0.674, 0.0, 0.674, 1.645]
SIGMA_BASELINE = 0.15


def round2(x: float) -> float | int:
    """Round to 2 decimals, half up, matching JS Math.round(x * 100) / 100."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    val = whole / 100
    return int(val) if val.is_integer() else val


def extract_curve(comp: dict) -> dict[int, float]:
    """Extract hour 1..24 viewer counts from comparable game data."""
    day_start = comp.get("day_start")
    hourly = comp.get("hourly", [])
    if not day_start or not hourly:
        return {}
    res = {}
    try:
        t_start = datetime.fromisoformat(day_start.replace("Z", "+00:00"))
        for h in hourly:
            f = h.get("from")
            if f:
                t_curr = datetime.fromisoformat(f.replace("Z", "+00:00"))
                diff_hours = int((t_curr - t_start).total_seconds() // 3600) + 1
                if 1 <= diff_hours <= 24:
                    res[diff_hours] = float(h.get("viewers", 0))
    except Exception:
        return {}
    return res


def forecast_case(case: dict, name: str) -> dict:
    if case.get("levels") != LEVELS:
        raise ValueError(f"{name} asks for levels {case.get('levels')}, expected {LEVELS}")

    known = case.get("known", [])
    first = next((k for k in known if k.get("hour") == 1), None)
    if first is None:
        raise ValueError(f"{name} has no hour-1 print")
    p1 = max(1.0, float(first.get("viewers", 1)))

    # Process comparables
    comparables = case.get("comparables", [])
    curves = []
    for c in comparables:
        crv = extract_curve(c)
        if 1 in crv and crv[1] > 0 and len(crv) >= 12:
            curves.append({
                "name": c.get("name"),
                "p1": crv[1],
                "curve": crv,
                "is_console_rolling": "rolling" in str(c.get("unlock", "")).lower() or "midnight local" in str(c.get("unlock", "")).lower()
            })

    target_is_console_rolling = "rolling" in str(case.get("notes", "")).lower() or "midnight local" in str(case.get("notes", "")).lower()

    forecast_rows = []
    for row in case.get("forecast", []):
        h = int(row["hour"])

        # Gather comparable log ratios for hour h
        pairs = []
        for c in curves:
            if h in c["curve"]:
                r = c["curve"][h] / max(1.0, c["p1"])
                lr = math.log(max(1e-4, r))
                scale_diff = abs(math.log(p1) - math.log(c["p1"]))
                w = math.exp(-0.5 * (scale_diff / 1.1) ** 2)
                # Boost comparables with similar unlock mechanism (rolling console midnight)
                if c["is_console_rolling"] == target_is_console_rolling:
                    w *= 1.25
                pairs.append((lr, w))

        if len(pairs) >= 5:
            pairs.sort(key=lambda x: x[0])
            total_w = sum(p[1] for p in pairs)
            qs = []
            for tau in LEVELS:
                target_w = tau * total_w
                cum = 0.0
                q_lr = pairs[-1][0]
                for lr, w in pairs:
                    cum += w
                    if cum >= target_w:
                        q_lr = lr
                        break
                qs.append(max(1.0, min(1e9, p1 * math.exp(q_lr))))
        else:
            # Fallback to random-walk persistence
            qs = [max(1.0, min(1e9, p1 * math.exp(z * SIGMA_BASELINE * math.sqrt(h - 1)))) for z in Z_BASELINE]

        # Enforce strict monotonicity and reasonable bounds
        for i in range(1, len(qs)):
            if qs[i] < qs[i - 1]:
                qs[i] = qs[i - 1]

        rounded_q = [round2(q) for q in qs]
        forecast_rows.append({"hour": h, "q": rounded_q})

    return {"hours": forecast_rows}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Process case files in deterministic name order
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        out_path = OUTPUT_DIR / f"{path.stem}.out"
        out_path.write_text(json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
