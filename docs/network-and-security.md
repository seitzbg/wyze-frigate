# Network and security

The bridge runs with host networking, so its ports listen on every address
the host has. Do not forward any of them from the internet; the bridge's own
README says the same. Firewall them before you start the bridge.

These are the listeners a running 4.5.0 bridge opened on our host:

| Port | Service | Authentication in 4.5.0 |
| ---- | ------- | ----------------------- |
| 5080/tcp | Bridge web UI, REST API, and its stream player | `BRIDGE_AUTH` (HTTP basic auth, or a `BRIDGE_API_TOKEN` bearer token) |
| 1984/tcp | go2rtc API, web UI, HLS and MSE streams | **None.** CORS allows any origin. |
| 8554/tcp | RTSP (what Frigate reads) | `STREAM_AUTH`, one user for all cameras |
| 8889/tcp and udp | WebRTC media | None of its own |

go2rtc also opens outbound UDP sessions to each camera on random local
ports. Those need no inbound rule.

## Why host networking

go2rtc's native client talks to each camera over UDP on your LAN. Behind
Docker's bridge NAT that connection failed to come up at all in our setup
("discovery timeout"). RTSP and WebRTC also need real host ports for Frigate
and browsers to reach them.

## What to lock down

- **Port 1984 has no authentication.** Anyone who can reach it can list
  streams (including each camera's `wyze://` source URL with its device
  keys), add or delete streams, and watch video. A go2rtc API login first
  appears in the 4.6.0 betas, so on 4.5.0 the firewall is the only control.
- **`STREAM_AUTH` covers RTSP only.** With `STREAM_AUTH=viewer:secret` the
  bridge sets that one user on go2rtc's RTSP server, and Frigate's input
  URLs must include it (`rtsp://viewer:secret@HOST:8554/name`). HLS, MSE and
  WebRTC through port 1984 stay open. We have not run with it set.
- **Set `BRIDGE_PASSWORD`.** With `BRIDGE_AUTH=true` and no password, the
  bridge uses the part of your Wyze email before the `@`.
- **`bridge/config/` is a secret.** It holds Wyze login tokens and, for each
  camera, its IP, MAC and the keys go2rtc uses to talk to it. Keep it out of
  backups you share and out of git (this repo's `.gitignore` excludes it).

## A firewall example

This uses `ufw`. Allow the Frigate host and the machines you browse from,
and deny everyone else. Replace the example addresses with yours.

```sh
FRIGATE=192.0.2.20         # host running Frigate (this host's own IP if it is the same)
ADMIN=192.0.2.0/24         # where you browse from

sudo ufw status verbose    # must say "Status: active"; if not, allow SSH, then: sudo ufw enable
for port in 5080 1984 8554 8889; do
    sudo ufw allow from "$FRIGATE" to any port "$port" proto tcp
    sudo ufw allow from "$ADMIN" to any port "$port" proto tcp
    sudo ufw deny "$port"/tcp
done
sudo ufw allow from "$ADMIN" to any port 8889 proto udp
sudo ufw deny 8889/udp
sudo ufw status numbered   # no earlier rule may allow these ports from anywhere
```

`ufw` checks rules in order, so an older `allow 8554` (or a blanket allow)
listed above these wins. Delete it. Host networking means these rules apply
to the bridge. They would not apply to ports Docker publishes with `-p`.

Then prove it from a machine that is not allowed:

```sh
nc -vz -w 3 BRIDGE_HOST 1984    # must time out or be refused
```

## Frigate on the same host

Frigate's own docs publish 8554, 8555 and 1984 for its built-in go2rtc. On
the bridge host those ports are already taken, and the bridge refuses to
start if 1984 is in use. Publish only 8971 (Frigate's authenticated UI), as
`frigate/docker-compose.yml` does.
