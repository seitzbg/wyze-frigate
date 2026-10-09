# Network and security

The bridge runs with host networking. Every port below listens on all of the
host's addresses. Do not forward any of them from the internet; the bridge's
own README says the same.

| Port | Service | Authentication in 4.5.0 |
| ---- | ------- | ----------------------- |
| 5080/tcp | Bridge web UI and REST API | `BRIDGE_AUTH=true` (HTTP basic auth or `BRIDGE_API_TOKEN` bearer) |
| 1984/tcp | go2rtc API and web UI | **None.** CORS allows any origin. |
| 8554/tcp | RTSP (what Frigate reads) | `STREAM_AUTH` |
| 8888/tcp | HLS | `STREAM_AUTH` |
| 8889/tcp, 8189/udp | WebRTC | `STREAM_AUTH` |

## Why host networking

go2rtc's native client talks to each camera over UDP on your LAN. Behind
Docker's bridge NAT that connection failed to come up at all in our setup
("discovery timeout"). RTSP, WebRTC and HLS also need real host ports for
Frigate and browsers to reach them.

## What to lock down

- **Port 1984 has no authentication.** Anyone who can reach it can list
  streams (including each camera's `wyze://` source URL with its device
  keys), add or delete streams, and watch video. The go2rtc API auth option
  first appears in the 4.6.0 betas, so on 4.5.0 a firewall is the only
  control.
- **Streams are open unless you set `STREAM_AUTH`.** With
  `STREAM_AUTH=viewer:secret`, RTSP, HLS and WebRTC all need those
  credentials, and Frigate's input URLs must include them
  (`rtsp://viewer:secret@HOST:8554/name`). We have not run with this set.
- **Set `BRIDGE_PASSWORD`.** With `BRIDGE_AUTH=true` and no password, the
  bridge uses the part of your Wyze email before the `@`.
- **`bridge/config/` is a secret.** It holds Wyze login tokens and, for each
  camera, its IP, MAC and the keys go2rtc uses to talk to it. Keep it out of
  backups you share and out of git (this repo's `.gitignore` excludes it).

## A firewall example

Allow the Frigate host and an admin subnet, drop everyone else. With `ufw`,
replacing the example addresses with yours:

```sh
FRIGATE=192.0.2.20         # host running Frigate (or this host's own IP)
ADMIN=192.0.2.0/24         # where you browse from
for port in 5080 1984 8554 8888 8889; do
    ufw allow from "$FRIGATE" to any port "$port" proto tcp
    ufw allow from "$ADMIN" to any port "$port" proto tcp
    ufw deny "$port"/tcp
done
ufw allow from "$ADMIN" to any port 8189 proto udp
ufw deny 8189/udp
```

The camera side needs nothing inbound: go2rtc connects out to the cameras.
If your cameras live on a separate VLAN, allow UDP from the bridge host to
that VLAN.

## Frigate on the same host

Frigate's own docs publish 8554, 8555 and 1984 for its built-in go2rtc. On
the bridge host those ports are already taken, and the bridge fails to start
if 1984 is in use. Publish only 8971 (Frigate's authenticated UI), as
`frigate/docker-compose.yml` does.
