---
name: vision
description: "REQUIRED when a user message contains an [image: path] attachment marker — you cannot see images directly, so call vision_analyze to get a text description before answering. Also use it for photos, screenshots, diagrams, OCR, object counting, image comparison."
---

# Vision Analysis

**You are a text-only model. You cannot see image content.** When a user message
contains an `[image: /path]` marker, that path points to an image the user wants
you to reason about. You MUST call `vision_analyze` with that path before
answering — otherwise your answer will be a guess.

## When To Use

- A user message contains `[image: /path]` (one or more).
- The user uploaded, pasted, or referenced a photo, screenshot, or diagram and
  asks about its content.
- Triggers (any language): "what's in this image", "看", "识别", "图里",
  "截图里", "OCR", "读出文字", "数一下", "对比这两张图", "生育期", "症状",
  "这是什么".
- The user asks you to extract text from a scanned document or screenshot.

## How To Call

```
vision_analyze(
  images=["/path/from/the/marker.png"],
  prompt="What growth stage is this crop in? Answer briefly.",
)
```

- Copy the path from the `[image: ...]` marker verbatim.
- For multiple markers in one message, pass all paths in a single call.
- Write a focused `prompt` tied to the user's question — "What growth stage?"
  beats "describe this image".
- The tool returns text only. Use that text to answer the user; never claim to
  "see" the image yourself.

## When NOT To Use

- The user just wants the image saved/forwarded — use `message` with `media`.
- The file is a PDF/DOCX/XLSX — use `read_file` (extracts text directly).
- No `[image: ...]` marker is present and the user hasn't referenced any image.


## When NOT To Use

- The user only wants the image re-sent, forwarded, or saved — use `message` with the `media` parameter.
- The image is one you just generated via `generate_image` and the user hasn't asked about its content.
- The file is a PDF / DOCX / XLSX — use `read_file` (which extracts text from those directly).

## How To Call

```
vision_analyze(
  images=["/path/to/image.png"],   # required, one or more paths
  prompt="Extract all visible text",  # optional, focused question
)
```

- `images` paths must be inside the workspace or the nanobot media directory.
- For multi-image comparison, pass all paths in one call and ask the comparison question in `prompt`.
- The tool returns **text only** — never an image. Quote or summarize that text back to the user; do not paste raw base64.

## Prompt Tips

Focused prompts beat generic ones:

- "Extract every line of text in this screenshot, preserving layout." — good.
- "List every object visible and roughly where it is in the frame." — good.
- "describe" — weak; the vision model may ramble.

## Fallbacks

If `vision_analyze` returns an error about the provider being unavailable or the image being unreadable, report the issue to the user briefly and suggest checking `tools.vision` configuration or the image path. Do not retry in a tight loop — vision calls can be slow.
