# Configuration

Boson reads environment variables only; there is no config file. Set them in the shell that starts ComfyUI (for the
nodes and the app) or the one that runs `tools/loop.py`. Nothing here is needed to view the shipped studios and scenes:
stored mode replays them with no key and no network. A test in the development repo fails when the code reads
a variable this page does not list.

## Where things live

| Variable | Default | What it sets |
|---|---|---|
| `BOSON_HOME` | `~/.cache/boson` | Working copies of every studio and scene the app opens (each cloned once from its bundle in `examples/`), the loop's decks and spend logs, render caches. Every click that changes a studio or a scene is a git commit here. |
| `BOSON_STUDIOS` | `examples/`, then `$BOSON_HOME/studios` | Where studios are found, `os.pathsep`-separated. A `.bundle` wins over its own working clone. |
| `BOSON_SCENES` | `examples/`, then `$BOSON_HOME/scenes` | The same for scenes. |

## Live calls: one switch per capability

Every capability has an open-weights path and a cloud path. The node's `mode` widget (`stored` / `live`) decides
whether anything is called at all; `backend` (pictures) and `model` (Locate) decide what.

| Variable | Default | Used by |
|---|---|---|
| `GEMINI_API_KEY` | none (then `~/.config/gemini/api_key`) | Pictures with `backend: api` (Nano Banana 2.1); Locate with its default model `gemini-3.8-flash`; reference descriptions when forging. |
| `COMFY_API_KEY` | none (then `~/.config/comfy-tokens/api-key`) | Pictures with `backend: comfy-api`: the same Nano Banana through Comfy's partner API, billed in Comfy credits (key from platform.comfy.org). |
| `BOSON_COMFY_API_BASE` | `https://api.comfy.org` | The Comfy API base for `comfy-api`. |
| `BOSON_AGY` | `agy` on `PATH` | Pictures with `backend: antigravity`: an Antigravity CLI signed in to a Gemini plan (about 1K output). |
| `BOSON_LOCAL_COMFY` | `http://127.0.0.1:8188` | Pictures with `backend: local`: the ComfyUI that draws with FLUX 3 Klein. It must be another server (another port) than the one running the Make node, or a run from `tools/loop.py` / `tools/scene_local.py`; a Make that would queue onto its own server is refused, since it would wait on itself. |
| `BOSON_LOCAL_MAX_REFS` | `6` | Reference images per Klein picture (Klein takes up to 10). |
| `BOSON_WRITER` | `claude-opus-5-5` | The model the writer asks for. The writer is the Claude Code CLI (`claude -p`), which must be on `PATH`. |
| `BOSON_WRITER_BASE_URL` | none | An Anthropic-compatible gateway in front of an open model (we use Qwen3.8 27B). Set it and the writer runs local: no login, non-essential traffic off. Use the gateway's URL, not a raw llama-server port; `BOSON_WRITER` then names the model it serves. |
| `BOSON_LOCATE_BASE_URL` | `http://127.0.0.1:8192` | Locate with `model: local:NAME`: a llama-server running a vision model with its projector. |
| `BOSON_SEG_DEVICE` | the GPU when one is free | `cpu` keeps BiRefNet (subject masks) off a full card. |

## The command-line loop

| Variable | Default | What it sets |
|---|---|---|
| `BOSON_ENGINE` | `tools/feedback_engine/engine.py` | The dots grid `tools/loop.py NAME dots` serves (one keypress per picture). |

## Maintainers: building the distribution

`tools/ship.py` builds the repo a stranger clones (studios as bundles, private references refused by content).

| Variable | Default | What it sets |
|---|---|---|
| `BOSON_ROOT` | this repo | The checkout whose `examples/` ship. |
| `BOSON_SHIP_REF` | `HEAD` | The commit whose pack (`boson/`, `workflows/`, `docs/`, `tools/`) ships. |
| `BOSON_PUBLISH_AS` | the publishing account | The author every shipped commit is signed with. |

## Model files for the local path

The `local` picture backend runs this graph on `BOSON_LOCAL_COMFY` with stock ComfyUI nodes. Put the files in that
ComfyUI's model folders:

| File | Folder | Role |
|---|---|---|
| `flux3-image-klein-bf16.safetensors` | `models/diffusion_models` | FLUX 3 Klein, the picture model |
| `qwen3vl_4b_bf16.safetensors` | `models/text_encoders` | its text encoder |
| `flux2-vae.safetensors` | `models/vae` | its VAE |
| `birefnet.safetensors` | `models/background_removal` | BiRefNet subject masks (scene swaps, local or cloud) |
