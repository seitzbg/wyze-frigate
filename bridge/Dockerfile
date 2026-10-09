# syntax=docker/dockerfile:1
# docker-wyze-bridge with a patched go2rtc. See ../docs/patches.md.
ARG BRIDGE_VERSION=4.5.0
ARG BRIDGE_DIGEST=sha256:708903d2882c76966ecb29763a075372d89773aa6796d0aab70f04369cc6d521
ARG BRIDGE_COMMIT=da56b956b9bfb8f426f8c2efda71f8f2851e76b8
ARG GO2RTC_COMMIT=a7f9c64a1591ef984e9a595c66b5e89ace3c6221

FROM --platform=$BUILDPLATFORM golang:1.24.13-bookworm@sha256:1a6d4452c65dea36aac2e2d606b01b4a029ec90cc1ae53890540ce6173ea77ac AS go2rtc
ARG GO2RTC_COMMIT
RUN git clone -q https://github.com/AlexxIT/go2rtc /src
WORKDIR /src
# The base commit is the head of PR #2324 (WebRTC profile selection).
RUN git fetch -q origin pull/2324/head && git checkout -q ${GO2RTC_COMMIT}
COPY patches/ /patches/
RUN for p in /patches/*.patch; do git apply --check "$p" && git apply "$p" || exit 1; done
# The bridge builds WebRTC sources without a profile, which Wyze serves at
# 360p. Default the profile to 2k. This applies to every Kinesis source in
# this go2rtc build; the bridge only creates Wyze ones.
RUN sed -i 's|if profile := query\.Get("profile"); profile != "" {|profile := query.Get("profile"); if profile == "" { profile = "2k" }; if profile != "" {|g' internal/webrtc/kinesis.go \
 && gofmt -w internal/webrtc/kinesis.go \
 && grep -c 'profile = "2k"' internal/webrtc/kinesis.go
RUN CGO_ENABLED=0 go test ./pkg/wyze ./pkg/tutk/...
ARG TARGETOS TARGETARCH
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -trimpath -o /out/go2rtc .

# Complete source for the release, with every Go module vendored, and the
# license notices that go into the image.
FROM --platform=$BUILDPLATFORM golang:1.24.13-bookworm@sha256:1a6d4452c65dea36aac2e2d606b01b4a029ec90cc1ae53890540ce6173ea77ac AS go2rtc-src
COPY --from=go2rtc /src /go2rtc
RUN cd /go2rtc && go mod vendor

# The bridge needs a newer Go than go2rtc (its go.mod says 1.26.4).
FROM --platform=$BUILDPLATFORM golang:1.26.9-bookworm@sha256:d9c68c2c51161e12fd77e4c6320687c9cd86e1af1e3ad6e6cd63ff970641453c AS bridge-src
ARG BRIDGE_COMMIT
RUN git clone -q https://github.com/IDisposable/docker-wyze-bridge /bridge \
 && cd /bridge && git checkout -q ${BRIDGE_COMMIT} && go mod vendor

FROM --platform=$BUILDPLATFORM golang:1.24.13-bookworm@sha256:1a6d4452c65dea36aac2e2d606b01b4a029ec90cc1ae53890540ce6173ea77ac AS sources
ARG BRIDGE_VERSION GO2RTC_COMMIT
COPY --from=go2rtc-src /go2rtc /go2rtc
COPY --from=bridge-src /bridge /bridge
COPY patches/ /doc/patches/
COPY SOURCES.txt /doc/SOURCES.txt
RUN short=$(echo "$GO2RTC_COMMIT" | cut -c1-7) \
 && mkdir -p /bundle /doc/third_party \
 && cp /go2rtc/LICENSE /doc/LICENSE.go2rtc \
 && cp /bridge/LICENSE /doc/LICENSE.wyze-bridge \
 && cp /bridge/THIRD_PARTY_NOTICES.md /doc/THIRD_PARTY_NOTICES.wyze-bridge.md \
 && for tree in go2rtc bridge; do \
      (cd "/$tree/vendor" && find . -type f \( -iname 'LICENSE*' -o -iname 'COPYING*' -o -iname 'NOTICE*' \) \
        -exec install -D -m 0644 {} "/doc/third_party/$tree/{}" \;); \
    done \
 && tar -C / --exclude=.git -czf "/bundle/go2rtc-${short}-patched-src.tar.gz" go2rtc \
 && tar -C / --exclude=.git -czf "/bundle/docker-wyze-bridge-v${BRIDGE_VERSION}-src.tar.gz" bridge

FROM scratch AS source-bundle
COPY --from=sources /bundle/ /

FROM idisposablegithub365/wyze-bridge:${BRIDGE_VERSION}@${BRIDGE_DIGEST}
COPY --from=go2rtc /out/go2rtc /usr/local/bin/go2rtc
COPY --from=sources /doc/ /usr/share/doc/wyze-bridge-patched/
LABEL org.opencontainers.image.source="https://github.com/seitzbg/wyze-frigate" \
      org.opencontainers.image.description="docker-wyze-bridge 4.5.0 with a patched go2rtc for local Wyze streams" \
      org.opencontainers.image.licenses="AGPL-3.0-only AND MIT"
