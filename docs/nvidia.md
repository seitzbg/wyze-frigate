# NVIDIA GPU setup

This is how we run Frigate: ONNX object detection with YOLOv9 on an NVIDIA
GPU, and NVDEC hardware video decode. It needs an amd64 host with an NVIDIA
GPU, its driver, and the
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).

## 1. Export the model

Frigate does not download YOLOv9 for you. Build it once, from the
repository root like every command here:

```sh
docker build frigate --build-arg IMG_SIZE=320 --output frigate/config/model_cache \
    -f frigate/nvidia/model-export.Dockerfile
```

This writes `frigate/config/model_cache/yolov9-t-320.onnx` (about 8 MB). The build
pins the YOLOv9 source and the weights' checksum. Its Python packages are not
pinned beyond what Frigate's own recipe pins, and it downloads PyTorch, so
expect a few GB and several minutes. Keep the file: it lives in your config
directory, not in the image.

## 2. Use the NVIDIA config

```sh
cp frigate/.env.example frigate/.env   # set FRIGATE_BRIDGE_IP
cp frigate/nvidia/config.nvidia.yml frigate/config/config.yml   # then edit the cameras
tools/validate-frigate-config frigate/config/config.yml ghcr.io/blakeblackshear/frigate:0.18.0-tensorrt
```

It differs from the baseline in three places: the `onnx` detector, the YOLOv9
`model` block, and `ffmpeg.hwaccel_args: preset-nvidia` for NVDEC decode
(one ffmpeg process per camera on the GPU).

## 3. Start with the GPU override

```sh
docker compose -f frigate/docker-compose.yml -f frigate/nvidia/docker-compose.nvidia.yml up -d
```

The override switches to the `-tensorrt` image, raises `shm_size` to 1 GB,
and requests the GPU. It uses the toolkit's `deploy.resources` form from
Frigate's docs. We run the CDI form (`devices: - nvidia.com/gpu=all`)
because our host has no nvidia runtime configured. The comment in the file
shows how to switch.

## Checking it

- Frigate's System metrics page shows detector inference time and GPU
  load.
- The GPU percentage covers everything on that GPU, not only Frigate.
  Compare with `nvidia-smi` when another container shares the card.
- After a host reboot, CDI device numbers can change. See the NVIDIA entry
  in [troubleshooting.md](troubleshooting.md).
