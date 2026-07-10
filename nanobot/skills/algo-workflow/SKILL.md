---
name: algo-workflow
description: "REQUIRED when the user explicitly requests running an agricultural algorithm — names an algorithm (daosui, qiuchao, yangmiao, wheat_height, etc.) or says 跑算法 / 启动XX算法 / 用XX检测 / 算法检测 / 跑一下XX. Workflow: collect local path + algo name → upload_minio → algo(start, filename=full MinIO path with bucket) → poll task status → report from task response. This takes priority over vision_analyze when an algorithm is explicitly requested."
---

# Agricultural Algorithm Workflow

Use this when the user explicitly wants to **run / start / launch** an
agricultural algorithm service on their data. Not for ad-hoc "看一眼" visual
questions — those go to `vision_analyze`.

## When To Use

- User names an algorithm: `daosui`, `qiuchao`, `yangmiao`, `wheat_height`, ...
- User says: "跑算法", "启动 daosui", "用 daosui 检测这张图",
  "算法跑一下", "跑一下稻穗算法".
- User references local data + a specific agricultural task.

## When NOT To Use

- User wants quick visual reasoning (count, describe, OCR on a single image)
  → `vision_analyze`.
- User only asks what algorithms exist → `algo(action="list")`.
- No algorithm is named and intent is ambiguous → ASK the user which they
  want before picking a path.

## Priority Over Vision

This skill **takes priority over `vision_analyze`** when an algorithm is
explicitly requested. `vision_analyze` does ad-hoc visual reasoning with the
multimodal LLM; this workflow runs the **trained model** on MinIO data. If
the user names an algorithm or says "跑算法", do not call `vision_analyze`
even if an `[image: /path]` marker is present — follow this workflow instead.

## Workflow

### Step 1 — Collect inputs

You need two things:

- **path**: local folder (or single file) with the input data.
- **algo**: algorithm service name (`daosui`, `qiuchao`, `yangmiao`, ...).

If the user gave an `[image: /path]` marker, that's the path. If they only
said "检测这张图" without naming the algorithm, **ASK** — don't guess. Each
algorithm expects a specific input modality (drone orthophoto, seedling
close-up, ...) and running the wrong one wastes time.

### Step 2 — Upload to MinIO

`upload_minio` accepts **folders only**. If the user gave a single image,
wrap it in a temp folder first:

```
# 1. make a temp folder (any writable dir works — /tmp or a workspace path)
exec(command="mkdir -p /tmp/algo_input && cp /path/from/marker.png /tmp/algo_input/")
# 2. upload the folder
upload_minio(path="/tmp/algo_input", algo="daosui")
```

If the user already gave a folder path, skip the copy:

```
upload_minio(path="/path/to/folder", algo="daosui")
```

The return value looks like:

```
Uploaded to MinIO: cloud-bucket/algoritm/daosui/algo_input_202607101200.zip (12345 bytes)
```

The **filename** for the next step is everything between `MinIO:` and the
trailing `(...)` — **including the bucket prefix**:

```
cloud-bucket/algoritm/daosui/algo_input_202607101200.zip
```

If the response says `Object already exists in MinIO: ...`, the filename is
everything after `MinIO:` with no size suffix — same rule.

### Step 3 — Start the algorithm

```
algo(
  action="start",
  service_name="daosui",
  filename="cloud-bucket/algoritm/daosui/algo_input_202607101200.zip",
)
```

The response contains a `task_id`. Save it for polling.

### Step 4 — Poll task status

```
algo(action="task", task_id="<task_id from step 3>")
```

Poll every few seconds. Status typically goes `pending → running → succeeded`
(or `failed`). Stop polling once terminal. **Do NOT tight-loop** — algorithm
runs can take tens of seconds to minutes. Between polls, yield control back
to the user with a brief "still running" message if appropriate.

### Step 5 — Report from task response

Once `succeeded`, read the result fields straight from the `algo(action="task")`
response — counts, annotated image paths, metrics are all there. **Do NOT try
to fetch files from the server's local output directory** — you can't reach
it. Summarize for the user:

- which algorithm ran on which input,
- final status,
- key output fields (detection counts, result image locations if any,
  per-image metrics).

If the response references a result image path that the user can access
remotely (e.g. a MinIO URL or a served path), mention it. Otherwise report
the textual metrics.

## Common Mistakes

- Calling `vision_analyze` instead of this workflow when the user named an
  algorithm. Don't — vision_analyze is ad-hoc, this workflow runs the
  trained model.
- Stripping the bucket prefix from `filename`. Pass the full path exactly as
  returned by `upload_minio` (including `cloud-bucket/`).
- Tight-looping on status polls. Spread them out — algorithm runs are slow.
- Guessing the algorithm name. If the user didn't say which, ask.
