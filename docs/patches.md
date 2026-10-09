# The go2rtc patches

The image builds go2rtc from commit `a7f9c64`, the head of
[PR #2324](https://github.com/AlexxIT/go2rtc/pull/2324), applies the three
patches in `bridge/patches/`, and changes one default. The patches came out
of testing six Wyze Bulb Cams (`HL_BC`, firmware 21.1.6.1161). All four
upstream pull requests were still open on 2026-10-08.

| Change | Upstream | Which cameras it affects |
| ------ | -------- | ------------------------ |
| Base: WebRTC profile selection | [#2324](https://github.com/AlexxIT/go2rtc/pull/2324) | WebRTC sources |
| `2k` profile default (Dockerfile `sed`) | none | every Kinesis WebRTC source in this go2rtc build |
| 0001 Bulb Cam resolution | [#2497](https://github.com/AlexxIT/go2rtc/pull/2497) | `HL_BC` only |
| 0002 extended frame endings | [#2498](https://github.com/AlexxIT/go2rtc/pull/2498) | every native (`wyze://`) camera |
| 0003 retransmission | [#2507](https://github.com/AlexxIT/go2rtc/pull/2507) | retransmission on `HL_BC` only; shared DTLS changes for every native camera |

## Base: PR #2324 and the `2k` default

Wyze's WebRTC service streams 360p unless the client asks for a profile.
PR #2324 adds a `#profile=` option to go2rtc's Wyze WebRTC source. The
bridge builds its WebRTC source URLs without that option, so the Dockerfile
changes go2rtc's default from "none" to `2k`. The `sed` matches both profile
checks in `internal/webrtc/kinesis.go`, so the default also covers go2rtc's
generic Kinesis and SwitchBot sources. The bridge only ever creates Wyze
sources, so nothing else in this image is affected.

The camera decides what it actually sends for a requested profile. On the
Bulb Cam, `2k` produced 2304x1296. For other WebRTC models, measure.

**Drop it when** go2rtc merges profile selection and the bridge passes a
profile, or go2rtc defaults to the best profile on its own.

## 0001: Bulb Cam resolution (`hdFrameSize`)

go2rtc asks a native camera for its HD profile with a resolution code from
`hdFrameSize()`: floodlight models get code 4, models listed in `is2K()` get
3, everything else gets 0 (1080p). The Bulb Cam is in neither list. Adding it
to `is2K()` is not enough: the camera acknowledges code 3 and keeps sending
640x360. It needs code 4, the floodlight code, which the camera reads back as
resolution 5 and then sends 2304x1296.

The patch adds `|| c.model == "HL_BC"` to the floodlight branch.

**Drop it when** #2497 or an equivalent lands upstream.

## 0002: extended frame endings

Native Wyze video arrives in fragments. A fragment header type `0x09` was
treated as "extended start". On the Bulb Cam it also ends multi-packet video
frames, and its `0x28` field is the length of the frame-info block, not a
packet index of 40. The old parser read it as packet number 40, so the
frame never completed and was dropped, and the frame-info bytes were not
stripped. The patch
treats `0x09` as an end and always strips the frame info. It adds unit tests
for both shapes and for a real fragment number 40.

This code is shared by every native camera. A camera that never sends `0x09`
endings sees no change.

**Drop it when** #2498 lands upstream.

## 0003: retransmission for the Bulb Cam

On the Bulb Cam a handful of lost UDP packets per minute broke keyframes,
which showed up as two-second holes in recordings. The host was not losing
them: there were no kernel UDP drops and no queue overflows. The packets
never arrived. The camera supports TUTK's reliable
mode, where the client sends selective ACKs and the camera re-sends what was
missed. The patch implements that mode in `pkg/tutk/dtls/reliable.go`:

- Login sets the resend flag at byte 538 (byte 536 did nothing on this
  camera).
- The receiver tracks the camera's media packet counter, asks for gaps with
  selective ACKs every 20 ms, drops duplicates, and hands fragments on in
  order. Re-sent media arrives on channels 4, 6 and 8 (originals on 3, 5
  and 7).
- It answers the camera's statistics requests, including those embedded in
  media packets, and echoes its timestamp so the camera's round-trip estimate
  works.
- It holds at most 512 pending fragments and gives up on a gap after two
  seconds, which ends the session so go2rtc reconnects.

It is switched on only when `c.model == "HL_BC"` (in `pkg/wyze/client.go`).
Other models keep the old login and ACK timing. The patch also changes code
every native DTLS session uses: locking around the connection, ACK
handling, error cancellation and worker shutdown. Its tests cover the
disabled mode as well as the enabled one.

Measured on one Bulb Cam over ten minutes: the largest decoded gap fell from
2.0 s to 0.3 s, with no decode warnings, at about 1.5 Mbit/s.

**Drop it when** #2507 or an equivalent lands upstream.

## Experimental: trying a patch gate on another model

Patches 0001 and 0003 are switched on by model code. If your camera shows
delivery stalls or the wrong resolution on the native path, you can try
widening a gate. This is a developer experiment, not part of adding a
camera. Do not leave a widened gate running without the before and after
numbers.

1. Confirm the camera is really on the native path (`wyze/dtls` in go2rtc's
   `/api/streams`) and that Wi-Fi signal is reasonable. Stalls from a weak
   link are not a patch problem.
2. Take a baseline: two `measure-stream` runs of 300 s each, with Frigate
   attached. Save the `--json` output.
3. Edit the gate. For retransmission, change `c.model == "HL_BC"` in
   `0003-tutk-hlbc-retransmission.patch` to include your model code. For
   resolution, add the model to the condition in
   `0001-wyze-hlbc-resolution.patch`, or to `is2K()` if the camera wants
   code 3.
4. Build locally and recreate the container so the new image actually
   runs. A plain `docker compose restart` keeps the old one.

   ```sh
   docker compose -f bridge/docker-compose.yml build
   docker compose -f bridge/docker-compose.yml up -d --force-recreate
   docker exec wyze-bridge sha256sum /usr/local/bin/go2rtc   # must differ from bridge/go2rtc-amd64.sha256
   ```

   The new build runs for every camera on this bridge, and the widened gate
   applies to every camera of that model. Ask whoever relies on those
   cameras first.
5. Repeat the two runs on the camera under test, and one run on a camera
   that was already working. The second run checks the change broke nothing.
6. Keep the change only if the largest arrival gap and the count of gaps
   over 500 ms clearly improve, and the other camera is unchanged.
7. Roll back by reverting the patch, then rebuilding and recreating as in
   step 4, or by pulling the release image
   (`docker compose -f bridge/docker-compose.yml pull`) and recreating.
8. Open a model report with both sets of JSON so the gate can be widened
   upstream.
