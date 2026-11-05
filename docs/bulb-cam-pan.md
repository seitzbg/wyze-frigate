# Bulb Cam Pan (`HL_BCP`)

The Bulb Cam Pan has no LAN stream path. The Wyze cloud reports no address
and no P2P parameters for it, so bridge 4.5.0 logs
`skipping device with missing P2P params` and never registers a stream. The
only way it has streamed for us is the path the Wyze web app uses for the
Cam Pan v4: a WebRTC session through Wyze's "Lake" gateway (hosted on
Agora). Video goes from the camera up to that gateway and back down to the
bridge, so this camera is not a LAN camera. It depends on your internet
uplink and on Wyze's service.

docker-wyze-bridge is gaining a receiver for that path in
[PR #161](https://github.com/IDisposable/docker-wyze-bridge/pull/161),
written for the Cam Pan v4. On top of it,
[t0nyz0/docker-wyze-bridge#2](https://github.com/t0nyz0/docker-wyze-bridge/pull/2)
makes the Bulb Cam Pan use it: it registers the model, asks for the `2.5k`
quality label (2560x1440), sends the camera's control commands in the form
this model accepts, and sets the quality guard's target to the model's own
resolution. Until those merge, `bridge-lake/` builds that branch from source
at a pinned commit. It runs as a second bridge beside `bridge/`, which keeps
every other camera.

What we measured, on one camera, firmware 21.2.2.1677 as reported by the
Wyze API (the device itself reports 21.2.4.1981): native HEVC at 2560x1440,
20 fps, and a session that ran 2 h 22 min without a restart. The numbers are
in [models.md](models.md#lake-path-wyze-cloud-relay).

## Run the second bridge

The account preparation is the same as the [README](../README.md) step 1.
Both bridges log in to the same account.

```sh
cp bridge-lake/.env.example bridge-lake/.env   # fill in the account, API key, BRIDGE_PASSWORD, STREAM_AUTH
docker compose -f bridge-lake/docker-compose.yml up -d --build
```

The build compiles the bridge and go2rtc from source and takes a few
minutes. The compose file pins a commit, so a rebuild gives the same result
until you change the pin. The container uses ordinary Docker networking: the
session is outbound only, and no camera needs to reach this host.

`STREAM_AUTH` is required here, unlike on the first bridge. Docker publishes
the RTSP port on every interface with its own firewall rules, so a host
firewall does not cover it; the compose file refuses to start until
`STREAM_AUTH` has a `user:password` value, and that login goes into
Frigate's input URL below.

`FILTER_MODELS=HL_BCP` keeps this bridge to the Bulb Cam Pan, and
`ALERTS_INTERVAL=0` leaves the account's event polling to the first bridge.
The first bridge keeps logging `missing P2P params` for the Bulb Cam Pan at
every refresh. That is harmless. To silence it, add `FILTER_MODELS=HL_BCP`
and `FILTER_BLOCKS=true` to `bridge/.env`, which excludes the model there.

## Find the stream

```sh
curl -s -u wyze http://BRIDGE_HOST:5081/api/cameras | jq '.[] | {name, model, fw_version}'
```

A Lake camera gets three go2rtc streams. Frigate wants the second one:

| Stream | Content |
| ------ | ------- |
| `<name>` | H.264 preview, transcoded by ffmpeg inside the container, for the bridge's web UI |
| `<name>_4k` | the camera's own HEVC stream, 2560x1440 |
| `<name>_lake` | the raw transport, used internally |

So the Frigate input is `rtsp://user:password@BRIDGE_HOST:8556/<name>_4k`,
with the `STREAM_AUTH` login. Port 8556 is the second bridge's RTSP port on
the host; `bridge/` keeps 8554.

## Attach Frigate

Put the `STREAM_AUTH` value in `frigate/.env` as `FRIGATE_LAKE_AUTH` (there
is a commented line for it in `frigate/.env.example`); Frigate substitutes
`{FRIGATE_...}` variables in its config, which keeps the password out of
`config.yml`. `tools/validate-frigate-config` fills that variable with a
placeholder when it is not in your shell, so validation works without it.

```yaml
cameras:
  front_door:
    ffmpeg:
      inputs:
        - path: rtsp://{FRIGATE_LAKE_AUTH}@{FRIGATE_BRIDGE_IP}:8556/front_door_4k
          roles: [detect, record]
    detect:
      fps: 5
      width: 2560
      height: 1440
```

Frigate decodes HEVC on the CPU unless you give it a hardware decoder; one
2560x1440 camera at 5 detect fps was fine on our host. Then measure, with
Frigate attached:

```sh
python3 tools/measure_stream.py rtsp://user:password@BRIDGE_HOST:8556/front_door_4k --expect 2560x1440 --expect-fps 20
```

The tool scrubs the credentials from what it reports.

## What to expect

- Delivery is bursty. Frames arrive in clumps, and a few times in five
  minutes nothing arrives for more than half a second, so `measure-stream`
  reports FAIL on that gap while the timestamps show holes of a few frames
  at most. Read its resolution, delivered rate and timestamp lines; Frigate
  records through the clumps.
- A new session starts at 640x360 and switches to 2560x1440 within a few
  seconds. The bridge keeps watching the delivered resolution (every minute
  after a two-minute warmup) and asks the camera for `2.5k` again when it
  drops, at most three times an hour.
- The session token is renewed about every 40 minutes. The log shows
  `token_renewal_sent` and `renewal_accepted` pairs.
- Reconnects are automatic. After a 90 s Wi-Fi outage the bridge was back
  34 s after the camera reconnected, without a restart. After a Docker
  daemon restart it reconnected in 24 s.
- The bridge's own camera state is not a health signal. It stayed
  `streaming` through the whole Wi-Fi outage above. Watch Frigate's per
  camera frame rate instead (`camera_fps` in Frigate's `/api/stats`, or
  `frigate_camera_fps` on its `/api/metrics` Prometheus endpoint).
- While the bridge is connected, the Wyze app's live view of the same camera
  stuttered in our one trial (two drops in three minutes). Alone, it was
  normal. We do not know whether the camera serves one viewer well at a time.
- Tested with one camera, one account and one firmware. Measure yours and
  send a model report.

## Troubleshooting

Session events are logged as `Lake session` lines with an `event` field:

```sh
docker logs wyze-bridge-lake 2>&1 | grep '"Lake session"' | tail -n 20
```

`connected` and `closed` bracket a session; `quality_sample` carries the
delivered `width` and `height`; `quality_retry_sent` means the bridge asked
for `2.5k` again; `user_offline_publisher` means the camera left the
session, after which the bridge reconnects on its own. The go2rtc API is not
published for this bridge. Read it from inside the container:

```sh
docker exec wyze-bridge-lake wget -qO- http://127.0.0.1:1984/api/streams | jq 'keys'
```

Treat that output as secret, as with the first bridge.

## Ports and secrets

| Port | Service | Authentication |
| ---- | ------- | -------------- |
| 5081/tcp | Bridge web UI and REST API | `BRIDGE_AUTH` (HTTP basic auth) |
| 8556/tcp | RTSP (what Frigate reads) | `STREAM_AUTH`, required by the compose file |

go2rtc's API (1984) and WebRTC ports are not published, so the web UI's own
video player does not work for this bridge; use Frigate or an RTSP player.
Docker publishes 5081 and 8556 with its own firewall rules, which `ufw`'s
host rules do not cover, which is why both carry a login: set
`BRIDGE_PASSWORD`, and `STREAM_AUTH` is mandatory.
`bridge-lake/config/` holds login tokens and camera details. Keep it out of
shared backups and out of git (`.gitignore` excludes it).

## When upstream merges

Once docker-wyze-bridge ships Lake support for the Bulb Cam Pan, replace the
`build:` block in `bridge-lake/docker-compose.yml` with the release image,
or fold the camera back into `bridge/` if that image serves both paths. The
pin in `bridge-lake/docker-compose.yml` will be updated here when that
happens.
