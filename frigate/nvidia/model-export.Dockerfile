# syntax=docker/dockerfile:1
# Exports YOLOv9 to ONNX for Frigate's onnx detector. Frigate does not
# download this model itself. Adapted from Frigate's detector docs, with the
# yolov9 source and the weights pinned. Run from the frigate/ directory:
#
#   docker build . --build-arg IMG_SIZE=320 --output ./config/model_cache \
#       -f nvidia/model-export.Dockerfile
#
# Result: config/model_cache/yolov9-t-320.onnx (about 8 MB). The checksum
# below is for the tiny (t) weights. Other sizes (s, m, c, e) are more
# accurate and slower; to use one, set MODEL_SIZE and replace the checksum
# with that file's sha256.
FROM python:3.11 AS build
RUN apt-get update && apt-get install --no-install-recommends -y cmake libgl1 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.10.4 /uv /bin/
WORKDIR /yolov9
ADD https://github.com/WongKinYiu/yolov9.git#5b1ea9a8b3f0ffe4fe0e203ec6232d788bb3fcff .
RUN uv pip install --system -r requirements.txt
RUN uv pip install --system onnx==1.18.0 onnxruntime onnx-simplifier==0.4.* onnxscript
ARG MODEL_SIZE=t
ARG IMG_SIZE=320
ADD --checksum=sha256:61e080e964e65e32b884477c5e6344c607c7e02103d64649de810edaeb869803 \
    https://github.com/WongKinYiu/yolov9/releases/download/v0.1/yolov9-${MODEL_SIZE}-converted.pt yolov9-${MODEL_SIZE}.pt
RUN sed -i "s/ckpt = torch.load(attempt_download(w), map_location='cpu')/ckpt = torch.load(attempt_download(w), map_location='cpu', weights_only=False)/g" models/experimental.py
RUN python3 export.py --weights ./yolov9-${MODEL_SIZE}.pt --imgsz ${IMG_SIZE} --simplify --include onnx
FROM scratch
ARG MODEL_SIZE=t
ARG IMG_SIZE=320
COPY --from=build /yolov9/yolov9-${MODEL_SIZE}.onnx /yolov9-${MODEL_SIZE}-${IMG_SIZE}.onnx
