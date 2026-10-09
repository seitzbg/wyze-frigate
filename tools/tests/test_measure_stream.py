"""Tests for measure_stream.

Unit tests drive summarize() with synthetic frame timelines. Integration
tests (skipped without ffmpeg) push real ffmpeg output through a local TCP
relay that can pause delivery, so the tool is checked against the failure it
exists to catch: a stall that leaves timestamps continuous.
"""
import contextlib
import io
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import measure_stream as ms  # noqa: E402

FFMPEG9 = ("[Parsed_showinfo_0 @ 0x7646] [info] n:   3 pts:      3 pts_time:0.15    "
           "duration:      1 duration_time:0.05    fmt:yuv420p cl:unspecified sar:1/1 "
           "s:2304x1296 i:P iskey:0 type:P checksum:EBA70FF3")
FFMPEG5 = ("[Parsed_showinfo_0 @ 0x55aa] [info] n:   0 pts:      0 pts_time:0       "
           "pos:      564 fmt:yuv420p sar:1/1 s:320x240 i:P iskey:1 type:I checksum:1")


def frames(times, pts=None, size=(320, 240)):
    pts = times if pts is None else pts
    return [ms.Frame(t, p, *size) for t, p in zip(times, pts)]


def cap_with(fr, end, exited=False):
    return ms.Capture(frames=fr, input_opened=True, has_video=True, exited=exited, end=end)


def clean_times():
    """20 fps for 12 s. With warmup 2 and duration 10 the window is [2, 12]."""
    return [i * 0.05 for i in range(241)]


class ParseTests(unittest.TestCase):
    def test_frame_line_ffmpeg9(self):
        cap = ms.Capture()
        ms.parse_line(FFMPEG9, 1.0, cap)
        self.assertEqual(cap.frames, [ms.Frame(1.0, 0.15, 2304, 1296)])

    def test_frame_line_ffmpeg5(self):
        cap = ms.Capture()
        ms.parse_line(FFMPEG5, 2.5, cap)
        self.assertEqual(cap.frames, [ms.Frame(2.5, 0.0, 320, 240)])

    def test_color_line_is_not_a_frame(self):
        cap = ms.Capture()
        ms.parse_line("[Parsed_showinfo_0 @ 0x1] [info] color_range:unknown color_space:unknown", 1.0, cap)
        self.assertEqual(cap.frames, [])

    def test_input_and_video_stream_detected(self):
        cap = ms.Capture()
        ms.parse_line("[info] Input #0, rtsp, from 'rtsp://10.0.0.5:8554/cam':", 0.1, cap)
        self.assertTrue(cap.input_opened)
        self.assertFalse(cap.has_video)
        ms.parse_line("[info]   Stream #0:0: Video: h264 (High), yuv420p, 2304x1296", 0.1, cap)
        self.assertTrue(cap.has_video)

    def test_levels_collected_with_time(self):
        cap = ms.Capture()
        ms.parse_line("[h264 @ 0x1] [error] left block unavailable for requested intra mode", 1.0, cap)
        ms.parse_line("[null @ 0x2] [warning] Non-monotonic DTS; previous: 5, current: 4", 2.0, cap)
        self.assertEqual([t for t, _ in cap.errors], [1.0])
        self.assertEqual([t for t, _ in cap.warnings], [2.0])

    def test_output_muxer_messages_are_not_decoder_errors(self):
        # The null muxer at the end of the measurement pipeline complains when
        # two frames share a timestamp. The video itself decoded fine.
        cap = ms.Capture()
        ms.parse_line("[null @ 0x5754] [error] Application provided invalid, non monotonically "
                      "increasing dts to muxer in stream 0: 469 >= 469", 5.0, cap)
        self.assertEqual(cap.errors, [])
        self.assertEqual(len(cap.warnings), 1)

    def test_redact(self):
        text = ("[error] rtsp://u:p@10.1.2.3:8554/x wyze://10.1.2.3?uid=ABC&enr=x%2Fy&mac=D03F27 "
                "uid=ABC enr=x%2Fy mac=D03F27 at 10.9.8.7")
        out = ms.redact(text)
        for leak in ("10.1.2.3", "10.9.8.7", "ABC", "x%2Fy", "D03F27", "u:p"):
            self.assertNotIn(leak, out)


class SummaryTests(unittest.TestCase):
    def test_clean_stream_passes(self):
        r = ms.summarize(cap_with(frames(clean_times()), end=12.0), 10, 2)
        self.assertEqual(r["outcome"], "complete")
        self.assertEqual(r["verdict"], "PASS", r["reasons"])
        self.assertEqual(r["resolution"], "320x240")
        self.assertAlmostEqual(r["delivered_fps"], 20, delta=0.5)
        self.assertAlmostEqual(r["nominal_fps"], 20, delta=0.01)

    def test_delivery_stall_with_continuous_pts_fails(self):
        # Delivery pauses 1.2 s before frame 120; timestamps stay continuous.
        t = [x + (1.2 if i >= 120 else 0) for i, x in enumerate(clean_times())]
        pts = [i * 0.05 for i in range(len(t))]
        r = ms.summarize(cap_with(frames(t, pts), end=12.0), 10, 2)
        self.assertGreaterEqual(r["arrival_gap_max_s"], 1.2)
        self.assertLess(r["pts_gap_max_s"], 0.1)
        self.assertEqual(r["verdict"], "FAIL")
        self.assertTrue(any("delivery" in reason for reason in r["reasons"]), r["reasons"])

    def test_timestamp_gap_fails(self):
        t = [x for i, x in enumerate(clean_times()) if not 100 <= i < 120]
        r = ms.summarize(cap_with(frames(t), end=12.0), 10, 2)
        self.assertGreaterEqual(r["pts_gap_max_s"], 1.0)
        self.assertEqual(r["verdict"], "FAIL")
        self.assertTrue(any("timestamp" in reason for reason in r["reasons"]), r["reasons"])

    def test_trailing_stall_counts(self):
        t = [x for x in clean_times() if x <= 9.0]
        r = ms.summarize(cap_with(frames(t), end=12.0), 10, 2)
        self.assertGreaterEqual(r["arrival_gap_max_s"], 2.9)
        self.assertEqual(r["verdict"], "FAIL")

    def test_early_eof(self):
        t = [x for x in clean_times() if x <= 5.0]
        r = ms.summarize(cap_with(frames(t), end=5.0, exited=True), 10, 2)
        self.assertEqual(r["outcome"], "early-eof")
        self.assertEqual(r["verdict"], "FAIL")
        self.assertLess(r["arrival_gap_max_s"], 0.1)

    def test_resolution_change_fails(self):
        t = clean_times()
        fr = frames(t[:120]) + frames(t[120:], size=(640, 360))
        r = ms.summarize(cap_with(fr, end=12.0), 10, 2)
        self.assertEqual(r["verdict"], "FAIL")
        self.assertTrue(any("resolution changed" in reason for reason in r["reasons"]), r["reasons"])

    def test_expect_mismatch_fails(self):
        r = ms.summarize(cap_with(frames(clean_times()), end=12.0), 10, 2, expect="2304x1296")
        self.assertEqual(r["verdict"], "FAIL")

    def test_errors_while_joining_do_not_fail(self):
        # Joining a live H.264 stream mid-GOP logs errors until the first
        # keyframe. Those land in the warmup, before the window opens.
        cap = cap_with(frames(clean_times()), end=12.0)
        cap.errors = [(0.3, "[h264] [error] Missing reference picture"), (0.4, "[h264] [error] top block unavailable")]
        r = ms.summarize(cap, 10, 2)
        self.assertEqual(r["verdict"], "PASS", r["reasons"])
        self.assertEqual(r["decode_errors"], 0)
        self.assertEqual(r["decode_errors_warmup"], 2)

    def test_errors_inside_window_fail(self):
        cap = cap_with(frames(clean_times()), end=12.0)
        cap.errors = [(0.3, "[h264] [error] join"), (6.0, "[h264] [error] error while decoding MB 30 0")]
        r = ms.summarize(cap, 10, 2)
        self.assertEqual(r["verdict"], "FAIL")
        self.assertEqual(r["decode_errors"], 1)
        self.assertEqual(r["error_samples"], ["[h264] [error] error while decoding MB 30 0"])

    def test_repeated_pts_counted_without_failing(self):
        t = clean_times()
        pts = list(t)
        pts[150] = pts[149]
        r = ms.summarize(cap_with(frames(t, pts), end=12.0), 10, 2)
        self.assertEqual(r["pts_repeats"], 1)
        self.assertEqual(r["verdict"], "PASS", r["reasons"])

    def test_backwards_pts_counted_not_gap(self):
        t = clean_times()
        pts = list(t)
        pts[100], pts[101] = pts[101], pts[100]
        r = ms.summarize(cap_with(frames(t, pts), end=12.0), 10, 2)
        self.assertEqual(r["pts_backwards"], 1)
        self.assertLess(r["pts_gap_max_s"], 0.2)

    def test_no_frames_outcomes(self):
        cases = [
            (ms.Capture(exited=True), "connect-failed"),
            (ms.Capture(exited=True, input_opened=True), "no-video"),
            (ms.Capture(exited=False), "no-frames"),
        ]
        for cap, outcome in cases:
            r = ms.summarize(cap, 10, 2)
            self.assertEqual(r["outcome"], outcome)
            self.assertEqual(r["verdict"], "FAIL")

    def test_exit_codes(self):
        self.assertEqual(ms.exit_code({"verdict": "PASS", "frames": 10}), 0)
        self.assertEqual(ms.exit_code({"verdict": "FAIL", "frames": 5}), 1)
        self.assertEqual(ms.exit_code({"verdict": "FAIL", "frames": 0}), 2)


VIDEO = ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=20", "-c:v", "mpeg2video", "-g", "20", "-bf", "0"]
AUDIO = ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-c:a", "mp2"]


class Relay:
    """TCP server that feeds one client a live MPEG-TS from ffmpeg, optionally pausing it."""

    def __init__(self, source, seconds, stall_at=None, stall_for=0.0, silent=False):
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-re", *source[:4],
                     "-t", str(seconds), *source[4:], "-f", "mpegts", "-flush_packets", "1", "pipe:1"]
        self.stall_at, self.stall_for, self.silent = stall_at, stall_for, silent
        self.done = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    @property
    def url(self):
        return f"tcp://127.0.0.1:{self.port}"

    def _serve(self):
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        if self.silent:
            self.done.wait()
            conn.close()
            return
        proc = subprocess.Popen(self.args, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        start, stalled = time.monotonic(), False
        while chunk := os.read(proc.stdout.fileno(), 65536):
            if self.stall_at is not None and not stalled and time.monotonic() - start >= self.stall_at:
                time.sleep(self.stall_for)
                stalled = True
            try:
                conn.sendall(chunk)
            except OSError:
                break
        proc.kill()
        proc.wait()
        conn.close()

    def close(self):
        self.done.set()
        self.sock.close()


# ffmpeg probes MPEG-TS for about 5 s before it emits the first frame, so the
# producers run long enough to cover the probe, the warmup and the window, and
# stalls are placed after the window opens (about 6 s in).
def run(url, duration, warmup=1.0, timeout=10.0, expect=None):
    cap = ms.capture(ms.build_command("ffmpeg", url), duration, warmup, timeout)
    return ms.summarize(cap, duration, warmup, expect)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class IntegrationTests(unittest.TestCase):
    def test_clean_stream_passes(self):
        relay = Relay(VIDEO, 14)
        r = run(relay.url, 4)
        relay.close()
        self.assertEqual(r["outcome"], "complete")
        self.assertEqual(r["resolution"], "320x240")
        self.assertEqual(r["verdict"], "PASS", r["reasons"])
        self.assertTrue(15 <= r["delivered_fps"] <= 25, r["delivered_fps"])
        self.assertLess(r["arrival_gap_max_s"], 0.4)

    def test_delivery_stall_with_continuous_timestamps_fails(self):
        relay = Relay(VIDEO, 18, stall_at=8, stall_for=1.5)
        r = run(relay.url, 6)
        relay.close()
        self.assertGreaterEqual(r["arrival_gap_max_s"], 1.2)
        self.assertLess(r["pts_gap_max_s"], 0.2)
        self.assertEqual(r["verdict"], "FAIL")

    def test_timestamp_gap_fails(self):
        src = VIDEO[:4] + ["-vf", "select=not(between(t\\,8.5\\,9.5))", "-fps_mode", "passthrough"] + VIDEO[4:]
        relay = Relay(src, 16)
        r = run(relay.url, 6)
        relay.close()
        self.assertGreaterEqual(r["pts_gap_max_s"], 0.9)
        self.assertEqual(r["verdict"], "FAIL")

    def test_early_eof_exits_1(self):
        relay = Relay(VIDEO, 9)
        with contextlib.redirect_stdout(io.StringIO()):
            code = ms.main([relay.url, "--duration", "10", "--warmup", "1", "--json"])
        relay.close()
        self.assertEqual(code, 1)

    def test_connect_failed_is_bounded(self):
        probe = socket.create_server(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        t0 = time.monotonic()
        r = run(f"tcp://127.0.0.1:{port}", 5)
        self.assertEqual(r["outcome"], "connect-failed")
        self.assertLess(time.monotonic() - t0, 10)

    def test_audio_only_is_no_video(self):
        relay = Relay(AUDIO, 5)
        r = run(relay.url, 3)
        relay.close()
        self.assertEqual(r["outcome"], "no-video")

    def test_silent_server_times_out(self):
        relay = Relay(VIDEO, 5, silent=True)
        t0 = time.monotonic()
        r = run(relay.url, 3, timeout=3)
        relay.close()
        self.assertEqual(r["outcome"], "no-frames")
        self.assertLess(time.monotonic() - t0, 9)


if __name__ == "__main__":
    unittest.main()
