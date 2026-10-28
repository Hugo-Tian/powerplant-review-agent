"""Generate reproducible, explicitly synthetic JSON data; never touch a database."""
import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# Device/fault combinations are illustrative scenarios, not maintenance guidance.
SCENARIOS = [
    ("TURBINE", "汽轮机", "上海电气", "MFR_SEC", [
        ("振动超标", "轴承振动趋势持续上升", "安排专业人员复核监测记录"),
        ("效率下降", "高压缸效率趋势下降", "登记异常并安排专项检查")]),
    ("GENERATOR", "发电机", "哈电集团", "MFR_HARBIN", [
        ("温度高", "定子温度趋势偏高", "复核测点和运行记录"),
        ("电气异常", "电流不平衡", "提交电气专业检查")]),
    ("BOILER", "锅炉", "上海电气", "MFR_SEC", [
        ("泄漏", "受热面巡检发现疑似漏水", "登记位置并安排专业检查"),
        ("堵塞", "受热面通道疑似堵管", "汇总巡检记录并制定检查计划")]),
    ("TRANSFORMER", "变压器", "特变电工", "MFR_TBEA", [
        ("温度高", "主变油温高", "复核冷却水和测温记录"),
        ("泄漏", "密封部位出现漏油迹象", "记录位置并联系检修人员")]),
    ("FWP", "给水泵", None, None, [
        ("泄漏", "轴封附近出现漏水迹象", "复核密封水记录"),
        ("振动异常", "轴承振动趋势异常", "安排状态检查")]),
    ("CWP", "循环水泵", None, None, [
        ("振动大", "轴承振动趋势上升", "安排专业人员检查"),
        ("效率下降", "循环水输送效率下降", "核对运行记录")]),
    ("EXCITER", "励磁系统", "南瑞继保", "MFR_NARI", [
        ("控制故障", "AVR控制故障告警", "保存告警记录并联系专业人员"),
        ("通讯中断", "监控通讯中断", "核查通讯事件记录")]),
    ("DCS", "DCS", None, None, [
        ("卡件故障", "控制卡件故障告警", "记录卡件位置并提交检查"),
        ("参数异常", "监控参数异常", "安排测点信息复核")]),
]


def generate(count=320, seed=20260909):
    if count < 32:
        raise ValueError("count must be at least 32 to cover demo scenarios")
    rng = random.Random(seed)
    catalogs = {
        "plants": [{"id": 1, "code": "SYNTH_PLANT", "name": "模拟电厂（虚构）"}],
        "units": [{"id": i, "plant_id": 1, "unit_no": f"#{i}"} for i in range(1, 5)],
        "device_types": [], "manufacturers": [], "device_models": [],
    }
    manufacturers = {}
    for i, (code, name, mfr, mfr_code, _) in enumerate(SCENARIOS, 1):
        catalogs['device_types'].append(dict(id=i, code=code, name=name))
        if mfr and mfr not in manufacturers:
            manufacturers[mfr] = len(manufacturers) + 1
            catalogs['manufacturers'].append(dict(id=manufacturers[mfr], code=mfr_code, name=mfr))
        if mfr:
            catalogs['device_models'].append(dict(
                id=i, manufacturer_id=manufacturers[mfr], device_type_id=i,
                model_code=f"SYNTH-{i:03d}", model_name=f"虚构演示型号{i}"))

    orders = []
    start = datetime(2026, 8, 1, 8, tzinfo=timezone(timedelta(hours=8)))
    levels = ['一般'] * 8 + ['重要'] * 4 + ['紧急'] * 2 + ['建议'] * 2
    for i in range(count):
        device_index = i % len(SCENARIOS)
        _, name, mfr, _, variants = SCENARIOS[device_index]
        fault, symptom, action = rng.choice(variants)
        unit = rng.randint(1, 4)
        level = levels[(i // len(SCENARIOS)) % len(levels)]
        row = dict(
            event_no=f"SYNTH-{i + 1:05d}", plant_id=1, unit_id=unit,
            device_type_id=device_index + 1,
            manufacturer_id=manufacturers.get(mfr),
            model_id=device_index + 1 if mfr else None,
            kks_code=f"SIM-{unit:02d}-{i + 1:05d}" if i % 5 else None,
            title=f"【模拟】#{unit}机组{name}{fault}记录 {i + 1:03d}",
            content=f"本条为虚构演示工单。{rng.choice(['巡检', '运行记录复核', '趋势检查'])}发现{name}{symptom}。"
                    f"{action}。{'模拟设备厂家字段为' + mfr + '。' if mfr else '厂家信息暂缺。'}",
            level=level, event_type=fault,
            occurred_at=(start + timedelta(hours=i * 2)).isoformat(),
        )
        if i % 29 == 0:
            row.update(manufacturer_id=None, model_id=None)
        if i % 53 == 0:
            row['unit_id'] = None
        if i % 79 == 0:
            row.update(device_type_id=None, manufacturer_id=None, model_id=None,
                       kks_code=None, unit_id=None, event_type=None, level='建议',
                       title=f"【模拟】待补充记录 {i + 1:03d}",
                       content="本条为虚构演示工单，设备和异常描述暂缺，等待人工补充。")
        orders.append(row)

    profiles = []
    for user_id, role, devices, faults in [
        ('synthetic-turbine', '汽轮机专工', {'TURBINE': 1.0, 'FWP': 0.7}, {'FAULT_VIBRATION': 0.8}),
        ('synthetic-electric', '电气专工', {'TRANSFORMER': 1.0, 'GENERATOR': 0.8, 'EXCITER': 0.9}, {'FAULT_ELECTRICAL': 0.8}),
        ('synthetic-boiler', '锅炉专工', {'BOILER': 1.0, 'FWP': 0.8}, {'FAULT_LEAKAGE': 0.8}),
    ]:
        profiles.append(dict(user_id=user_id, role=role, responsible_units=['#1'],
                             device_interests=devices, mfr_interests={}, fault_interests=faults,
                             keyword_interests={}, personal_tags=[]))
    return dict(metadata=dict(synthetic=True, seed=seed, count=count,
                              description="全部工单和画像均人工模拟；厂家名称仅用于匹配现有词典，不表示真实厂商事件。",
                              id_scope="编号仅对应本文件 catalogs，不可直接当作已有数据库外键。",
                              metrics="不含真实标签、准确率、召回率或任何模型效果评估。"),
                catalogs=catalogs, profiles=profiles, orders=orders)


def to_predict_request(order, catalogs, profile):
    def resolve(table, key):
        if key is None:
            return {}
        return next(row for row in catalogs[table] if row['id'] == key)

    unit = resolve('units', order['unit_id'])
    device = resolve('device_types', order['device_type_id'])
    mfr = resolve('manufacturers', order['manufacturer_id'])
    model = resolve('device_models', order['model_id'])
    return dict(order=dict(event_id=order['event_no'], title=order['title'], content=order['content'],
                           level=order['level'], unit_no=unit.get('unit_no'),
                           device_type_name=device.get('name'), manufacturer_name=mfr.get('name'),
                           model_code=model.get('model_code'), kks_code=order['kks_code'],
                           event_type=order['event_type']), profile=profile)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=320)
    parser.add_argument('--seed', type=int, default=20260909)
    args = parser.parse_args()
    data = generate(args.count, args.seed)
    output = ROOT / 'data' / 'synthetic'
    output.mkdir(parents=True, exist_ok=True)
    for name, value in [('dataset.json', data), ('predict_requests.json', [
        to_predict_request(order, data['catalogs'], data['profiles'][0]) for order in data['orders']
    ])]:
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Generated {len(data["orders"])} synthetic orders in {output}')


if __name__ == '__main__':
    main()
