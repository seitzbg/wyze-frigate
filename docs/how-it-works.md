# How it works

Three programs sit between a Wyze camera and a Frigate recording.

```
Wyze cloud ──(login, camera list)──> wyze-bridge
                                         │ registers one stream per camera
                                         v
camera ──(native TUTK, LAN)──────────> go2rtc ──RTSP :8554──> Frigate
camera ──(WebRTC via Wyze cloud)─────>   │
```

## The bridge

[docker-wyze-bridge](https://github.com/IDisposable/docker-wyze-bridge)
logs into your Wyze account with your email, password and developer API
key. It reads the camera list from the Wyze cloud at startup and again every
`REFRESH_INTERVAL` (default 30 minutes). For each camera it registers a
stream with the go2rtc process that runs inside the same container. The
stream name is the camera's Wyze nickname in lower case, with spaces turned
into underscores and every character other than letters, digits, `_` and `-`
removed.

The bridge does not carry video itself. go2rtc does.

## How a camera's source is chosen

In bridge 4.5.0 (`streamSourceFor` in `internal/camera/manager.go`) each
camera gets one of three sources:

1. **WebRTC** when the model is registered as a WebRTC streamer (the
   Doorbell Pro family, OG, Cam Pan Duo, Floodlight Pro), when you force it
   with `MODEL_OVERRIDES=<MODEL>:is_webrtc=true`, or after automatic
   promotion (below). go2rtc sets up the stream through Wyze's cloud
   signalling. On our Bulb Cams the media then flowed directly over the LAN,
   but setup always depends on the cloud.
2. **Gwell proxy** for the Gwell-based models that stream through the
   bridge's `gwell-proxy` sidecar.
3. **Native** (`wyze://`) for everything else. go2rtc talks the camera's
   TUTK protocol directly over the LAN, using the camera IP the Wyze cloud
   reported. go2rtc's native client only supports cameras that report DTLS.
   It refuses a camera whose cloud record says `dtls=false`.

**Automatic promotion.** When a native camera fails to connect
`TUTK_FALLBACK_THRESHOLD` times in a row (default 5), the bridge switches it
to WebRTC for the rest of the run and logs `TUTK failing repeatedly,
promoting camera to WebRTC`. A camera can therefore be on a different path
than you expect. Check the real source with go2rtc's API (see the
`add-wyze-camera` skill or [troubleshooting](troubleshooting.md)).

## Why the patched go2rtc

Stock go2rtc picks the camera's resolution from a per-model table, and the
Bulb Cam is missing from it. Its native receiver also has no retransmission,
so on our Bulb Cams a few lost packets broke whole keyframes and left
two-second holes in the video. This repo builds go2rtc with three patches
and one setting change. [patches.md](patches.md) has the details. In short:

- The Bulb Cam (`HL_BC`) asks for the right 2K resolution code.
- Multi-packet video frames that end with an extended header are parsed
  correctly. This applies to every native camera.
- The Bulb Cam gets packet retransmission, so lost fragments are re-sent
  instead of breaking a keyframe.
- WebRTC sources ask for the `2k` profile. Without it our Bulb Cams got
  360p over WebRTC.

## On-demand streams

go2rtc connects to a camera only while something is watching that stream.
On our Bulb Cams the first seconds of a new connection could arrive at
640x360 before the camera switched to its HD profile. Frigate stays
connected all the time, so in practice it holds every camera at full
resolution. A one-off probe from a cold start can report 360p even when
everything is fine. Measure with a
consumer attached and a warmup period, which is what `measure-stream` does.

## Frigate

Frigate pulls `rtsp://BRIDGE_HOST:8554/<stream name>` with one input per
camera for both detection and recording. One input means one connection to
the bridge per camera. The bridge uses host networking, so Frigate reaches
it at the bridge host's LAN IP. That works whether Frigate runs on the same
host or another one.
