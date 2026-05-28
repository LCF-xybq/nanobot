# 算法服务接口文档

基础地址：`http://{host}:8000`

---

## 1. 查询已注册算法列表

获取所有已注册算法的名称和描述信息。

- **URL**：`GET /list_service`
- **请求参数**：无

**响应示例**：

```json
{
  "daosui": {
    "name": "稻穗检测算法",
    "description": "基于无人机影像的稻穗数量检测算法（Rice Panicles Detection Algorithm, RPDA），采用不同型号无人机在不同高度采集而来的数据训练而来，重在检测稻穗的数量，为产量的预测打下基础。"
  },
  "qiuchao": {
    "name": "秋草识别算法",
    "description": "本算法通过无人机RGB影像快速识别水稻田杂草，提供杂草面积、位置信息作为来年杂草防治的参考。"
  },
  "yangmiao": {
    "name": "秧苗检测算法",
    "description": "基于无人机影像的秧苗检测算法，采用 SAHI 切片 + TensorRT 推理，检测秧苗数量并计算 ROI 面积（亩），为秧苗长势评估提供数据支撑。"
  }
}
```

---

## 2. 启动算法服务

提交一个算法任务，后台异步执行。

- **URL**：`POST /start_service/{service_name}`
- **路径参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `service_name` | string | 算法名称，如 `daosui`、`qiuchao`、`yangmiao` |

- **请求体**：

```json
{
  "filename": "qiuchao_202605221045.zip"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `filename` | string | 是 | MinIO 中待处理的 zip 文件名 |

**响应示例**：

```json
{
  "task_id": "a1b2c3d4",
  "status": "PENDING",
  "service_name": "qiuchao"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 任务唯一标识 |
| `status` | string | 任务状态，初始为 `PENDING` |
| `service_name` | string | 算法名称 |

---

## 3. 查询当前运行中的服务状态

获取某个算法当前正在运行的任务状态。

- **URL**：`GET /service_status/{service_name}`
- **路径参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `service_name` | string | 算法名称 |

**响应示例**：

```json
{
  "task_id": "a1b2c3d4",
  "service_name": "qiuchao",
  "status": "RUNNING",
  "progress": {
    "percent": 40.0,
    "stage": "inference",
    "message": "",
    "timestamp": 1747881600.0
  },
  "start_time": 1747881500.0,
  "end_time": null,
  "elapsed_time": 100.5,
  "timeout_overall": null,
  "timeout_deadline": null,
  "error_message": null,
  "error_type": null,
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "retry_count": 0,
  "max_retries": 0
}
```

**错误响应**（服务未运行）：

```json
{
  "request_id": "550e8400-...",
  "error_code": "SERVICE_NOT_FOUND",
  "message": "Service qiuchao is not currently running",
  "details": { "service_name": "qiuchao" }
}
```

---

## 4. 通过任务 ID 查询状态

根据 `task_id` 查询任意任务的状态（包括已完成任务）。

- **URL**：`GET /task_status/{task_id}`
- **路径参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 启动服务时返回的任务 ID |

**响应示例**：

```json
{
  "task_id": "a1b2c3d4",
  "service_name": "qiuchao",
  "status": "SUCCESS",
  "progress": {
    "percent": 100.0,
    "stage": "done",
    "message": "",
    "timestamp": 1747881800.0
  },
  "start_time": 1747881500.0,
  "end_time": 1747881800.0,
  "elapsed_time": 300.0,
  "timeout_overall": null,
  "timeout_deadline": null,
  "error_message": null,
  "error_type": null,
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "retry_count": 0,
  "max_retries": 0
}
```

**错误响应**（任务不存在）：

```json
{
  "request_id": "550e8400-...",
  "error_code": "TASK_NOT_FOUND",
  "message": "Task a1b2c3d4 not found",
  "details": { "task_id": "a1b2c3d4" }
}
```

---

## 5. 查询所有任务

获取所有任务（运行中和已完成）的列表。

- **URL**：`GET /tasks`
- **请求参数**：无

**响应示例**：

```json
{
  "tasks": [
    {
      "task_id": "a1b2c3d4",
      "service_name": "qiuchao",
      "status": "SUCCESS",
      "progress": { "percent": 100.0, "stage": "done", "message": "", "timestamp": 1747881800.0 },
      "start_time": 1747881500.0,
      "end_time": 1747881800.0,
      "elapsed_time": 300.0,
      "timeout_overall": null,
      "timeout_deadline": null,
      "error_message": null,
      "error_type": null,
      "request_id": "550e8400-e29b-41d4-a716-446655440000",
      "retry_count": 0,
      "max_retries": 0
    }
  ],
  "count": 1
}
```

---

## 6. 按算法查询任务

获取某个算法的所有任务记录。

- **URL**：`GET /tasks/{service_name}`
- **路径参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `service_name` | string | 算法名称 |

**响应示例**：

```json
{
  "service_name": "qiuchao",
  "tasks": [
    {
      "task_id": "a1b2c3d4",
      "service_name": "qiuchao",
      "status": "SUCCESS",
      "progress": { "percent": 100.0, "stage": "done", "message": "", "timestamp": 1747881800.0 },
      "start_time": 1747881500.0,
      "end_time": 1747881800.0,
      "elapsed_time": 300.0,
      "timeout_overall": null,
      "timeout_deadline": null,
      "error_message": null,
      "error_type": null,
      "request_id": "550e8400-e29b-41d4-a716-446655440000",
      "retry_count": 0,
      "max_retries": 0
    }
  ],
  "count": 1
}
```

---

## 7. 停止服务

停止当前正在运行的算法任务。

- **URL**：`POST /stop_service/{service_name}`
- **路径参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `service_name` | string | 算法名称 |

- **请求体**：无

**响应示例**：

```json
{
  "status": "stopped",
  "service_name": "qiuchao",
  "task_id": "a1b2c3d4"
}
```

**错误响应**（服务未运行）：

```json
{
  "request_id": "550e8400-...",
  "error_code": "SERVICE_NOT_FOUND",
  "message": "Service qiuchao is not currently running",
  "details": { "service_name": "qiuchao" }
}
```

---

## 8. 查询 MinIO 数据列表

列出指定算法在 MinIO 中的输入数据文件。

- **URL**：`POST /list_data`
- **请求体**：

```json
{
  "algo_name": "qiuchao"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `algo_name` | string | 是 | 算法名称 |

**响应示例**：

```json
{
  "data": [
    {
      "name": "qiuchao_202605221045.zip",
      "size": 104857600,
      "last_modified": "2026-05-22T10:45:00+00:00"
    }
  ],
  "count": 1
}
```

---

## 通用说明

### 任务状态流转

```
PENDING → RUNNING → SUCCESS
                  → FAILED
                  → TIMEOUT
                  → STOPPED
         → RETRYING → RUNNING → ...
```

### 进度阶段

**稻穗检测（daosui）**：

| 阶段 | stage | 进度 |
|------|-------|------|
| 下载 | `download` | 0% |
| 推理 | `inference` | 30% |
| 上传 | `upload` | 80% |
| 完成 | `done` | 100% |

**秋草识别（qiuchao）**：

| 阶段 | stage | 进度 |
|------|-------|------|
| 下载 | `download` | 0% |
| 畸变校正 | `distortion_correction` | 15% |
| 切片 | `slicing` | 30% |
| 推理 | `inference` | 40% |
| 拼接 | `stitching` | 65% |
| 统计 | `statistics` | 80% |
| 上传 | `upload` | 90% |
| 完成 | `done` | 100% |

**秧苗检测（yangmiao）**：

| 阶段 | stage | 进度 |
|------|-------|------|
| 下载 | `download` | 0% |
| 切片 | `slicing` | 20% |
| 推理 | `inference` | 20%-80% |
| NMS 去重 | `nms` | 85% |
| 上传 | `upload` | 90% |
| 完成 | `done` | 100% |

### 请求头

| 头部 | 说明 |
|------|------|
| `X-Request-ID` | 请求追踪 ID，未提供时自动生成 |
| `X-User-ID` | 用户标识 |
| `X-Operation` | 操作标识 |

所有响应都会在头部返回 `X-Request-ID`，用于问题追踪。

### 错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| `SERVICE_NOT_FOUND` | 404 | 服务未注册或未运行 |
| `TASK_NOT_FOUND` | 404 | 任务不存在 |
| `SERVICE_ALREADY_RUNNING` | 409 | 服务已在运行中 |
| `VALIDATION_ERROR` | 422 | 请求参数校验失败 |
| `PIPELINE_TIMEOUT` | 408 | 管线执行超时 |
| `PIPELINE_ERROR` | 500 | 管线执行异常 |
| `STORAGE_ERROR` | 500 | 存储操作异常 |
| `INTERNAL_ERROR` | 500 | 未知内部错误 |
