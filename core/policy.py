"""推送规程（岗位职责表）：各岗位负责哪些设备，以及什么情况下该推、不该推。

同一份规程有两个用途：
* scripts/simulate_review.py 的模拟审核员按它给出目标分（演示学习闭环、评测的标准答案）；
* 审核智能体可以通过 get_push_policy 工具读取它的文字版——相当于电厂成文的岗位职责表。
  文字版只给定性规定，不给目标分数。
"""

# 岗位 → (核心设备, 相关设备)
ROLE_RULES = {
    "汽轮机专工": ({"TURBINE", "TURBINE_HP", "TURBINE_MP", "TURBINE_LP", "FWP", "DEH_CTRL", "GOV_CTRL"},
              {"CONDENSER", "CWP", "ACC"}),
    "电气专工": ({"TRANSFORMER", "AUX_TRANSFORMER", "GENERATOR", "EXCITER"}, {"DCS"}),
    "发电机专工": ({"GENERATOR", "EXCITER"}, {"TRANSFORMER"}),
    "锅炉专工": ({"BOILER", "FWP"}, {"SCR", "FGD", "ESP"}),
}
NAMES = {"TURBINE": "汽轮机", "TURBINE_HP": "高压缸", "TURBINE_MP": "中压缸", "TURBINE_LP": "低压缸", "ACC": "空冷",
         "AUX_TRANSFORMER": "厂变", "FWP": "给水泵", "DEH_CTRL": "DEH", "GOV_CTRL": "调速系统", "CONDENSER": "凝汽器",
         "CWP": "循环水泵", "TRANSFORMER": "变压器", "GENERATOR": "发电机", "EXCITER": "励磁系统",
         "BOILER": "锅炉", "DCS": "DCS", "SCR": "脱硝", "FGD": "脱硫", "ESP": "除尘器"}

RULES_TEXT = [
    "工单真正出问题的设备是本岗位核心设备、且发生在本人负责的机组：必须推送，第一时间掌握。",
    "本岗位核心设备、但发生在其他机组：可以推送，作为同类设备参考。",
    "只涉及本岗位的相关设备：了解即可，一般不推送。",
    "发生在本人负责的机组、且实际为紧急事件（危及设备或人身安全、需要立即处理或停机）：即使不是本专业设备，也需要推送让本人知晓。",
    "其他情况（设备不属于本岗位、或不在本人负责机组的非本专业事件）：不推送，应由对应专工处理。",
    "问题不是上表中任何专工负责的生产设备（例如属于厂房建筑或公用辅助设施），即使发生在某台设备的厂房或区域里，也不推送给该设备的专工。",
    "判断依据是工单原文描述的实际设备和实际紧急程度，而不是系统提取的标签或填报等级。",
]


def judge_devices(role: str, units: list[str], unit_no: str | None, devices: set[str],
                  level: str | None) -> tuple[float, str]:
    """Target score and reason under the policy, for the given true devices and level."""
    core, related = ROLE_RULES.get(role, (set(), set()))
    own_unit = unit_no in units
    name = lambda codes: "、".join(NAMES.get(c, c) for c in sorted(codes))  # noqa: E731
    if not devices:
        return 0.05, "工单未写明设备，无法判断与本岗位相关，暂不推送"
    if devices & core:
        if own_unit:
            return 0.9, f"本人负责机组的{name(devices & core)}问题，必须第一时间掌握"
        return 0.65, f"其他机组的{name(devices & core)}问题，可作同类设备参考"
    if devices & related:
        return 0.45, f"{name(devices & related)}与本岗位设备运行相关，了解即可"
    if level == "紧急" and own_unit:
        return 0.6, f"虽是{name(devices)}问题，但发生在本人负责机组且为紧急，需要知晓"
    return 0.1, f"{name(devices)}不属于{role}职责范围，应推给对应专工"


def policy_view(role: str | None = None) -> dict:
    """Written policy for the agents: role duties (device names) and qualitative rules, no target scores."""
    roles = {r: {"核心设备": [NAMES.get(c, c) for c in sorted(core)], "相关设备": [NAMES.get(c, c) for c in sorted(rel)]}
             for r, (core, rel) in ROLE_RULES.items() if role is None or r == role}
    return {"岗位职责": roles, "推送规定": RULES_TEXT}
