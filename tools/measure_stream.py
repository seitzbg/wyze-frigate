#!/usr/bin/env python3
"""Measure what a consumer of a camera stream actually receives.

One ffmpeg decode pass. For every decoded video frame it records when the
frame arrived (monotonic clock) and the frame's presentation timestamp.

Arrival gaps are what Frigate sees. PTS gaps come from the stream's own
timestamps, which go2rtc rewrites. A camera-side stall can arrive as a
delivery gap with continuous timestamps, so both are judged. Neither can see
camera-side frame counters; go2rtc's verbose logs are the place for that.
"""
from __future__ import annotations

import argparse
import json
import queue
import re
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field

__version__ = "1.0.0"

FRAME_RE = re.compile(r"\bn:\s*\d+\s+pts:\s*\S+\s+pts_time:(\S+).*?\bs:(\d+)x(\d+)")
LEVEL_RE = re.compile(r"\[(warning|error|fatal)\]")
# The null muxer that ends the measurement pipeline. Its complaints are about
# repeated timestamps reaching the output, not about decoding.
OUTPUT_MUXER_RE = re.compile(r"^\[null @ ")
INPUT_RE = re.compile(r"\bInput #0\b")
VIDEO_RE = re.compile(r"\bStream #0:\d+\S*: Video:")
URL_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s'\"]+", re.I)
SECRET_RE = re.compile(r"\b(uid|enr|mac)=[^&\s'\"]+", re.I)
IPV4_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")

SMALL_GAP = 0.150
BIG_GAP = 0.500


@dataclass
class Frame:
    arrival: float          # seconds since ffmpeg started
    pts: float | None       # pts_time in seconds, None when absent
    width: int
    height: int


@dataclass
class Capture:
    frames: list[Frame] = field(default_factory=list)
    warnings: list[tuple[float, str]] = field(default_factory=list)   # (arrival, line)
    errors: list[tuple[float, str]] = field(default_factory=list)
    input_opened: bool = False
    has_video: bool = False
    exited: bool = False    # ffmpeg ended on its own before the deadline
    end: float = 0.0        # seconds since start when the capture stopped


def redact(text: str) -> str:
    """Remove stream URLs, IPv4 addresses and Wyze uid/enr/mac values."""
    text = SECRET_RE.sub(r"\1=<redacted>", text)
    text = URL_RE.sub("<url>", text)
    return IPV4_RE.sub("<ip>", text)


def _float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def parse_line(line: str, t: float, cap: Capture) -> None:
    """Fold one ffmpeg stderr line, received at time t, into the capture."""
    if "showinfo" in line:
        m = FRAME_RE.search(line)
        if m:
            cap.frames.append(Frame(t, _float(m.group(1)), int(m.group(2)), int(m.group(3))))
        return
    if INPUT_RE.search(line):
        cap.input_opened = True
    if VIDEO_RE.search(line):
        cap.has_video = True
    level = LEVEL_RE.search(line)
    if level:
        harness = OUTPUT_MUXER_RE.match(line)
        target = cap.warnings if level.group(1) == "warning" or harness else cap.errors
        target.append((t, redact(line.strip())))


def build_command(ffmpeg: str, url: str) -> list[str]:
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-loglevel", "level+info"]
    if url.startswith(("rtsp://", "rtsps://")):
        cmd += ["-rtsp_transport", "tcp"]
    return cmd + ["-i", url, "-map", "0:v:0", "-vf", "showinfo", "-f", "null", "-"]


def capture(cmd: list[str], duration: float, warmup: float, connect_timeout: float) -> Capture:
    """Run ffmpeg until warmup + duration after the first frame, or connect_timeout without one."""
    cap = Capture()
    start = time.monotonic()
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, text=True, errors="replace")
    lines: queue.Queue = queue.Queue()

    def pump() -> None:
        for line in proc.stderr:
            lines.put((time.monotonic() - start, line))
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    try:
        while True:
            deadline = (cap.frames[0].arrival + warmup + duration) if cap.frames else connect_timeout
            remaining = deadline - (time.monotonic() - start)
            if remaining <= 0:
                break
            try:
                item = lines.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            if item is None:
                cap.exited = True
                break
            parse_line(item[1], item[0], cap)
    finally:
        cap.end = time.monotonic() - start
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    return cap


def _gaps(values: list[float]) -> list[float]:
    return [b - a for a, b in zip(values, values[1:])]


def summarize(cap: Capture, duration: float, warmup: float, expect: str | None = None) -> dict:
    """Judge the frames and decoder messages in [first frame + warmup, + duration].

    Decoder errors before the window are reported but do not fail the run:
    joining a live H.264 stream mid-GOP logs errors until the first keyframe.
    """
    result: dict = {"warmup_s": warmup}
    if not cap.frames:
        result.update(decode_errors=len(cap.errors), decode_warnings=len(cap.warnings),
                      error_samples=[m for _, m in cap.errors[:5]])
        if cap.exited and cap.input_opened and not cap.has_video:
            outcome = "no-video"
        elif cap.exited:
            outcome = "connect-failed"
        else:
            outcome = "no-frames"
        result.update(outcome=outcome, frames=0, verdict="FAIL", reasons=[outcome])
        return result

    start = cap.frames[0].arrival + warmup
    complete = not cap.exited
    end = start + duration if complete else max(cap.end, start)
    window = [f for f in cap.frames if start <= f.arrival <= end]
    errors = [m for t, m in cap.errors if start <= t <= end]
    arrivals = [f.arrival for f in window]
    # Edge gaps count too: a stall at the start or end of the window is a stall.
    arrival_gaps = _gaps(arrivals)
    if arrivals:
        arrival_gaps.append(arrivals[0] - start)
        if complete:
            arrival_gaps.append(end - arrivals[-1])
    elif complete:
        arrival_gaps.append(duration)
    pts_steps = _gaps([f.pts for f in window if f.pts is not None])
    pts_gaps = [g for g in pts_steps if g > 0]
    sizes = Counter(f"{f.width}x{f.height}" for f in window)
    span = end - start

    result.update(
        outcome="complete" if complete else "early-eof",
        window_s=round(span, 3),
        frames=len(window),
        resolution=sizes.most_common(1)[0][0] if sizes else None,
        resolutions=dict(sizes),
        delivered_fps=round(len(window) / span, 2) if span > 0 else 0.0,
        nominal_fps=round(1 / statistics.median(pts_gaps), 2) if pts_gaps else None,
        arrival_gap_max_s=round(max(arrival_gaps), 3) if arrival_gaps else None,
        arrival_gaps_over_150ms=sum(g > SMALL_GAP for g in arrival_gaps),
        arrival_gaps_over_500ms=sum(g > BIG_GAP for g in arrival_gaps),
        pts_gap_max_s=round(max(pts_gaps), 3) if pts_gaps else None,
        pts_gaps_over_150ms=sum(g > SMALL_GAP for g in pts_gaps),
        pts_gaps_over_500ms=sum(g > BIG_GAP for g in pts_gaps),
        pts_backwards=sum(g < 0 for g in pts_steps),
        pts_repeats=sum(g == 0 for g in pts_steps),
        decode_errors=len(errors),
        decode_errors_warmup=sum(t < start for t, _ in cap.errors),
        decode_warnings=sum(start <= t <= end for t, _ in cap.warnings),
        error_samples=errors[:5],
    )
    reasons = []
    if not complete:
        reasons.append(f"stream ended after {span:.1f} s of the {duration:.0f} s window")
    if not window:
        reasons.append("no frames inside the measurement window")
    if result["arrival_gap_max_s"] and result["arrival_gap_max_s"] > BIG_GAP:
        reasons.append(f"delivery stalled for {result['arrival_gap_max_s']:.2f} s")
    if result["pts_gap_max_s"] and result["pts_gap_max_s"] > BIG_GAP:
        reasons.append(f"timestamp gap of {result['pts_gap_max_s']:.2f} s")
    if errors:
        reasons.append(f"{len(errors)} decoder errors")
    if len(sizes) > 1:
        reasons.append("resolution changed during the window")
    if expect and result["resolution"] != expect:
        reasons.append(f"resolution {result['resolution']}, expected {expect}")
    result.update(verdict="FAIL" if reasons else "PASS", reasons=reasons)
    return result


def exit_code(result: dict) -> int:
    """0 PASS, 1 measured but FAIL, 2 nothing measured."""
    if result["verdict"] == "PASS":
        return 0
    return 1 if result.get("frames") else 2


def _seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f} s"


def render(r: dict) -> str:
    if not r.get("frames"):
        lines = [f"outcome      {r['outcome']}"] + [f"error        {e}" for e in r["error_samples"]]
        return "\n".join(lines + [f"verdict      FAIL: {'; '.join(r['reasons'])}"])
    nominal = f"{r['nominal_fps']:.2f}/s" if r["nominal_fps"] else "unknown"
    sizes = "" if len(r["resolutions"]) == 1 else f"  {r['resolutions']}"
    lines = [
        f"outcome      {r['outcome']} ({r['window_s']:.1f} s measured after {r['warmup_s']:.0f} s warmup)",
        f"resolution   {r['resolution']}{sizes}",
        f"frames       {r['frames']} decoded, {r['delivered_fps']:.2f}/s delivered, {nominal} nominal",
        f"arrival gaps max {_seconds(r['arrival_gap_max_s'])}; >150 ms: {r['arrival_gaps_over_150ms']};"
        f" >500 ms: {r['arrival_gaps_over_500ms']}",
        f"pts gaps     max {_seconds(r['pts_gap_max_s'])}; >150 ms: {r['pts_gaps_over_150ms']};"
        f" >500 ms: {r['pts_gaps_over_500ms']}; backwards: {r['pts_backwards']};"
        f" repeated: {r['pts_repeats']}",
        f"decoder      {r['decode_errors']} errors, {r['decode_warnings']} warnings"
        f" ({r['decode_errors_warmup']} errors during warmup, not counted)",
    ]
    lines += [f"error        {e}" for e in r["error_samples"]]
    lines.append(f"verdict      {r['verdict']}" + (f": {'; '.join(r['reasons'])}" if r["reasons"] else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("url", help="stream URL, e.g. rtsp://BRIDGE_HOST:8554/front_door")
    p.add_argument("--duration", type=float, default=300,
                   help="seconds to measure after warmup (default 300)")
    p.add_argument("--warmup", type=float, default=10,
                   help="seconds after the first frame to ignore (default 10)")
    p.add_argument("--connect-timeout", type=float, default=30,
                   help="seconds to wait for the first frame (default 30)")
    p.add_argument("--expect", metavar="WxH", help="fail unless the stream has this resolution")
    p.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg binary (default: ffmpeg on PATH)")
    p.add_argument("--json", action="store_true", help="print JSON instead of text")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    a = p.parse_args(argv)
    try:
        cap = capture(build_command(a.ffmpeg, a.url), a.duration, a.warmup, a.connect_timeout)
    except FileNotFoundError:
        print(f"ffmpeg not found: {a.ffmpeg}", file=sys.stderr)
        return 2
    result = summarize(cap, a.duration, a.warmup, a.expect)
    print(json.dumps(result, indent=2) if a.json else render(result))
    return exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
