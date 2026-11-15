import cv2
import time
import numpy as np

print("=" * 60)
print("Scanning camera indices 0 through 9...")
print("=" * 60)

found_any = False
for idx in range(10):
    for backend_name, backend in [("DirectShow", cv2.CAP_DSHOW), ("MSMF", cv2.CAP_MSMF)]:
        cap = cv2.VideoCapture(idx, backend)
        if cap.isOpened():
            time.sleep(0.5)
            ret, frame = cap.read()
            if ret and frame is not None:
                mean = float(np.mean(frame))
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                status = "✅ ACTIVE" if mean > 5.0 else "⚠️ DARK"
                print(f"Index {idx} ({backend_name}): {status} — {w}x{h}, mean: {mean:.1f}")
                if mean > 5.0:
                    found_any = True
            else:
                print(f"Index {idx} ({backend_name}): opened but read() failed")
            cap.release()

print("=" * 60)
if not found_any:
    print("No active camera found up to index 9.")
else:
    print("Found active camera!")
