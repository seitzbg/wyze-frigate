---
name: add-wyze-camera
description: Use when adding a Wyze camera to this bridge and Frigate setup, or when a Wyze camera here streams at low resolution, stalls, or never starts.
---

# Add or diagnose a Wyze camera

Work through the steps in order. Each ends on a check. The job is done when
the camera has a passing `measure-stream` run with Frigate attached, or a
named cause from `docs/troubleshooting.md` backed by the measurement that
shows it.

Placeholders: `BRIDGE_HOST` is the bridge host's LAN IP. `CAMERA` is the
stream name. Bridge credentials are `BRIDGE_USERNAME` / `BRIDGE_PASSWORD`
from the user's `bridge/.env`. Ask the user for them; never print them.

## 1. Identify the camera

```sh
curl -s -u "$BRIDGE_USERNAME:$BRIDGE_PASSWORD" http://BRIDGE_HOST:5080/api/cameras \
  | jq '.[] | {name, model, model_name, fw_version, state}'
```

`name` is the stream name. Done when you have the model code and firmware.

## 2. Look up the model

Find the model code in `docs/models.md`. Note its path, requested
resolution and status. If the row names an override (for example the V4's
`MODEL_OVERRIDES=HL_CAM4:is_webrtc=true`), tell the user and add it to
`bridge/.env` only with their OK, then restart the bridge with their OK.

Done when you know which path the camera should be on and whether anyone
has verified the model.

## 3. Attach Frigate

Add a camera block like the one in `frigate/config.example.yml`: one input
for `detect` and `record` at `rtsp://{FRIGATE_BRIDGE_IP}:8554/CAMERA`.
Validate before restarting:

```sh
tools/validate-frigate-config frigate/config/config.yml
```

Restart Frigate with the user's OK. Frigate is now the persistent consumer
that keeps the camera at full resolution. Done when validation prints
`valid` and Frigate shows the camera live.

## 4. Read the actual path

```sh
curl -s http://BRIDGE_HOST:1984/api/streams | jq -r --arg c CAMERA '.[$c].producers[0]
  | "\(.protocol // "idle")  dtls=\((.source // "") | capture("dtls=(?<d>[a-z]+)").d // "?")"'
```

`wyze/dtls` is native, `webrtc/...` is the cloud path. The `source` field
holds the camera's keys, so print only these two values. Done when the path
matches step 2, or the mismatch is explained (`dtls=false`, a
`promoting camera to WebRTC` line in `docker logs wyze-bridge`, or an
override).

## 5. Measure

```sh
python3 tools/measure_stream.py rtsp://BRIDGE_HOST:8554/CAMERA --json
```

Add `--expect WxH` when `docs/models.md` lists a verified resolution for
the model. Without host ffmpeg, build `tools/Dockerfile` and run it with
`--network host`. The run takes about five minutes.

Done when you have the JSON. `PASS` means the resolution held, no delivery
or timestamp gap exceeded 500 ms, and the decoder logged no errors.

## 6. Diagnose a FAIL

Match the `reasons` against `docs/troubleshooting.md` and run the check it
names for that symptom. Each cause there has one distinguishing check:
delivery stalls with continuous timestamps, timestamp gaps, decoder errors,
640x360, and no frames are separate branches. Change one thing, then
measure again. Done when the run passes, or you can name the cause and show
the measurement that points to it.

Patch gates stay as they are here. If the cause is packet loss on a native
model without retransmission, point the user to the experiment at the end
of `docs/patches.md`.

## 7. Tune

Set the camera's `detect.width` and `detect.height` to the measured
resolution. Apply `docs/frigate-tuning.md` where it fits: `contour_area` for
foliage, a mask for the timestamp. Validate and restart as in step 3.

## 8. Report

Offer to open a model report (`.github/ISSUE_TEMPLATE/model-report.yml`)
for any model not yet verified in `docs/models.md`. It carries the model
code, firmware, host architecture, path, image tag and the `--json` output,
which is already redacted. Show the user the full text before it is posted.
