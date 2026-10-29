#!/usr/bin/env python3
"""Subject masks with BiRefNet, the background-removal model ComfyUI core ships (comfy/bg_removal_model.py). Runs under
ComfyUI's own venv so Boson's runner needs no torch: scene.subject_masks() calls it as a subprocess.

  ~/ComfyUI/venv/bin/python boson/segment.py IN.png OUT.png [IN2.png OUT2.png ...]

Writes each OUT as an 8-bit L mask the size of its IN (255 = subject). GPU when one is free, else CPU (BOSON_SEG_DEVICE).
"""
import os, pathlib, sys

COMFY = pathlib.Path(os.environ.get("COMFYUI_DIR", pathlib.Path.home() / "ComfyUI")).resolve()


def main(pairs):
    sys.path.insert(0, str(COMFY))
    sys.argv = [sys.argv[0]] + (["--cpu"] if os.environ.get("BOSON_SEG_DEVICE") == "cpu" else [])
    import numpy as np, torch
    from PIL import Image
    import comfy.options
    comfy.options.enable_args_parsing()
    import comfy.bg_removal_model as bg
    m = bg.load(str(COMFY / "models" / "background_removal" / "birefnet.safetensors"))
    with torch.inference_mode():
        for src, dst in pairs:
            img = torch.from_numpy(np.asarray(Image.open(src).convert("RGB"), dtype=np.float32) / 255.0)[None]
            mask = m.encode_image(img)[0].float().clamp(0, 1).cpu().numpy()
            Image.fromarray((mask * 255).round().astype(np.uint8)).save(dst)
            print(dst, flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or len(a) % 2:
        sys.exit(__doc__)
    main(list(zip(a[::2], a[1::2])))
