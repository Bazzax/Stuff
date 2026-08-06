# Stuff

Portable storage for Claude Code skills.

## Contents

### `.claude/skills/artwork-orchestrator/` (v1.1.0)

Turns an artwork concept into list-ready print products: prompt variations →
local generation → 4× upscale → 300-DPI print crops → titled folder → listing SEO.

Cloning this repo and working inside it makes the skill available to Claude Code
automatically. To use it from any directory instead, copy it to your personal
skills directory:

```sh
cp -r .claude/skills/artwork-orchestrator ~/.claude/skills/
```

## Runtime dependencies

The skill is self-contained except for three things it expects to find on the
machine running it. Check them with:

```sh
python .claude/skills/artwork-orchestrator/scripts/artwork.py preflight
```

| Dependency | What it's for | Notes |
|---|---|---|
| `~/.config/ai-images/env` | `GEMINI_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY` | Read by `generate.py`; `source` it before generating |
| `tooling/ad-creatives/generate.py` + its `.venv` | Image generation (shared provider layer) | Lives in the project this skill was built for — not vendored here |
| Real-ESRGAN (`realesrgan-ncnn-vulkan`) | The 4× upscale | One-time install; preflight prints the instructions. Set `ARTWORK_UPSCALER` to point at it |

Preflight exits non-zero and names anything missing. The skill deliberately
refuses to skip the upscale step — native resolution alone will not reach
300 DPI at the larger print sizes.
