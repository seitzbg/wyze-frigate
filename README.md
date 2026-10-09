# wyze-frigate

Record Wyze cameras in [Frigate](https://frigate.video) over your LAN, at
full resolution. This repo packages
[docker-wyze-bridge](https://github.com/IDisposable/docker-wyze-bridge) with
a patched [go2rtc](https://github.com/AlexxIT/go2rtc), Frigate configs for
CPU and NVIDIA hosts, a tool that measures what each camera actually
delivers, and a guide for coding agents.

It came out of running six Wyze Bulb Cams at 2304x1296 in Frigate. The
Bulb Cam is the only model tested so far. [docs/models.md](docs/models.md)
lists what the code does for every other model, and how to add your
measurements.

## What you need

- A Linux host with Docker on the same LAN as the cameras. The bridge uses
  host networking.
- A Wyze account with a password (see step 1) and a developer API key.
- For Frigate: an x86-64 host for the CPU baseline, or an NVIDIA GPU for
  the [GPU setup](docs/nvidia.md). It can be the bridge host.
- `curl` and `jq` for the commands below.
- Python 3 and ffmpeg for `measure-stream`, or Docker to run it in a
  container.

Run every command from the repository root unless a step says otherwise.

## Quickstart

### 1. Prepare the Wyze account

- If you sign in to Wyze with Google or Apple, set a Wyze password for the
  account. The bridge logs in with email and password only.
- Create an API key in the
  [Wyze developer console](https://developer-api-console.wyze.com/#/apikey/view).
  You need both the key and its ID.
- Give each camera a DHCP reservation. The native stream path dials the IP
  the Wyze cloud last saw, and that copy can lag a long time after a camera
  moves ([why](docs/troubleshooting.md#the-stream-never-starts)).

### 2. Firewall the bridge ports

The bridge listens on 5080, 1984, 8554 and 8889, and port 1984 has no
authentication in this bridge version. Restrict them before the bridge
starts: [docs/network-and-security.md](docs/network-and-security.md) has a
`ufw` example and a check to run from a machine that should be refused.

### 3. Start the bridge

```sh
cp bridge/.env.example bridge/.env   # fill in the account, API key, BRIDGE_IP, BRIDGE_PASSWORD
docker compose -f bridge/docker-compose.yml up -d
```

### 4. Find the stream names

```sh
curl -s -u wyze http://BRIDGE_HOST:5080/api/cameras | jq '.[] | {name, model, fw_version}'
```

curl asks for the password: the `BRIDGE_PASSWORD` from `bridge/.env`.
`name` is the stream name, served at `rtsp://BRIDGE_HOST:8554/<name>`.

### 5. Configure and start Frigate

```sh
cp frigate/.env.example frigate/.env   # set FRIGATE_BRIDGE_IP to the bridge host's LAN IP
mkdir -p frigate/config
cp frigate/config.example.yml frigate/config/config.yml   # replace the example camera with yours
tools/validate-frigate-config frigate/config/config.yml
docker compose -f frigate/docker-compose.yml up -d
docker logs frigate 2>&1 | grep -A1 'User: admin'   # admin password, printed on first start only
```

The UI is at `https://FRIGATE_HOST:8971` (self-signed certificate). For an
NVIDIA GPU, swap in the GPU config and compose override from
[docs/nvidia.md](docs/nvidia.md) at this step.

### 6. Measure each camera

With Frigate running:

```sh
python3 tools/measure_stream.py rtsp://BRIDGE_HOST:8554/<name>
# or, without ffmpeg on the host:
docker build -t measure-stream tools/
docker run --rm --network host measure-stream rtsp://BRIDGE_HOST:8554/<name>
```

It watches the stream for five minutes and reports resolution, frame rate,
the largest gap in delivery and in timestamps, and decoder errors. Set each
camera's `detect.width` and `detect.height` to the measured resolution.
[docs/frigate-tuning.md](docs/frigate-tuning.md) covers foliage and the
burned-in timestamp.

## Using a coding agent

[AGENTS.md](AGENTS.md) is the guide for Codex, Claude Code and similar
tools. The `add-wyze-camera` skill (`.claude/skills/`, also linked from
`.agents/skills/`) walks an agent through adding a camera, checking its
real stream path, measuring it, and diagnosing a failure.

## Documentation

- [How it works](docs/how-it-works.md): bridge, go2rtc, the native and
  WebRTC paths, and why the patches exist.
- [Camera models](docs/models.md): what is verified and what the code does
  for each model.
- [Patches](docs/patches.md): each go2rtc change, its upstream PR, and how
  to experiment with another model.
- [Network and security](docs/network-and-security.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Frigate tuning](docs/frigate-tuning.md)
- [NVIDIA setup](docs/nvidia.md)

## Building the image yourself

```sh
docker compose -f bridge/docker-compose.yml build
```

The build clones go2rtc at a pinned commit, applies the patches, runs their
tests, and swaps the result into the pinned bridge image. On amd64 it
produces the same go2rtc binary the prebuilt image carries.

## Upstream

The patches are proposed upstream. Once they merge and a bridge release
picks them up, the stock image will do the same job.

- go2rtc [#2324](https://github.com/AlexxIT/go2rtc/pull/2324) (WebRTC
  profile selection), [#2497](https://github.com/AlexxIT/go2rtc/pull/2497)
  (Bulb Cam resolution), [#2498](https://github.com/AlexxIT/go2rtc/pull/2498)
  (frame endings), [#2507](https://github.com/AlexxIT/go2rtc/pull/2507)
  (retransmission)
- docker-wyze-bridge
  [#148](https://github.com/IDisposable/docker-wyze-bridge/issues/148)
  (Bulb Cam support)

## License

The files in this repository are MIT licensed (see [LICENSE](LICENSE)).

The published image is a different matter. It contains docker-wyze-bridge
4.5.0, unmodified, under AGPL-3.0, and go2rtc under MIT with the patches
from `bridge/patches/`. Their license texts, the bridge's third-party
notices and a description of the sources are in
`/usr/share/doc/wyze-bridge-patched/` inside the image. The complete source
for both is attached to every
[release](https://github.com/seitzbg/wyze-frigate/releases).

Built on docker-wyze-bridge, go2rtc and Frigate.
