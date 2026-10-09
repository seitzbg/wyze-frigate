# Troubleshooting

Start with two facts about the camera: which path it is on and what Frigate
actually receives.

```sh
# Path and DTLS flag for every stream that has a live producer
# (a stream has one only while something is watching it).
curl -s http://BRIDGE_HOST:1984/api/streams | jq -r 'to_entries[]
  | .value.producers[0] as $p
  | "\(.key)  \($p.protocol // "idle")  dtls=\(($p.source // "") | capture("dtls=(?<d>[a-z]+)").d // "?")"'

# What a consumer gets, over five minutes
python3 tools/measure_stream.py rtsp://BRIDGE_HOST:8554/CAMERA
```

`wyze/dtls` means native. Anything starting with `webrtc` means the cloud
path. Treat the `/api/streams` output as secret: its `source` field holds
the camera's IP and keys.

Several observations below come from Bulb Cams on firmware 21.1.6.1161.
They are marked as such and may not hold for other models.

## The stream is 640x360

- **Cold start.** A new connection can start at 640x360 before the camera
  switches to HD (seen on Bulb Cams). Measure with Frigate attached and a
  warmup. `measure-stream` ignores the first 10 s by default.
- **WebRTC path without a profile.** The stock image asks for no profile and
  Wyze sends 360p. This image defaults to `2k`. If you built go2rtc
  yourself, check the `sed` step in `bridge/Dockerfile` ran.
- **Wrong native resolution code.** The camera accepts the request and
  ignores it. See [patches.md](patches.md), patch 0001, and the experiment
  at the end of that page.

## The stream never starts

- **Stale camera IP.** The native path dials the IP the Wyze cloud reports.
  The bridge re-reads it at startup and every 30 minutes, but the cloud copy
  can lag a long time after a camera changes address. On our Bulb Cams it
  only refreshed when the camera rebooted (power cycle, or Restart Device in
  the Wyze app). A Wi-Fi disconnect did not refresh it. Give every camera a
  DHCP reservation so its address never changes. Compare the `ip` field from
  the bridge's `/api/cameras` with your DHCP leases.
- **`dtls=false`.** go2rtc's native client only supports DTLS cameras. Such
  a camera fails on the native path and the bridge may promote it to WebRTC
  after `TUTK_FALLBACK_THRESHOLD` failures (default 5). Look for
  `promoting camera to WebRTC` in `docker logs wyze-bridge`.
- **Docker networking.** The bridge must use `network_mode: host`. Native
  connections failed behind Docker's bridge NAT in our setup.
- **Port 1984 in use.** The bridge refuses to start when something already
  listens on 1984, for example a Frigate container that publishes it.

## Login fails

- Accounts that sign in with Google or Apple need a Wyze password as well.
  The bridge logs in with email and password only.
- The API ID and key come from the Wyze developer console and are required
  in addition to the password.
- Accounts with authenticator-app two-factor auth need `WYZE_TOTP_KEY`.

## A camera dropped off Wi-Fi and its LED flashes red and blue

That is pairing mode. On one of our Bulb Cams, repeated Wi-Fi de-auths
(kicking it from the access point several times in a row) pushed it into
pairing mode. It had to be added again in the Wyze app. If you need a
camera to reconnect, kick it once at most, or reboot it.

## Frigate shows gaps or smeared frames

Run `measure-stream` for five minutes. It reports what reached it, not
where a problem started. Read both gap lines:

- **"No frames for N s" with continuous timestamps:** frames reached the
  tool late. The cause can be loss between the camera and go2rtc, the
  network between the bridge and the tool, or a busy host. Run the tool on
  the bridge host itself (the `tools/Dockerfile` image with
  `--network host`) to take the network out, and watch CPU load while it
  runs. If the gap persists there, check the camera's Wi-Fi signal. On the
  native path for a model other than the Bulb Cam, retransmission is off;
  see the experiment in [patches.md](patches.md).
- **Timestamp gaps:** frames are missing from the stream itself.
- **Delivered fps well below nominal:** frames are being lost throughout,
  not in one stall. Use `--expect-fps` with the camera's frame rate if
  timestamps look even but the rate is low.
- **Decoder errors:** often the same loss, seen by the decoder. Errors in
  the first seconds after connecting are normal and are not counted.

`measure-stream` may log about one `non monotonically increasing dts`
warning every 30 seconds. It comes from the null output at the end of the
tool's own ffmpeg pipeline. In our runs the camera's timestamps had no
repeats, gaps or reversals at the same time, so the tool counts these as
warnings, not errors. Frigate's ffmpeg can log similar `Non-monotonic DTS`
lines; one of our cameras does and records fine.

## Frigate

- **"Bus error" or crashes with several cameras:** raise `shm_size`. The
  formula is in `frigate/docker-compose.yml`.
- **Admin password:** printed once, on the first start with an empty
  database: `docker logs frigate 2>&1 | grep -A1 'User: admin'`. To reset
  it, add this to the config, restart Frigate, and read the new password
  with `docker logs frigate 2>&1 | grep 'Password:'`. Then remove the
  setting again, or every restart resets it.

  ```yaml
  auth:
    reset_admin_password: true
  ```
- **Config changes do nothing:** Frigate reads its config at start. Restart
  the container after editing it.
- **NVIDIA: every camera crash-loops with `Device creation failed`** after a
  host reboot. The GPU's device numbers changed and the CDI spec is stale.
  Regenerate it (`nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`)
  and restart Frigate.
