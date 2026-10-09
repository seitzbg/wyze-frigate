# Camera models

Only the Bulb Cam has been tested with this image. Every other row comes
from reading the code of the versions this image pins: bridge 4.5.0
(`internal/wyzeapi/models.go`, `internal/camera/manager.go`) and go2rtc
`a7f9c64` (`pkg/wyze/client.go`). Those rows say what the software will try,
not what the camera will do. If you run one of them, measure it and send a
[model report](../.github/ISSUE_TEMPLATE/model-report.yml).

Names are the ones the bridge's model registry uses.

## How to read the table

- **Path** is what bridge 4.5.0 picks by default. Native rows apply only
  when the camera reports DTLS. go2rtc's native client refuses `dtls=false`,
  and the bridge may then promote the camera to WebRTC after 5 failures.
  Check the real path with go2rtc's `/api/streams` (see
  [troubleshooting.md](troubleshooting.md)).
- **Requested** is the resolution code go2rtc asks for on the native path,
  from `hdFrameSize()`: `2K` (code 3), `1080p` (code 0), or `floodlight`
  (code 4). Doorbell rows use the doorbell resolution command (K10052)
  instead of K10056. The name of a code is not a promise of pixels. The Bulb
  Cam acknowledged the `2K` code and still sent 640x360.
- **Patches**: 0002 (frame endings) and the shared parts of 0003 touch every
  native camera. 0001 and the retransmission in 0003 are on for `HL_BC`
  only. The `2k` WebRTC profile default touches every WebRTC camera.

## Native path (TUTK over the LAN)

| Model | Code | Requested | Status | Notes |
| ----- | ---- | --------- | ------ | ----- |
| Bulb Cam | `HL_BC` | floodlight (patch 0001) | **Verified** | See measurements below. Not in bridge 4.5.0's model list, so it shows its raw code. |
| V3 | `WYZE_CAKP2JFUS` | 1080p | Untested | |
| V3 Pro | `HL_CAM3P` | 2K | Untested | |
| V4 | `HL_CAM4` | 2K | Untested | The bridge warns that v4 firmware from about 2025-02 blocks TUTK and suggests `MODEL_OVERRIDES=HL_CAM4:is_webrtc=true`. On WebRTC the `2k` profile default applies. |
| Pan | `WYZECP1_JEF` | 1080p | Untested | |
| Pan V2 | `HL_PAN2` | 1080p | Untested | |
| Pan V3 | `HL_PAN3` | 1080p | Untested | |
| Pan Pro | `HL_PANP` | 2K | Untested | |
| Doorbell | `WYZEDB3` | 1080p, doorbell command | Untested | |
| Doorbell V2 | `HL_DB2` | 2K | Untested | |
| Floodlight V2 | `HL_CFL2` | floodlight | Untested | |
| Outdoor | `WVOD1` | 1080p, doorbell command | Untested | |
| Outdoor V2 | `HL_WCO2` | 1080p, doorbell command | Untested | |
| V1, V2 | `WYZEC1`, `WYZEC1-JZ` | 1080p (v1 uses the doorbell command) | Untested | |
| Battery Cam Pro | `AN_RSCW` | 1080p | Untested | |

## WebRTC path (Wyze cloud signalling)

These models are WebRTC streamers in the bridge's registry. go2rtc asks for
the `2k` profile because of this image's default. What the camera sends for
it is untested.

| Model | Code |
| ----- | ---- |
| Doorbell Pro | `GW_BE1` |
| Doorbell Pro 2 | `AN_RDB1` |
| Doorbell Duo | `GW_DBD` |
| OG, OG 3X | `GW_GC1`, `GW_GC2` |
| Cam Pan Duo | `GW_DUO` |
| Floodlight Pro | `LD_CFP` |

The Window Cam (`GW_WC`) uses the bridge's Gwell proxy, which this image
does not change.

## Bulb Cam measurements

Two Bulb Cams on the native path, measured on 2026-10-08 with
`measure-stream` for 300 s after a 10 s warmup, Frigate attached, bridge on
an amd64 host. Both passed.

| Firmware | Resolution | Frames | Delivered | Largest delivery gap | Gaps over 500 ms | Largest timestamp gap | Decoder errors |
| -------- | ---------- | ------ | --------- | -------------------- | ---------------- | --------------------- | -------------- |
| 21.1.6.1161 | 2304x1296 | 5985 | 19.95 fps | 0.310 s | 0 | 0.050 s | 0 |
| 21.1.7.1256 | 2304x1296 | 5985 | 19.95 fps | 0.431 s | 0 | 0.050 s | 0 |

Earlier work on the same model, from the transport investigation behind
patch 0003: over a ten-minute recording the largest decoded gap was 0.3 s,
down from 2.0 s without retransmission, at about 1.5 Mbit/s.

## Adding a row

Run the [add-wyze-camera](../.claude/skills/add-wyze-camera/SKILL.md)
procedure or measure by hand:

```sh
python3 tools/measure_stream.py rtsp://BRIDGE_HOST:8554/CAMERA --json
```

Then open a model report issue with the model code, firmware, path and the
JSON. The tool scrubs the stream URL's host, credentials and camera name,
and anything shaped like an address, MAC or Wyze key from the messages it
reports. Read the JSON before you paste it, and paste nothing else from your
system.
