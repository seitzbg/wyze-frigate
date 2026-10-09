# Agent guide

This repo runs Frigate on Wyze cameras through docker-wyze-bridge with a
patched go2rtc. You are usually helping someone set it up on their own
hardware, add a camera, or work out why a camera streams badly.

## Map

- `bridge/`: the image (Dockerfile, go2rtc patches), compose file, `.env` template.
- `frigate/`: baseline compose and config (OpenVINO on CPU); `nvidia/` holds the GPU variant.
- `tools/measure_stream.py`: the instrument. `tools/validate-frigate-config`: strict config check.
- `docs/`: how it works, models, patches, network and security, troubleshooting, tuning.
- `.claude/skills/add-wyze-camera/`: the procedure for adding or diagnosing a camera.

## Commands

```sh
python3 -m unittest discover -s tools/tests -v              # tool tests (needs ffmpeg for integration)
tools/validate-frigate-config frigate/config.example.yml    # needs Docker
docker build bridge/                                         # builds the image and runs the patch tests
```

## Rules

- **Evidence is measure-stream output.** A resolution, a "works", or a
  "fixed" comes from a `measure-stream` run with Frigate attached, quoted
  with its numbers. The bridge UI's labels and a single cold `ffprobe` are
  not evidence.
- **The path comes from go2rtc.** Read each camera's protocol and DTLS flag
  from `http://BRIDGE_HOST:1984/api/streams` (`wyze/dtls` is native,
  `webrtc/...` is the cloud path). The bridge can promote a camera to WebRTC
  on its own.
- **The user's containers are theirs.** Ask before restarting or recreating
  the bridge or Frigate, and before rebooting a camera.
- **Reports carry numbers, never identifiers.** Issues, commits and chat get
  the model code, firmware, path and `measure-stream --json` output.
  IP addresses, URLs, MAC addresses, `uid`/`enr` values, camera names,
  `.env` contents and `bridge/config/` stay on the user's machine.
- **One Wi-Fi kick at most.** Repeated de-auths pushed a camera into pairing
  mode in our testing. Reboot the camera instead.
- **Patch gates are an experiment.** Adding a camera never edits a patch.
  Widening a model gate follows the procedure at the end of
  `docs/patches.md`, with before and after measurements.
