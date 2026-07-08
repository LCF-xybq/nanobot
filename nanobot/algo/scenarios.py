"""Five agricultural scenarios and their associated algorithms."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AlgorithmInfo:
    name: str
    display_name: str
    description: str


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    description: str
    algorithms: list[AlgorithmInfo] = field(default_factory=list)

    @property
    def has_algorithms(self) -> bool:
        return len(self.algorithms) > 0


SCENARIOS: list[Scenario] = [
    Scenario(
        id="transplant_quality",
        name="栽秧质量检测",
        description="基于无人机影像的栽秧质量检测，包括秧苗数量统计和稻穗检测，为栽秧效果评估提供数据支撑。",
        algorithms=[
            AlgorithmInfo(
                name="daosui",
                display_name="稻穗检测",
                description="基于无人机影像的稻穗数量检测算法（RPDA），采用不同型号无人机在不同高度采集的数据训练而来，检测稻穗数量，为产量预测打下基础。",
            ),
            AlgorithmInfo(
                name="yangmiao",
                display_name="秧苗检测",
                description="基于无人机影像的秧苗检测算法，采用 SAHI 切片 + TensorRT 推理，检测秧苗数量并计算 ROI 面积（亩），为秧苗长势评估提供数据支撑。",
            ),
        ],
    ),
    Scenario(
        id="lodging",
        name="倒伏监测",
        description="通过无人机影像监测水稻倒伏情况，评估灾害影响程度。",
        algorithms=[
            AlgorithmInfo(
                name="daofu",
                display_name="倒伏监测",
                description="基于无人机影像的水稻倒伏监测算法，通过滑动窗口切片与 TensorRT 推理识别倒伏区域，统计倒伏面积与分布。",
            ),
        ],
    ),
    Scenario(
        id="growth",
        name="长势监测",
        description="基于多时相无人机影像，监测水稻长势变化趋势，辅助田间管理决策。",
        algorithms=[
            AlgorithmInfo(
                name="ndvi",
                display_name="NDVI 长势监测",
                description="基于多时相无人机影像计算 NDVI 植被指数，进行长势分级与重分类，生成田间长势分布图。",
            ),
        ],
    ),
    Scenario(
        id="weed",
        name="稻田杂草",
        description="通过无人机 RGB 影像快速识别水稻田杂草，提供杂草面积和位置信息。",
        algorithms=[
            AlgorithmInfo(
                name="qiuchao",
                display_name="秋草识别",
                description="通过无人机 RGB 影像快速识别水稻田杂草，提供杂草面积、位置信息作为来年杂草防治的参考。",
            ),
        ],
    ),
    Scenario(
        id="wheat_height",
        name="小麦株高",
        description="基于无人机影像估算小麦株高，为品种筛选和生长评估提供量化指标。",
        algorithms=[
            AlgorithmInfo(
                name="height",
                display_name="株高检测",
                description="植物株高测量算法，通过检测标尺及关键点几何换算得到株高（cm），输出可视化结果及株高JSON。",
            ),
        ],
    ),
]

SCENARIO_MAP: dict[str, Scenario] = {s.id: s for s in SCENARIOS}
ALGORITHM_SCENARIO_MAP: dict[str, str] = {
    algo.name: scenario.id
    for scenario in SCENARIOS
    for algo in scenario.algorithms
}
