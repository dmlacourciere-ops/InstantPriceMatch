# tools/droidcam.py
# DroidCam helper: snapshot and live-stream capture for dev camera.
# Provides:
#   - grab_frame(ip, port=4747) -> temp JPEG path
#   - open_capture(ip, port=4747) -> cv2.VideoCapture
#   - read_frame_rgb(cap) -> np.ndarray (RGB) or None

import io
import tempfile
from typing import Optional, List

import requests
from PIL import Image

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore
    np = None   # type: ignore

# Known DroidCam endpoints
SNAPSHOT_PATHS: List[str] = [
    "/shot.jpg", "/photo.jpg", "/jpeg", "/image.jpg",
    "/cam/1/shot.jpg", "/cam/1/photo.jpg",
]
STREAM_PATHS: List[str] = [
    "/video", "/mjpegfeed", "/video?640x480", "/video?1280x720",
]

def _base(ip: str, port: int) -> str:
    return f"http://{ip}:{port}".rstrip("/")

def _save_bytes_to_temp_jpeg(b: bytes) -> str:
    # Validate and normalize image bytes to a clean JPEG on disk
    img = Image.open(io.BytesIO(b)).convert("RGB")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    img.save(tmp.name, format="JPEG", quality=92)
    return tmp.name

def grab_frame(ip: str, port: int = 4747, timeout: float = 4.0) -> str:
    """
    Capture one still frame from DroidCam and return a temp JPEG path.
    1) Try snapshot endpoints via HTTP.
    2) If they fail, pull one frame from the MJPEG stream via OpenCV.
    """
    if not ip:
        raise ValueError("Missing ip (e.g., 192.168.1.23). Open DroidCam on the phone to see IP/port.")
    base = _base(ip, port)

    # 1) Fast path: snapshots
    for path in SNAPSHOT_PATHS:
        url = base + path
        try:
            r = requests.get(url, timeout=timeout)
            if r.ok and r.content:
                return _save_bytes_to_temp_jpeg(r.content)
        except Exception:
            continue  # try the next path

    # 2) Fallback: one frame from MJPEG stream
    if cv2 is None:
        raise RuntimeError("OpenCV not available and snapshots failed. Install opencv-python.")
    for path in STREAM_PATHS:
        url = base + path
        try:
            cap = cv2.VideoCapture(url)
            ok, frame = cap.read()
            cap.release()
            if ok and frame is not None:
                ok2, buf = cv2.imencode(".jpg", frame)
                if ok2:
                    return _save_bytes_to_temp_jpeg(buf.tobytes())
        except Exception:
            continue

    raise RuntimeError(
        "Could not capture from DroidCam. "
        "Verify the app is open and try http://IP:PORT/shot.jpg or /video in a browser."
    )

def open_capture(ip: str, port: int = 4747):
    """
    Open a live MJPEG stream with OpenCV and return a cv2.VideoCapture.
    You must call cap.release() when done.
    """
    if cv2 is None:
        raise RuntimeError("OpenCV not available. Install opencv-python.")
    base = _base(ip, port)
    for path in STREAM_PATHS:
        url = base + path
        cap = cv2.VideoCapture(url)
        if cap.isOpened():
            return cap
    raise RuntimeError("Could not open DroidCam stream. Test http://IP:PORT/video in a browser to confirm it works.")

def read_frame_rgb(cap) -> Optional["np.ndarray"]:
    """
    Read one frame from an open cv2.VideoCapture and return it as RGB ndarray.
    Returns None if a frame was not available.
    """
    if cv2 is None or np is None:
        return None
    ok, frame = cap.read()
    if not ok or frame is None:
        return None
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
