"""Five agricultural scenarios and their associated algorithms."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ApplicationStep:
    name: str
    display_name: str


@dataclass(frozen=True)
class ApplicationInfo:
    name: str
    display_name: str
    description: str
    steps: list[ApplicationStep] = field(default_factory=list)


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    description: str
    applications: list[ApplicationInfo] = field(default_factory=list)

    @property
    def has_applications(self) -> bool:
        return len(self.applications) > 0


SCENARIOS: list[Scenario] = [
    Scenario(
        id="transplant_quality",
        name="栽秧质量检测",
        description="基于无人机影像的栽秧质量检测，包括秧苗数量统计和稻穗检测，为栽秧效果评估提供数据支撑。",
        applications=[
            ApplicationInfo(
                name="daosui",
                display_name="稻穗检测",
                description="基于无人机影像的稻穗数量检测算法（RPDA），采用不同型号无人机在不同高度采集的数据训练而来，检测稻穗数量，为产量预测打下基础。",
                steps=[
                    ApplicationStep("image_loader", "ImageLoader"),
                    ApplicationStep("preprocess", "Preprocess"),
                    ApplicationStep("trt_inference", "TRTInference"),
                    ApplicationStep("postprocess", "Postprocess"),
                    ApplicationStep("detection_visualizer", "DetectionVisualizer"),
                    ApplicationStep("result_saver", "ResultSaver"),
                    ApplicationStep("stats_collector", "StatsCollector"),
                ],
            ),
            ApplicationInfo(
                name="yangmiao",
                display_name="秧苗检测",
                description="基于无人机影像的秧苗检测算法，采用 SAHI 切片 + TensorRT 推理，检测秧苗数量并计算 ROI 面积（亩），为秧苗长势评估提供数据支撑。",
                steps=[
                    ApplicationStep("geotiff_process", "GeoTIFFProcess"),
                    ApplicationStep("sahi_slicing", "SAHISlicing"),
                    ApplicationStep("trt_inference", "TRTInference"),
                    ApplicationStep("global_nms", "GlobalNMS"),
                    ApplicationStep("slice_paste", "SlicePaste"),
                    ApplicationStep("shapefile_saving", "ShapefileSaving"),
                ],
            ),
        ],
    ),
    Scenario(
        id="lodging",
        name="倒伏监测",
        description="通过无人机影像监测水稻倒伏情况，评估灾害影响程度。",
    ),
    Scenario(
        id="growth",
        name="长势监测",
        description="基于多时相无人机影像，监测水稻长势变化趋势，辅助田间管理决策。",
    ),
    Scenario(
        id="weed",
        name="稻田杂草",
        description="通过无人机 RGB 影像快速识别水稻田杂草，提供杂草面积和位置信息。",
        applications=[
            ApplicationInfo(
                name="qiuchao",
                display_name="秋草识别",
                description="通过无人机 RGB 影像快速识别水稻田杂草，提供杂草面积、位置信息作为来年杂草防治的参考。",
                steps=[
                    ApplicationStep("dji_distortion_correct", "DJIDistortionCorrect"),
                    ApplicationStep("sahi_slicing", "SAHISlicing"),
                    ApplicationStep("trt_inference", "TRTInference"),
                    ApplicationStep("slice_paste", "SlicePaste"),
                    ApplicationStep("area_calcu", "AreaCalcu"),
                    ApplicationStep("stats_collector", "StatsCollector"),
                ],
            ),
        ],
    ),
    Scenario(
        id="wheat_height",
        name="小麦株高",
        description="基于无人机影像估算小麦株高，为品种筛选和生长评估提供量化指标。",
    ),
]

SCENARIO_MAP: dict[str, Scenario] = {s.id: s for s in SCENARIOS}
APPLICATION_SCENARIO_MAP: dict[str, str] = {
    app.name: scenario.id
    for scenario in SCENARIOS
    for app in scenario.applications
}
