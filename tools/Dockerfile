# Runs measure_stream.py without installing ffmpeg on the host:
#   docker build -t measure-stream tools/
#   docker run --rm --network host measure-stream rtsp://BRIDGE_HOST:8554/front_door
FROM python:3.13-slim-trixie
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*
COPY measure_stream.py /usr/local/bin/measure-stream
ENTRYPOINT ["python3", "/usr/local/bin/measure-stream"]
