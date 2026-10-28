-- ============================================================
-- 电厂工单智能推送系统 测试数据
-- 执行顺序：schema.sql 之后运行本文件
-- 可重复执行：开头的 TRUNCATE 确保幂等性
-- ============================================================

-- 清空所有业务数据（保留 device_types / manufacturers，它们在 schema.sql 里）
TRUNCATE TABLE
  push_results, push_configs, user_profiles, user_behaviors,
  nlp_extract_jobs, event_tags, event_attachments, events,
  tags, users, departments, units, plants, device_models
CASCADE;
-- 重置自增序列
ALTER SEQUENCE device_models_id_seq RESTART WITH 1;
ALTER SEQUENCE departments_id_seq   RESTART WITH 1;
ALTER SEQUENCE plants_id_seq        RESTART WITH 1;
ALTER SEQUENCE units_id_seq         RESTART WITH 1;
ALTER SEQUENCE tags_id_seq          RESTART WITH 1;
ALTER SEQUENCE push_configs_id_seq  RESTART WITH 1;

-- ============================================================
-- 1. 设备型号 device_models
-- ============================================================
INSERT INTO device_models(manufacturer_id, device_type_id, model_code, model_name, spec_json) VALUES
  (1, 1, 'N660-25/600/600', '660MW超超临界汽轮机', '{"power_mw":660,"steam_pressure":"25MPa","steam_temp":"600°C"}'),
  (1, 1, 'N330-16.7/537/537', '330MW亚临界汽轮机',  '{"power_mw":330,"steam_pressure":"16.7MPa","steam_temp":"537°C"}'),
  (2, 1, 'N1000-26.25/600/600','1000MW超超临界汽轮机','{"power_mw":1000,"steam_pressure":"26.25MPa","steam_temp":"600°C"}'),
  (3, 1, 'N660-24.2/566/566', '660MW超临界汽轮机',  '{"power_mw":660,"steam_pressure":"24.2MPa","steam_temp":"566°C"}'),
  (1, 2, 'QFSN-660-2', '660MW汽轮发电机',          '{"power_mw":660,"voltage":"27kV","power_factor":0.9}'),
  (2, 2, 'QFSN-1000-2','1000MW汽轮发电机',          '{"power_mw":1000,"voltage":"27kV","power_factor":0.9}'),
  (4, 3, 'NEC-660',    '660MW励磁系统',             '{"excitation_type":"静态励磁","voltage":"800V"}'),
  (5, 4, 'SFP-360000', '360MVA主变压器',            '{"capacity_mva":360,"voltage_ratio":"242/27kV"}'),
  (6, 4, 'OSFPS-720000','720MVA主变压器',           '{"capacity_mva":720,"voltage_ratio":"500/27kV"}'),
  (1, 5, 'SG-2100/25.4-M850','2100t/h超超临界锅炉','{"evaporation":"2100t/h","steam_pressure":"25.4MPa"}');

-- ============================================================
-- 2. 电厂 plants
-- ============================================================
INSERT INTO plants(code, name, location, capacity_mw, status) VALUES
  ('PLANT_HB01', '华北能源集团第一发电厂', '河北省保定市',   2640, 'operating'),
  ('PLANT_HB02', '华北能源集团第二发电厂', '河北省唐山市',   3960, 'operating'),
  ('PLANT_SD01', '山东电力集团莱芜发电厂', '山东省莱芜市',   2000, 'operating'),
  ('PLANT_HN01', '华能集团淮南发电厂',     '安徽省淮南市',   3200, 'operating'),
  ('PLANT_GD01', '广东能源粤电台山发电厂', '广东省台山市',   2400, 'maintenance');

-- ============================================================
-- 3. 机组 units
-- ============================================================
INSERT INTO units(plant_id, unit_no, capacity_mw, status) VALUES
  -- 华北一厂 (plant_id=1): 4×660MW
  (1, '#1', 660, 'operating'),
  (1, '#2', 660, 'operating'),
  (1, '#3', 660, 'operating'),
  (1, '#4', 660, 'operating'),
  -- 华北二厂 (plant_id=2): 4×660MW + 1×1000MW (部分检修)
  (2, '#1', 660,  'operating'),
  (2, '#2', 660,  'operating'),
  (2, '#3', 660,  'operating'),
  (2, '#4', 1000, 'maintenance'),
  -- 山东莱芜 (plant_id=3): 2×1000MW
  (3, '#1', 1000, 'operating'),
  (3, '#2', 1000, 'operating'),
  -- 华能淮南 (plant_id=4): 4×800MW
  (4, '#1', 800, 'operating'),
  (4, '#2', 800, 'operating'),
  (4, '#3', 800, 'operating'),
  (4, '#4', 800, 'operating'),
  -- 粤电台山 (plant_id=5): 2×1200MW (全厂检修)
  (5, '#1', 1200, 'maintenance'),
  (5, '#2', 1200, 'maintenance');

-- ============================================================
-- 4. 部门 departments
-- ============================================================
INSERT INTO departments(name, plant_id) VALUES
  ('汽轮机部',     1),
  ('电气部',       1),
  ('锅炉部',       1),
  ('运行部',       1),
  ('检修部',       1),
  ('汽轮机部',     2),
  ('电气部',       2),
  ('运行部',       2),
  ('检修部',       2),
  ('汽轮机部',     3),
  ('运行部',       3),
  ('检修部',       3);

-- ============================================================
-- 5. 用户 users（16人，覆盖不同角色与班组）
-- EMP001 使用固定 UUID，与 index.html 中 CURRENT_USER_ID 保持一致
-- ============================================================
INSERT INTO users(id, emp_no, name, department_id, plant_id, role, shift_group,
                  responsible_units, email, phone, push_enabled) VALUES
  ('00000000-0000-0000-0000-000000000001', 'EMP001', '张建国', 1, 1, '汽轮机专工', NULL, '["#1","#2"]', 'zhangjg@plant1.com', '13801001001', TRUE);

INSERT INTO users(emp_no, name, department_id, plant_id, role, shift_group,
                  responsible_units, email, phone, push_enabled) VALUES
  -- 华北一厂（其余用户）
  ('EMP002', '李梅',   1,  1, '汽轮机专工',   NULL,  '["#3","#4"]',       'limei@plant1.com',   '13801001002', TRUE),
  ('EMP003', '王志强', 2,  1, '电气专工',     NULL,  '["#1","#2","#3","#4"]','wangzq@plant1.com','13801001003', TRUE),
  ('EMP004', '陈磊',   4,  1, '运行值长',     'A',   '["#1","#2"]',       'chenlei@plant1.com', '13801001004', TRUE),
  ('EMP005', '刘芳',   4,  1, '运行值长',     'B',   '["#3","#4"]',       'liufang@plant1.com', '13801001005', TRUE),
  ('EMP006', '赵鹏',   5,  1, '检修工程师',   NULL,  '["#1","#2","#3","#4"]','zhaopeng@plant1.com','13801001006',TRUE),
  ('EMP007', '孙晓燕', 3,  1, '锅炉专工',     NULL,  '["#1","#2"]',       'sunxy@plant1.com',   '13801001007', TRUE),
  -- 华北二厂
  ('EMP008', '周海涛', 6,  2, '汽轮机专工',   NULL,  '["#1","#2"]',       'zhouht@plant2.com',  '13801002001', TRUE),
  ('EMP009', '吴丽娜', 6,  2, '汽轮机专工',   NULL,  '["#3","#4"]',       'wuln@plant2.com',    '13801002002', TRUE),
  ('EMP010', '郑强',   7,  2, '电气专工',     NULL,  '["#1","#2","#3","#4"]','zhengq@plant2.com','13801002003', TRUE),
  ('EMP011', '马超',   8,  2, '运行值长',     'A',   '["#1","#2","#3"]',  'machao@plant2.com',  '13801002004', TRUE),
  ('EMP012', '黄婷',   9,  2, '检修工程师',   NULL,  '["#1","#2","#3","#4"]','huangting@plant2.com','13801002005',TRUE),
  -- 山东莱芜
  ('EMP013', '徐明',   10, 3, '汽轮机专工',   NULL,  '["#1","#2"]',       'xuming@plant3.com',  '13801003001', TRUE),
  ('EMP014', '林静',   11, 3, '运行值长',     'C',   '["#1"]',            'linjing@plant3.com', '13801003002', TRUE),
  ('EMP015', '谢建伟', 12, 3, '检修工程师',   NULL,  '["#1","#2"]',       'xiejw@plant3.com',   '13801003003', TRUE),
  ('EMP016', '彭飞',   10, 3, '汽轮机专工',   NULL,  '["#1","#2"]',       'pengfei@plant3.com', '13801003004', TRUE);

-- ============================================================
-- 6. NLP 标签 tags
-- ============================================================
INSERT INTO tags(code, name, category, weight) VALUES
  -- 设备类型标签
  ('tag_turbine',     '汽轮机',     'device_type',   1.0),
  ('tag_generator',   '发电机',     'device_type',   1.0),
  ('tag_exciter',     '励磁系统',   'device_type',   1.0),
  ('tag_transformer', '变压器',     'device_type',   1.0),
  ('tag_boiler',      '锅炉',       'device_type',   1.0),
  ('tag_fwp',         '给水泵',     'device_type',   0.9),
  ('tag_cwp',         '循环水泵',   'device_type',   0.9),
  ('tag_condenser',   '凝汽器',     'device_type',   0.9),
  ('tag_acc',         '空冷系统',   'device_type',   0.9),
  -- 厂家标签
  ('tag_mfr_dfst',    '东方汽轮机', 'manufacturer',  1.0),
  ('tag_mfr_harbin',  '哈电集团',   'manufacturer',  1.0),
  ('tag_mfr_sec',     '上海电气',   'manufacturer',  1.0),
  ('tag_mfr_nari',    '南瑞继保',   'manufacturer',  1.0),
  -- 故障类型标签
  ('tag_fault_vib',   '振动超标',   'fault_type',    1.0),
  ('tag_fault_leak',  '泄漏',       'fault_type',    1.0),
  ('tag_fault_over',  '超温',       'fault_type',    1.0),
  ('tag_fault_bear',  '轴承故障',   'fault_type',    1.0),
  ('tag_fault_seal',  '密封失效',   'fault_type',    0.9),
  ('tag_fault_elec',  '电气故障',   'fault_type',    1.0),
  ('tag_fault_ctrl',  '控制系统故障','fault_type',   0.9),
  ('tag_fault_cool',  '冷却系统故障','fault_type',   0.9),
  -- 关键词标签
  ('tag_kw_rotor',    '转子',       'keyword',       0.9),
  ('tag_kw_blade',    '叶片',       'keyword',       0.9),
  ('tag_kw_bearing',  '轴承',       'keyword',       0.9),
  ('tag_kw_seal',     '汽封',       'keyword',       0.8),
  ('tag_kw_governor', '调速器',     'keyword',       0.8),
  ('tag_kw_lube',     '润滑油',     'keyword',       0.8),
  ('tag_kw_steam',    '蒸汽',       'keyword',       0.7),
  ('tag_kw_pressure', '压力',       'keyword',       0.7),
  ('tag_kw_temp',     '温度',       'keyword',       0.7),
  ('tag_kw_winding',  '绕组',       'keyword',       0.8),
  ('tag_kw_protect',  '保护装置',   'keyword',       0.8),
  -- 症状标签
  ('tag_sym_noise',   '异常噪声',   'symptom',       0.9),
  ('tag_sym_heat',    '过热',       'symptom',       0.9),
  ('tag_sym_smoke',   '冒烟',       'symptom',       1.0),
  ('tag_sym_trip',    '跳机',       'symptom',       1.0),
  ('tag_sym_alarm',   '报警',       'symptom',       0.8);

-- ============================================================
-- 7. 事件 events（30条，覆盖不同等级/类型/状态）
-- ============================================================
INSERT INTO events(event_no, plant_id, unit_id, device_type_id, manufacturer_id, model_id,
                   kks_code, title, content, level, event_type, status, occurred_at) VALUES

-- 华北一厂 #1机 紧急事件
('EVT-20260101-001', 1, 1, 1, 1, 1,
 '10MAA10AA001',
 '#1机汽轮机高压转子振动超标跳机',
 '#1机组汽轮机高压缸A侧轴承振动于2026-01-01 14:23突然上升，轴振峰值达到267μm，超过跳机保护定值250μm，机组自动跳闸。初步判断为高压缸第3级叶片断裂，碎片导致动静碰磨，现场检查已发现转子表面有划伤痕迹。需立即联系东方汽轮机厂家技术支持到场处理。',
 '紧急', '振动故障', 'processing',
 '2026-04-01 14:23:00+08'),

-- 华北一厂 #2机 重要事件
('EVT-20260103-002', 1, 2, 1, 1, 1,
 '10MAA20AA001',
 '#2机高压调节汽门卡涩导致出力受限',
 '#2机组高压调节汽门4号阀门卡涩，无法全开，机组最大出力受限至530MW（设计额定660MW）。经检查为调节阀油动机内部油缸密封圈老化失效，导致伺服油泄漏，阀门动作迟缓。建议在下次计划停机时更换密封组件，目前限负荷运行，加强监视。',
 '重要', '调节系统故障', 'processing',
 '2026-04-03 09:15:00+08'),

-- 华北一厂 #1机 一般事件
('EVT-20260105-003', 1, 1, 6, 1, NULL,
 '10LAB10AP001',
 '#1机A侧给水泵密封水流量偏低报警',
 '#1机A侧汽动给水泵机械密封冷却水流量低于设计值，密封水流量报警（设计值18L/min，当前15.2L/min）。已现场检查密封水过滤器，滤芯有轻微堵塞，已进行反冲洗，暂时恢复正常。建议利用近期小修机会更换密封水过滤器滤芯，并对机械密封状态进行全面检查。',
 '一般', '密封故障', 'closed',
 '2026-04-05 16:40:00+08'),

-- 华北一厂 #3机 励磁系统故障
('EVT-20260108-004', 1, 3, 3, 4, 7,
 '10EXC30AA001',
 '#3机励磁系统AVR通道切换异常',
 '#3机励磁系统AVR主通道发生故障切换至备用通道时，短暂出现励磁电流波动，发电机机端电压在0.5秒内从额定27kV跌落至24.8kV，AGC自动响应减少无功输出。励磁系统已切换至备用AVR运行，电压恢复正常。需对主AVR控制板进行检修，排查故障原因。',
 '重要', '电气故障', 'processing',
 '2026-04-07 22:10:00+08'),

-- 华北一厂 #4机 锅炉
('EVT-20260110-005', 1, 4, 5, 1, 10,
 '10HAB40AA001',
 '#4机锅炉A侧水冷壁管超温报警',
 '#4机锅炉燃烧器A侧区域水冷壁管壁温度超过设计限值，最高点测温达到478°C（设计限值450°C），已调整燃烧器配风，降低该区域热负荷。初步分析为A侧磨煤机出口粉量偏多，燃烧偏斜，已调整磨煤机运行参数，管壁温度有所下降，继续监视中。',
 '重要', '超温故障', 'processing',
 '2026-04-09 11:30:00+08'),

-- 华北一厂 一般/建议事件
('EVT-20260112-006', 1, 2, 1, 1, 1,
 '10MAA20BP001',
 '#2机低压转子末级叶片测量建议',
 '根据本轮大修检查计划，建议对#2机低压转子末级（L-0级）叶片进行全面PT探伤检查，上次检查于2024年大修完成，已运行约18000小时，接近制造厂商建议检查周期（20000小时）。同时建议对叶根部位应力腐蚀情况进行重点检查，近年来同类型机组存在叶根腐蚀疲劳裂纹案例。',
 '建议', '预防性检查', 'open',
 '2026-05-03 08:00:00+08'),

-- 华北二厂事件
('EVT-20260115-007', 2, 5, 1, 1, 2,
 '20MAA10AA001',
 '#1机中压缸轴封漏汽量增大',
 '华北二厂#1机中压缸前轴封漏汽量监测值异常增大，汽封蒸汽流量从正常值2.1t/h增至3.8t/h，轴封腔室压力偏高。初步判断为中压缸前汽封片磨损严重，导致汽封间隙增大。目前已调整轴封调整器压力设定，抑制漏汽。计划在2月份计划检修中进行汽封片更换。',
 '一般', '泄漏故障', 'processing',
 '2026-04-11 14:20:00+08'),

('EVT-20260118-008', 2, 6, 4, 5, 8,
 '20BBA20AA001',
 '#2机主变压器冷却器控制回路故障',
 '#2机主变压器冷却器自动投切控制回路出现故障，冷却风扇无法按温度自动启停，需要人工手动控制，增加了运行人员操作负担。经电气人员检查，发现控制板继电器触点接触不良，氧化严重。已联系特变电工厂家发送备件，预计3日内到货更换。',
 '一般', '电气故障', 'processing',
 '2026-04-12 10:05:00+08'),

('EVT-20260120-009', 2, 7, 1, 2, 3,
 '20MAA30AA001',
 '#3机高压缸效率下降分析报告',
 '#3机高压缸热力性能监测数据显示，缸效率较上次大修后下降约1.8%（当前82.3%，大修后84.1%），蒸汽消耗率偏高，影响机组发电煤耗。分析原因可能为高压缸内通流面积因结垢或腐蚀有所变化。建议在下次计划停机时进行高压缸揭缸检查，重点检查隔板、叶栅和汽封状态。',
 '建议', '性能劣化', 'open',
 '2026-04-13 09:00:00+08'),

('EVT-20260122-010', 2, 8, 1, 2, 3,
 '20MAA40AA001',
 '#4机（1000MW）高中压导汽管焊口超声波异常',
 '#4机1000MW汽轮机年度预防性检查中，对高中压导汽管焊口进行超声波探伤，发现2号焊口存在疑似缺陷回波，缺陷当量约Φ3.0mm，位于焊缝热影响区。已停机待哈电集团技术支持人员到场复测确认，若确认为裂纹缺陷，需进行焊口挖补修复后方可恢复运行。',
 '紧急', '裂纹缺陷', 'processing',
 '2026-04-14 16:00:00+08'),

-- 山东莱芜电厂
('EVT-20260125-011', 3, 9, 1, 2, 3,
 '30MAA10AA001',
 '#1机轴承巴氏合金温度异常升高',
 '莱芜电厂#1机5号轴承（中压转子前轴承）巴氏合金温度持续升高，当前温度96°C，接近保护定值105°C。已降低机组负荷至额定的80%，并增大润滑油流量，温度上升趋势有所缓解。初步判断为油膜失稳或轴承乌金局部脱落，需跟踪监视，若继续升高则需启动降负荷甩负荷预案。',
 '紧急', '轴承故障', 'processing',
 '2026-04-15 03:45:00+08'),

('EVT-20260127-012', 3, 10, 2, 2, 6,
 '30MKA20AA001',
 '#2机发电机定子绕组绝缘异常',
 '莱芜电厂#2机发电机在线绝缘监测系统报警，A相定子绕组对地绝缘电阻降低至185MΩ（正常值>500MΩ），局放量有所增大。分析可能原因：定子端部绑扎松动导致线棒振动磨损、或冷却水系统微量渗漏进入绕组绝缘层。建议尽快安排停机进行定子绝缘系统全面检查。',
 '重要', '电气故障', 'open',
 '2026-04-16 11:20:00+08'),

('EVT-20260201-013', 3, 9, 7, 1, NULL,
 '30LAC10AP001',
 '#1机循环水泵A泵振动偏大',
 '莱芜电厂#1机循环水A泵（立式斜流泵）振动监测值持续偏高，泵体垂直方向振动6.8mm/s（报警值5.0mm/s）。已对泵体地脚螺栓和联轴器对中进行复查，对中偏差在允许范围内。怀疑为叶轮流道内有异物导致水力不平衡，计划在本周末停泵进行检查。',
 '一般', '振动故障', 'processing',
 '2026-04-17 14:30:00+08'),

('EVT-20260203-014', 1, 1, 1, 1, 1,
 '10MAA10AA002',
 '#1机修复后恢复并网调试正常',
 '#1机汽轮机高压转子叶片修复工作已完成（见EVT-20260101-001），更换了3-5级损坏叶片，经精密动平衡后装机。机组已于2026-02-03完成冲转、升速、并网调试，各轴承振动值正常（最大值56μm），各参数均在设计范围内。机组恢复满负荷运行。',
 '一般', '恢复正常', 'closed',
 '2026-04-18 18:00:00+08'),

('EVT-20260205-015', 2, 5, 1, 1, 2,
 '20MAA10BP001',
 '#1机汽轮机调速系统DEH升级改造建议',
 '华北二厂#1机DEH系统运行已超过15年，现有系统存在备件供货困难、通信接口老旧等问题。建议利用2026年大修机会，对DEH系统进行升级改造，采用国产化新型控制器替代现有进口模块，提高系统可靠性和可维护性。预计改造工期约30天，需纳入大修计划。',
 '建议', '设备改造', 'open',
 '2026-04-19 10:00:00+08'),

('EVT-20260207-016', 1, 3, 5, 1, 10,
 '10HAB30AA001',
 '#3机锅炉脱硝催化剂活性下降',
 '#3机SCR脱硝系统催化剂运行约24000小时，近期NOx排放浓度出现上升趋势，脱硝效率从设计值90%降至82%，已不能稳定满足排放标准（≤50mg/Nm³）。建议在本次大修中对催化剂进行活化处理或部分更换，同时优化氨喷射系统喷嘴，改善氨-烟气混合效果。',
 '重要', '环保超标', 'processing',
 '2026-04-20 09:30:00+08'),

('EVT-20260210-017', 2, 6, 2, 1, 5,
 '20MKA20AA001',
 '#2机发电机冷却器冷却水管轻微渗漏',
 '华北二厂#2机发电机定子冷却水回路巡检发现，冷却器出口水管法兰处有轻微渗漏，水迹约一茶杯量，未见明显流淌。已紧固法兰螺栓，渗漏有所减小但未完全消除。初步判断为法兰密封垫片老化失效，已准备备件，计划在本周末小停机更换密封垫片。',
 '一般', '泄漏故障', 'processing',
 '2026-04-21 15:20:00+08'),

('EVT-20260212-018', 1, 2, 1, 1, 1,
 '10MAA20AA002',
 '#2机高压调节门修复后性能验证',
 '#2机高压调节汽门4号阀门密封圈更换工作完成（见EVT-20260103-002）。经调试验证，阀门动作响应时间恢复正常（全行程动作时间<3s），阀门全开时机组可达额定出力660MW，油动机伺服油压正常，无泄漏。工单闭合。',
 '建议', '恢复正常', 'closed',
 '2026-04-22 16:45:00+08'),

('EVT-20260215-019', 3, 9, 1, 2, 3,
 '30MAA10BP001',
 '#1机高压转子弯曲度超标预警',
 '莱芜电厂#1机高压转子连续盘车监测期间，转子弯曲度测量值为0.058mm，超过制造厂家建议的启机安全限值（0.05mm/m），暂缓升速。已联系哈电集团技术人员远程会诊，建议延长低速暖机时间至6小时，并在达到临界转速时重点监视振动变化趋势。若振动稳定则可继续升速至额定。',
 '重要', '振动故障', 'processing',
 '2026-04-23 05:30:00+08'),

('EVT-20260218-020', 1, 4, 8, 1, NULL,
 '10MAB40AA001',
 '#4机凝汽器真空度下降分析',
 '#4机凝汽器真空度由正常-96.5kPa下降至-94.2kPa，排汽温度相应升高，热耗上升约0.5%。对凝汽器进行热力清洗效果不明显，怀疑为铜管局部泄漏导致漏空气进入真空系统。已对真空严密性进行测试，查漏结果确认有3处微小漏点。计划近期停机对泄漏管子进行堵管处理。',
 '一般', '真空下降', 'processing',
 '2026-04-24 13:00:00+08'),

-- 新近事件（3月、4月）
('EVT-20260305-021', 1, 1, 1, 1, 1,
 '10MAA10AA003',
 '#1机高压缸汽封间隙偏大需调整',
 '#1机大修揭缸后检查发现，高压缸前汽封径向间隙普遍偏大，部分测量值比设计图纸上限超出0.15-0.28mm，预计影响汽封效率，导致泄汽量增加约15%。已向东方汽轮机厂请购汽封片备件，计划在本次大修中统一更换，恢复设计间隙值。',
 '一般', '密封故障', 'processing',
 '2026-04-25 08:30:00+08'),

('EVT-20260310-022', 2, 8, 1, 2, 3,
 '20MAA40AA002',
 '#4机（1000MW）导汽管焊口修复完成恢复运行',
 '#4机1000MW汽轮机2号导汽管焊口修复工作已完成（见EVT-20260122-010）。挖补长度约80mm，采用TIG焊工艺，焊后经RT+UT+MT复验合格，热处理硬度检验符合要求。机组于2026-03-10完成启动，各项参数正常，导汽管测点无异常。工单闭合。',
 '重要', '裂纹缺陷', 'closed',
 '2026-04-26 20:00:00+08'),

('EVT-20260315-023', 3, 10, 2, 2, 6,
 '30MKA20AA002',
 '#2机发电机定子绕组绝缘修复方案确认',
 '根据EVT-20260127-012，莱芜电厂#2机发电机停机检查结果：定子端部2处线棒固定绑扎松动，绑扎胶带磨损，局部绝缘层轻微损伤。修复方案：对松动绑扎处重新固紧，损伤绝缘处进行局部补涂绝缘漆，修复后进行整体绝缘电阻、直流电阻和局放量检测。预计修复工期5天。',
 '重要', '电气故障', 'processing',
 '2026-04-27 10:00:00+08'),

('EVT-20260320-024', 1, 2, 1, 1, 1,
 '10MAA20AA003',
 '#2机汽轮机油系统润滑油颗粒度超标',
 '#2机汽轮机润滑油年度取样化验结果显示，颗粒度NAS等级为10级，超过设计允许值（8级），油品清洁度不达标。分析原因为油系统过滤器滤芯更换周期过长，已更换全部油过滤器滤芯，并增加在线过滤装置，对系统进行循环过滤。两周后复验合格后可解除监视。',
 '一般', '油品异常', 'processing',
 '2026-04-28 09:00:00+08'),

('EVT-20260325-025', 2, 5, 6, 1, NULL,
 '20LAB10AP001',
 '#1机A给水泵汽轮机排汽压力偏高',
 '华北二厂#1机A侧汽动给水泵汽轮机排汽压力持续偏高，正常值应<15kPa(a)，当前测量值18.5kPa(a)，影响给泵效率，主给水流量偏低约3%。排查原因为给泵汽轮机排汽至低压加热器连通管道上的阀门开度不足，调整阀门开度后排汽压力恢复正常。',
 '一般', '压力异常', 'closed',
 '2026-04-29 11:30:00+08'),

('EVT-20260401-026', 1, 3, 3, 4, 7,
 '10EXC30AA002',
 '#3机励磁系统主AVR修复验证',
 '#3机励磁系统主AVR控制板已完成检修（见EVT-20260108-004），更换了故障的PWM驱动芯片和光耦隔离器，经工厂测试台测试各项指标合格。已重新投入主AVR通道运行，备用通道热备用，AVR通道切换试验正常，机端电压调节响应时间符合设计要求。工单闭合。',
 '一般', '电气故障', 'closed',
 '2026-04-30 14:00:00+08'),

('EVT-20260405-027', 3, 9, 1, 2, 3,
 '30MAA10AA002',
 '#1机高压转子中心孔探伤检查',
 '莱芜电厂#1机高压转子按计划进行中心孔超声波探伤检查，检查长度约3200mm。检查结果：在距汽轮机端1850mm处发现一处轴向缺陷回波，缺陷当量约Φ2.0mm，位于中心孔内壁。已请哈电集团专家进行会商，目前确认为制造时原始缺陷，尺寸未见增大，按监控档案存档，下次检修重点复检。',
 '重要', '裂纹缺陷', 'open',
 '2026-05-01 09:00:00+08'),

('EVT-20260408-028', 1, 4, 9, 1, NULL,
 '10MAF40AA001',
 '#4机空冷系统A列散热翅片积灰严重',
 '#4机空冷系统A列（共6列）散热翅片积灰严重，翅片堵塞率目测约30%，导致该列散热效果下降，机组背压上升约1.2kPa，热耗上升。建议安排高压水冲洗作业，清除翅片积灰，恢复散热效率。同时检查自动清洗系统喷嘴是否堵塞。预计冲洗工时约8小时/列。',
 '建议', '积灰堵塞', 'open',
 '2026-05-02 10:30:00+08'),

('EVT-20260410-029', 2, 7, 1, 1, 2,
 '20MAA30AA002',
 '#3机高压缸内缸螺栓预紧力复查建议',
 '华北二厂#3机高压缸已连续运行约22000小时，上次螺栓检查在18000小时（2024年大修），建议在即将到来的2026年4月小修中对高压缸内缸水平结合面螺栓预紧力进行全面复查，包括力矩检查和螺栓伸长量测量，防止因螺栓松弛导致高压缸密封不严，出现漏汽问题。',
 '建议', '预防性检查', 'open',
 '2026-05-03 08:00:00+08'),

('EVT-20260412-030', 1, 1, 1, 1, 1,
 '10MAA10AA004',
 '#1机组低压转子末级叶片PT探伤发现裂纹',
 '#1机低压转子末级（L-0级）叶片PT探伤检查，在17号叶片叶根圆弧过渡区发现一条长约12mm的线状缺陷，经复验确认为疲劳裂纹。该裂纹位于叶根应力集中区，存在扩展风险。已停机，联系东方汽轮机厂技术部门会商处理方案，初步决定更换该叶片及相邻叶片，进行动平衡后重新装机。预计处理工期10-15天。',
 '紧急', '裂纹缺陷', 'processing',
 '2026-05-04 21:30:00+08'),

-- ★ 今日事件（2026-04-13）—— 确保 push engine 运行时能查到
('EVT-20260413-031', 1, 1, 1, 1, 1,
 '10MAA10AA005',
 '#1机高压缸第2级隔板汽封片脱落报警',
 '#1机停机检修期间检查发现，高压缸第2级隔板汽封片有一段（约80mm）脱落，脱落片已随蒸汽流冲至下级叶栅，导致高压缸第2-3级叶片前缘出现轻微划伤。目前已清理脱落碎片，受损叶片经评估可继续使用，汽封片将进行整体更换。计划本次大修中同步更换第1-5级所有汽封片，恢复汽封间隙至设计值。',
 '重要', '密封故障', 'processing',
 NOW()),

('EVT-20260413-032', 1, 2, 6, 1, NULL,
 '10LAB20AP001',
 '#2机B侧给水泵轴承振动突升紧急停泵',
 '#2机B侧汽动给水泵驱动端轴承振动于今日08:12突升至12.4mm/s，超过联锁停泵定值（10mm/s），给水泵自动跳闸。已切换至A侧给水泵运行，主给水流量维持正常。现场检查B给水泵联轴器对中偏差较大，初步判断为对中偏差导致轴承受力异常，计划当日下午进行联轴器重新对中和轴承检查。',
 '紧急', '振动故障', 'processing',
 NOW());

-- ============================================================
-- 8. 事件标签关联 event_tags
-- ============================================================
-- EVT-20260101-001 (汽轮机振动跳机) -> 取第一条事件ID需动态处理，用子查询
INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.98, 'nlp'
FROM events e, tags t
WHERE e.event_no = 'EVT-20260101-001' AND t.code IN (
  'tag_turbine','tag_fault_vib','tag_sym_trip','tag_kw_blade','tag_kw_rotor','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.95, 'nlp'
FROM events e, tags t
WHERE e.event_no = 'EVT-20260103-002' AND t.code IN (
  'tag_turbine','tag_fault_ctrl','tag_kw_governor','tag_fault_seal','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.92, 'nlp'
FROM events e, tags t
WHERE e.event_no = 'EVT-20260105-003' AND t.code IN (
  'tag_fwp','tag_fault_seal','tag_fault_leak','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.97, 'nlp'
FROM events e, tags t
WHERE e.event_no = 'EVT-20260108-004' AND t.code IN (
  'tag_exciter','tag_fault_elec','tag_sym_alarm','tag_mfr_nari');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.94, 'nlp'
FROM events e, tags t
WHERE e.event_no = 'EVT-20260110-005' AND t.code IN (
  'tag_boiler','tag_fault_over','tag_sym_heat','tag_kw_temp','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.90, 'nlp'
FROM events e, tags t
WHERE e.event_no = 'EVT-20260112-006' AND t.code IN (
  'tag_turbine','tag_kw_blade','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.93, 'nlp'
FROM events e, tags t
WHERE e.event_no = 'EVT-20260115-007' AND t.code IN (
  'tag_turbine','tag_fault_leak','tag_kw_seal','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.91, 'nlp'
FROM events e, tags t
WHERE e.event_no = 'EVT-20260118-008' AND t.code IN (
  'tag_transformer','tag_fault_elec','tag_fault_cool','tag_mfr_tbea');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.88, 'nlp'
FROM events e, tags t
WHERE e.event_no = 'EVT-20260120-009' AND t.code IN (
  'tag_turbine','tag_kw_blade','tag_mfr_harbin');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.98, 'nlp'
FROM events e, tags t
WHERE e.event_no = 'EVT-20260122-010' AND t.code IN (
  'tag_turbine','tag_fault_seal','tag_mfr_harbin');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.96, 'nlp'
FROM events e, tags t
WHERE e.event_no = 'EVT-20260125-011' AND t.code IN (
  'tag_turbine','tag_fault_bear','tag_kw_bearing','tag_kw_lube','tag_mfr_harbin');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.95, 'nlp'
FROM events e, tags t
WHERE e.event_no = 'EVT-20260127-012' AND t.code IN (
  'tag_generator','tag_fault_elec','tag_kw_winding','tag_mfr_harbin');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.90, 'nlp'
FROM events e, tags t
WHERE e.event_no = 'EVT-20260201-013' AND t.code IN (
  'tag_cwp','tag_fault_vib','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.85, 'nlp'
FROM events e, tags t
WHERE e.event_no = 'EVT-20260203-014' AND t.code IN (
  'tag_turbine','tag_kw_blade','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.87, 'nlp'
FROM events e, tags t
WHERE e.event_no = 'EVT-20260207-016' AND t.code IN (
  'tag_boiler','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.89, 'nlp'
FROM events e, tags t
WHERE e.event_no = 'EVT-20260210-017' AND t.code IN (
  'tag_generator','tag_fault_leak','tag_fault_cool','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.96, 'nlp'
FROM events e, tags t
WHERE e.event_no = 'EVT-20260412-030' AND t.code IN (
  'tag_turbine','tag_kw_blade','tag_kw_rotor','tag_mfr_dfst','tag_fault_bear');

-- ============================================================
-- 9. 用户行为记录 user_behaviors（每位主要用户约 20-30 条）
-- ============================================================

-- EMP001 张建国（汽轮机专工，#1#2机）-- 关注振动/叶片/东方汽轮机
INSERT INTO user_behaviors(user_id, session_id, page_url, module, action_type,
    query_content, query_fields, selected_event_id,
    data_type_tags, result_count, enter_time, leave_time,
    mouse_max_stay_sec, scroll_depth_pct)
SELECT
  u.id,
  'sess-001-' || gs::text,
  '/events',
  CASE (gs % 3) WHEN 0 THEN '事件信息库' WHEN 1 THEN '状态报告' ELSE '工单管理' END,
  CASE (gs % 4) WHEN 0 THEN 'query' WHEN 1 THEN 'detail' WHEN 2 THEN 'export' ELSE 'query' END,
  CASE (gs % 5)
    WHEN 0 THEN '汽轮机振动'
    WHEN 1 THEN '叶片裂纹'
    WHEN 2 THEN '高压缸故障'
    WHEN 3 THEN '东方汽轮机'
    ELSE '轴承温度'
  END,
  ('{"device_type":"汽轮机","plant":"华北一厂"}'::jsonb),
  (SELECT id FROM events WHERE event_no IN ('EVT-20260101-001','EVT-20260412-030','EVT-20260305-021','EVT-20260203-014') ORDER BY RANDOM() LIMIT 1),
  '["tag_turbine","tag_fault_vib","tag_kw_blade"]'::jsonb,
  (5 + gs % 20),
  NOW() - ((90 - gs) || ' days')::interval + (gs % 24 || ' hours')::interval,
  NOW() - ((90 - gs) || ' days')::interval + (gs % 24 || ' hours')::interval + ((180 + gs * 30) || ' seconds')::interval,
  (30 + gs * 10 % 180),
  (40 + gs * 7 % 60)
FROM users u, generate_series(1, 28) gs
WHERE u.emp_no = 'EMP001';

-- EMP002 李梅（汽轮机专工，#3#4机）-- 关注汽封/调速/东方
INSERT INTO user_behaviors(user_id, session_id, page_url, module, action_type,
    query_content, query_fields, selected_event_id,
    data_type_tags, result_count, enter_time, leave_time,
    mouse_max_stay_sec, scroll_depth_pct)
SELECT
  u.id, 'sess-002-' || gs::text, '/events',
  CASE (gs % 3) WHEN 0 THEN '事件信息库' WHEN 1 THEN '工单管理' ELSE '状态报告' END,
  CASE (gs % 3) WHEN 0 THEN 'query' WHEN 1 THEN 'detail' ELSE 'export' END,
  CASE (gs % 4) WHEN 0 THEN '汽封间隙' WHEN 1 THEN '调速系统' WHEN 2 THEN '油系统' ELSE '叶片检查' END,
  ('{"device_type":"汽轮机","unit":["#3","#4"]}'::jsonb),
  (SELECT id FROM events WHERE event_no IN ('EVT-20260103-002','EVT-20260305-021','EVT-20260320-024') ORDER BY RANDOM() LIMIT 1),
  '["tag_turbine","tag_kw_seal","tag_kw_governor"]'::jsonb,
  (3 + gs % 15),
  NOW() - ((85 - gs) || ' days')::interval + (gs % 20 || ' hours')::interval,
  NOW() - ((85 - gs) || ' days')::interval + (gs % 20 || ' hours')::interval + ((120 + gs * 25) || ' seconds')::interval,
  (20 + gs * 8 % 150),
  (50 + gs * 5 % 50)
FROM users u, generate_series(1, 22) gs
WHERE u.emp_no = 'EMP002';

-- EMP003 王志强（电气专工）-- 关注发电机/励磁/变压器
INSERT INTO user_behaviors(user_id, session_id, page_url, module, action_type,
    query_content, query_fields, selected_event_id,
    data_type_tags, result_count, enter_time, leave_time,
    mouse_max_stay_sec, scroll_depth_pct)
SELECT
  u.id, 'sess-003-' || gs::text, '/events',
  CASE (gs % 2) WHEN 0 THEN '事件信息库' ELSE '状态报告' END,
  CASE (gs % 3) WHEN 0 THEN 'query' WHEN 1 THEN 'detail' ELSE 'download' END,
  CASE (gs % 4) WHEN 0 THEN '励磁系统故障' WHEN 1 THEN '发电机绝缘' WHEN 2 THEN '变压器冷却' ELSE '绕组温度' END,
  ('{"device_type":"励磁系统","plant":"华北一厂"}'::jsonb),
  (SELECT id FROM events WHERE event_no IN ('EVT-20260108-004','EVT-20260401-026','EVT-20260210-017') ORDER BY RANDOM() LIMIT 1),
  '["tag_exciter","tag_generator","tag_fault_elec","tag_kw_winding"]'::jsonb,
  (4 + gs % 12),
  NOW() - ((80 - gs) || ' days')::interval + (gs % 18 || ' hours')::interval,
  NOW() - ((80 - gs) || ' days')::interval + (gs % 18 || ' hours')::interval + ((90 + gs * 20) || ' seconds')::interval,
  (15 + gs * 6 % 120),
  (45 + gs * 4 % 55)
FROM users u, generate_series(1, 20) gs
WHERE u.emp_no = 'EMP003';

-- EMP004 陈磊（运行值长）-- 查询各类报警，关注多设备
INSERT INTO user_behaviors(user_id, session_id, page_url, module, action_type,
    query_content, query_fields, selected_event_id,
    data_type_tags, result_count, enter_time, leave_time,
    mouse_max_stay_sec, scroll_depth_pct)
SELECT
  u.id, 'sess-004-' || gs::text, '/dashboard',
  '事件信息库',
  CASE (gs % 4) WHEN 0 THEN 'query' WHEN 1 THEN 'query' WHEN 2 THEN 'detail' ELSE 'print' END,
  CASE (gs % 5) WHEN 0 THEN '紧急事件' WHEN 1 THEN '今日报警' WHEN 2 THEN '振动超标' WHEN 3 THEN '轴承温度' ELSE '跳机事件' END,
  ('{"level":"紧急","plant":"华北一厂"}'::jsonb),
  (SELECT id FROM events WHERE plant_id = 1 ORDER BY RANDOM() LIMIT 1),
  '["tag_sym_alarm","tag_sym_trip","tag_fault_vib"]'::jsonb,
  (10 + gs % 30),
  NOW() - ((88 - gs) || ' days')::interval + (gs % 22 || ' hours')::interval,
  NOW() - ((88 - gs) || ' days')::interval + (gs % 22 || ' hours')::interval + ((60 + gs * 15) || ' seconds')::interval,
  (10 + gs * 5 % 90),
  (60 + gs * 3 % 40)
FROM users u, generate_series(1, 30) gs
WHERE u.emp_no = 'EMP004';

-- EMP008 周海涛（华北二厂汽轮机专工）-- 关注哈电/振动/轴承
INSERT INTO user_behaviors(user_id, session_id, page_url, module, action_type,
    query_content, query_fields, selected_event_id,
    data_type_tags, result_count, enter_time, leave_time,
    mouse_max_stay_sec, scroll_depth_pct)
SELECT
  u.id, 'sess-008-' || gs::text, '/events',
  CASE (gs % 3) WHEN 0 THEN '事件信息库' WHEN 1 THEN '工单管理' ELSE '状态报告' END,
  CASE (gs % 3) WHEN 0 THEN 'query' WHEN 1 THEN 'detail' ELSE 'export' END,
  CASE (gs % 4) WHEN 0 THEN '哈电汽轮机' WHEN 1 THEN '振动分析' WHEN 2 THEN '轴承故障' ELSE '高压缸效率' END,
  ('{"manufacturer":"哈电集团","device_type":"汽轮机"}'::jsonb),
  (SELECT id FROM events WHERE event_no IN ('EVT-20260122-010','EVT-20260120-009','EVT-20260310-022') ORDER BY RANDOM() LIMIT 1),
  '["tag_turbine","tag_mfr_harbin","tag_fault_vib","tag_fault_bear"]'::jsonb,
  (5 + gs % 18),
  NOW() - ((75 - gs) || ' days')::interval + (gs % 16 || ' hours')::interval,
  NOW() - ((75 - gs) || ' days')::interval + (gs % 16 || ' hours')::interval + ((150 + gs * 35) || ' seconds')::interval,
  (25 + gs * 9 % 160),
  (55 + gs * 4 % 45)
FROM users u, generate_series(1, 25) gs
WHERE u.emp_no = 'EMP008';

-- EMP013 徐明（山东莱芜汽轮机专工）-- 关注哈电/裂纹/转子
INSERT INTO user_behaviors(user_id, session_id, page_url, module, action_type,
    query_content, query_fields, selected_event_id,
    data_type_tags, result_count, enter_time, leave_time,
    mouse_max_stay_sec, scroll_depth_pct)
SELECT
  u.id, 'sess-013-' || gs::text, '/events',
  CASE (gs % 3) WHEN 0 THEN '事件信息库' WHEN 1 THEN '状态报告' ELSE '工单管理' END,
  CASE (gs % 3) WHEN 0 THEN 'query' WHEN 1 THEN 'detail' ELSE 'download' END,
  CASE (gs % 5) WHEN 0 THEN '转子裂纹' WHEN 1 THEN '探伤检查' WHEN 2 THEN '轴承温度高' WHEN 3 THEN '中心孔' ELSE '弯曲振动' END,
  ('{"manufacturer":"哈电集团","plant":"山东莱芜"}'::jsonb),
  (SELECT id FROM events WHERE event_no IN ('EVT-20260125-011','EVT-20260215-019','EVT-20260405-027') ORDER BY RANDOM() LIMIT 1),
  '["tag_turbine","tag_mfr_harbin","tag_kw_rotor","tag_fault_bear"]'::jsonb,
  (6 + gs % 14),
  NOW() - ((70 - gs) || ' days')::interval + (gs % 14 || ' hours')::interval,
  NOW() - ((70 - gs) || ' days')::interval + (gs % 14 || ' hours')::interval + ((200 + gs * 40) || ' seconds')::interval,
  (35 + gs * 11 % 200),
  (65 + gs * 3 % 35)
FROM users u, generate_series(1, 24) gs
WHERE u.emp_no = 'EMP013';

-- EMP006 赵鹏（华北一厂检修工程师）-- 广泛查询各类故障
INSERT INTO user_behaviors(user_id, session_id, page_url, module, action_type,
    query_content, query_fields, selected_event_id,
    data_type_tags, result_count, enter_time, leave_time,
    mouse_max_stay_sec, scroll_depth_pct)
SELECT
  u.id, 'sess-006-' || gs::text, '/events',
  '工单管理',
  CASE (gs % 4) WHEN 0 THEN 'query' WHEN 1 THEN 'detail' WHEN 2 THEN 'export' ELSE 'print' END,
  CASE (gs % 6)
    WHEN 0 THEN '密封检修'
    WHEN 1 THEN '叶片更换'
    WHEN 2 THEN '轴承检修'
    WHEN 3 THEN '动平衡调试'
    WHEN 4 THEN '汽封调整'
    ELSE '焊口探伤'
  END,
  ('{"plant":"华北一厂","status":"processing"}'::jsonb),
  (SELECT id FROM events WHERE plant_id = 1 ORDER BY RANDOM() LIMIT 1),
  '["tag_turbine","tag_fault_seal","tag_fault_bear","tag_kw_blade"]'::jsonb,
  (8 + gs % 25),
  NOW() - ((82 - gs) || ' days')::interval + (gs % 20 || ' hours')::interval,
  NOW() - ((82 - gs) || ' days')::interval + (gs % 20 || ' hours')::interval + ((240 + gs * 50) || ' seconds')::interval,
  (40 + gs * 12 % 240),
  (70 + gs * 2 % 30)
FROM users u, generate_series(1, 26) gs
WHERE u.emp_no = 'EMP006';

-- ============================================================
-- 10. 用户画像 user_profiles
-- ============================================================
INSERT INTO user_profiles(user_id, device_interests, mfr_interests, fault_interests,
                          keyword_interests, personal_tags, profile_vector,
                          total_behaviors, active_days_30, avg_stay_sec, last_computed_at)
SELECT u.id,
  '{"1":0.95,"2":0.35,"5":0.20}'::jsonb,
  '{"1":0.92,"2":0.15}'::jsonb,
  '{"振动超标":0.88,"裂纹缺陷":0.75,"密封故障":0.60}'::jsonb,
  '{"叶片":0.90,"转子":0.85,"轴承":0.70,"汽封":0.55}'::jsonb,
  '["汽轮机","振动","叶片裂纹","东方汽轮机","高压缸"]'::jsonb,
  '[0.95,0.35,0.20,0.92,0.15,0.88,0.75,0.60,0.90,0.85,0.70,0.55]'::jsonb,
  28, 25, 320, NOW() - interval '2 hours'
FROM users u WHERE u.emp_no = 'EMP001';

INSERT INTO user_profiles(user_id, device_interests, mfr_interests, fault_interests,
                          keyword_interests, personal_tags, profile_vector,
                          total_behaviors, active_days_30, avg_stay_sec, last_computed_at)
SELECT u.id,
  '{"1":0.88,"6":0.42}'::jsonb,
  '{"1":0.85}'::jsonb,
  '{"密封故障":0.82,"调节系统故障":0.75,"油品异常":0.55}'::jsonb,
  '{"汽封":0.88,"调速器":0.78,"润滑油":0.65}'::jsonb,
  '["汽轮机","汽封","调速系统","润滑油"]'::jsonb,
  '[0.88,0.42,0.00,0.85,0.00,0.82,0.75,0.55,0.88,0.78,0.65,0.00]'::jsonb,
  22, 20, 270, NOW() - interval '3 hours'
FROM users u WHERE u.emp_no = 'EMP002';

INSERT INTO user_profiles(user_id, device_interests, mfr_interests, fault_interests,
                          keyword_interests, personal_tags, profile_vector,
                          total_behaviors, active_days_30, avg_stay_sec, last_computed_at)
SELECT u.id,
  '{"2":0.78,"3":0.90,"4":0.65}'::jsonb,
  '{"4":0.88,"5":0.55}'::jsonb,
  '{"电气故障":0.92,"绝缘故障":0.80}'::jsonb,
  '{"励磁":0.92,"绕组":0.85,"保护装置":0.75}'::jsonb,
  '["励磁系统","发电机","电气故障","绝缘","南瑞继保"]'::jsonb,
  '[0.78,0.90,0.65,0.88,0.55,0.92,0.80,0.00,0.92,0.85,0.75,0.00]'::jsonb,
  20, 18, 185, NOW() - interval '4 hours'
FROM users u WHERE u.emp_no = 'EMP003';

INSERT INTO user_profiles(user_id, device_interests, mfr_interests, fault_interests,
                          keyword_interests, personal_tags, profile_vector,
                          total_behaviors, active_days_30, avg_stay_sec, last_computed_at)
SELECT u.id,
  '{"1":0.70,"2":0.65,"3":0.60,"4":0.55,"5":0.65}'::jsonb,
  '{"1":0.70,"2":0.65}'::jsonb,
  '{"振动故障":0.75,"电气故障":0.68,"轴承故障":0.72}'::jsonb,
  '{"报警":0.85,"跳机":0.82,"转速":0.65}'::jsonb,
  '["运行监视","紧急事件","报警处理"]'::jsonb,
  '[0.70,0.65,0.60,0.70,0.65,0.75,0.68,0.72,0.85,0.82,0.65,0.00]'::jsonb,
  30, 28, 140, NOW() - interval '1 hour'
FROM users u WHERE u.emp_no = 'EMP004';

INSERT INTO user_profiles(user_id, device_interests, mfr_interests, fault_interests,
                          keyword_interests, personal_tags, profile_vector,
                          total_behaviors, active_days_30, avg_stay_sec, last_computed_at)
SELECT u.id,
  '{"1":0.90,"6":0.55,"5":0.45}'::jsonb,
  '{"2":0.92}'::jsonb,
  '{"振动故障":0.85,"轴承故障":0.88,"裂纹缺陷":0.70}'::jsonb,
  '{"轴承":0.88,"转子":0.82,"振动":0.78}'::jsonb,
  '["哈电汽轮机","振动","轴承","高压缸"]'::jsonb,
  '[0.90,0.55,0.45,0.92,0.00,0.85,0.88,0.70,0.88,0.82,0.78,0.00]'::jsonb,
  25, 22, 380, NOW() - interval '2 hours'
FROM users u WHERE u.emp_no = 'EMP008';

INSERT INTO user_profiles(user_id, device_interests, mfr_interests, fault_interests,
                          keyword_interests, personal_tags, profile_vector,
                          total_behaviors, active_days_30, avg_stay_sec, last_computed_at)
SELECT u.id,
  '{"1":0.92,"5":0.40}'::jsonb,
  '{"2":0.95}'::jsonb,
  '{"裂纹缺陷":0.92,"振动故障":0.78,"轴承故障":0.82}'::jsonb,
  '{"转子":0.90,"探伤":0.88,"裂纹":0.85,"轴承":0.75}'::jsonb,
  '["哈电汽轮机","转子裂纹","探伤","轴承温度"]'::jsonb,
  '[0.92,0.40,0.00,0.95,0.00,0.92,0.78,0.82,0.90,0.88,0.75,0.85]'::jsonb,
  24, 21, 420, NOW() - interval '3 hours'
FROM users u WHERE u.emp_no = 'EMP013';

INSERT INTO user_profiles(user_id, device_interests, mfr_interests, fault_interests,
                          keyword_interests, personal_tags, profile_vector,
                          total_behaviors, active_days_30, avg_stay_sec, last_computed_at)
SELECT u.id,
  '{"1":0.85,"2":0.60,"3":0.50,"4":0.45,"5":0.55,"6":0.65}'::jsonb,
  '{"1":0.80}'::jsonb,
  '{"密封故障":0.82,"振动故障":0.78,"裂纹缺陷":0.88}'::jsonb,
  '{"汽封":0.80,"叶片":0.85,"轴承":0.78,"动平衡":0.75}'::jsonb,
  '["检修工程师","汽封调整","叶片检查","轴承检修"]'::jsonb,
  '[0.85,0.60,0.50,0.80,0.45,0.82,0.78,0.88,0.80,0.85,0.78,0.75]'::jsonb,
  26, 23, 480, NOW() - interval '5 hours'
FROM users u WHERE u.emp_no = 'EMP006';

-- ============================================================
-- 11. 推送配置 push_configs（为每个用户创建配置）
-- ============================================================
INSERT INTO push_configs(user_id, score_threshold, max_push_per_day,
    weight_device_type, weight_behavior, weight_role, weight_manufacturer,
    push_window_start, push_window_end,
    channel_in_app, channel_mobile, channel_email, emergency_realtime)
SELECT id,
  CASE role
    WHEN '运行值长'     THEN 0.55
    WHEN '汽轮机专工'   THEN 0.65
    WHEN '电气专工'     THEN 0.65
    WHEN '锅炉专工'     THEN 0.65
    WHEN '检修工程师'   THEN 0.60
    ELSE 0.60
  END,
  CASE role WHEN '运行值长' THEN 30 ELSE 20 END,
  0.35, 0.30, 0.20, 0.15,
  '07:30', '09:00',
  TRUE, TRUE,
  CASE WHEN role IN ('汽轮机专工','电气专工','检修工程师') THEN TRUE ELSE FALSE END,
  TRUE
FROM users;

-- ============================================================
-- 12. 推送结果 push_results（最近14天）
-- ============================================================
-- 为 EMP001 张建国推送汽轮机相关事件
INSERT INTO push_results(user_id, event_id, push_date, match_score, score_breakdown,
                         push_reasons, push_type, is_read, read_at, is_clicked, feedback)
SELECT
  u.id,
  e.id,
  d.push_date,
  ROUND((0.72 + RANDOM() * 0.25)::numeric, 4),
  ('{"device_type":0.32,"behavior":0.28,"role":0.18,"manufacturer":0.14}'::jsonb),
  ('["设备类型匹配：汽轮机（权重0.35）","行为历史：近30日查询振动相关23次","岗位匹配：汽轮机专工"]'::jsonb),
  CASE (ROW_NUMBER() OVER()) % 3 WHEN 0 THEN 'personal' WHEN 1 THEN 'device_group' ELSE 'personal' END,
  RANDOM() > 0.3,
  CASE WHEN RANDOM() > 0.3 THEN NOW() - (RANDOM() * 12 || ' hours')::interval ELSE NULL END,
  RANDOM() > 0.5,
  CASE WHEN RANDOM() > 0.6 THEN 'like' WHEN RANDOM() > 0.4 THEN NULL ELSE 'dislike' END
FROM users u,
     (SELECT generate_series(0,13) AS n,
             CURRENT_DATE - generate_series(0,13) AS push_date) d,
     events e
WHERE u.emp_no = 'EMP001'
  AND e.event_no IN ('EVT-20260101-001','EVT-20260412-030','EVT-20260305-021',
                     'EVT-20260203-014','EVT-20260112-006','EVT-20260320-024')
ON CONFLICT (user_id, event_id, push_date) DO NOTHING;

-- 为 EMP001 推送紧急事件（最高分）
INSERT INTO push_results(user_id, event_id, push_date, match_score, score_breakdown,
                         push_reasons, push_type, is_read, read_at, is_clicked)
SELECT
  u.id, e.id, CURRENT_DATE,
  0.9800,
  ('{"device_type":0.35,"behavior":0.30,"role":0.20,"manufacturer":0.13}'::jsonb),
  ('["紧急事件实时推送","设备类型匹配：汽轮机","岗位匹配：汽轮机专工","制造商匹配：东方汽轮机"]'::jsonb),
  'emergency',
  TRUE, NOW() - interval '2 hours', TRUE
FROM users u, events e
WHERE u.emp_no = 'EMP001' AND e.event_no = 'EVT-20260412-030'
ON CONFLICT DO NOTHING;

-- 为 EMP008 周海涛推送哈电汽轮机事件
INSERT INTO push_results(user_id, event_id, push_date, match_score, score_breakdown,
                         push_reasons, push_type, is_read, is_clicked)
SELECT
  u.id, e.id,
  CURRENT_DATE - ((ROW_NUMBER() OVER() - 1) % 7)::int,
  ROUND((0.68 + RANDOM() * 0.28)::numeric, 4),
  ('{"device_type":0.33,"behavior":0.28,"role":0.18,"manufacturer":0.13}'::jsonb),
  ('["设备类型匹配：汽轮机","制造商匹配：哈电集团","行为历史：近期多次查询哈电振动事件"]'::jsonb),
  'personal',
  RANDOM() > 0.25,
  RANDOM() > 0.45
FROM users u, events e
WHERE u.emp_no = 'EMP008'
  AND e.event_no IN ('EVT-20260122-010','EVT-20260125-011','EVT-20260120-009',
                     'EVT-20260310-022','EVT-20260215-019','EVT-20260405-027')
ON CONFLICT (user_id, event_id, push_date) DO NOTHING;

-- 为 EMP013 徐明推送裂纹探伤相关事件
INSERT INTO push_results(user_id, event_id, push_date, match_score, score_breakdown,
                         push_reasons, push_type, is_read, is_clicked, feedback)
SELECT
  u.id, e.id,
  CURRENT_DATE - ((ROW_NUMBER() OVER() - 1) % 10)::int,
  ROUND((0.75 + RANDOM() * 0.22)::numeric, 4),
  ('{"device_type":0.34,"behavior":0.29,"role":0.19,"manufacturer":0.15}'::jsonb),
  ('["设备类型匹配：汽轮机","制造商匹配：哈电集团","行为兴趣：转子裂纹/探伤检查","岗位匹配：汽轮机专工"]'::jsonb),
  'personal',
  RANDOM() > 0.2,
  RANDOM() > 0.35,
  CASE WHEN RANDOM() > 0.5 THEN 'like' ELSE NULL END
FROM users u, events e
WHERE u.emp_no = 'EMP013'
  AND e.event_no IN ('EVT-20260125-011','EVT-20260405-027','EVT-20260215-019',
                     'EVT-20260122-010','EVT-20260127-012')
ON CONFLICT (user_id, event_id, push_date) DO NOTHING;

-- 为 EMP003 王志强推送电气事件
INSERT INTO push_results(user_id, event_id, push_date, match_score, score_breakdown,
                         push_reasons, push_type, is_read, is_clicked)
SELECT
  u.id, e.id,
  CURRENT_DATE - ((ROW_NUMBER() OVER() - 1) % 8)::int,
  ROUND((0.70 + RANDOM() * 0.25)::numeric, 4),
  ('{"device_type":0.32,"behavior":0.27,"role":0.19,"manufacturer":0.12}'::jsonb),
  ('["设备类型匹配：励磁系统/发电机","岗位匹配：电气专工","行为历史：多次查询电气故障"]'::jsonb),
  'personal',
  RANDOM() > 0.3,
  RANDOM() > 0.5
FROM users u, events e
WHERE u.emp_no = 'EMP003'
  AND e.event_no IN ('EVT-20260108-004','EVT-20260401-026','EVT-20260127-012',
                     'EVT-20260210-017','EVT-20260118-008')
ON CONFLICT (user_id, event_id, push_date) DO NOTHING;

-- 紧急推送：EVT-20260412-030 (#1机末级叶片裂纹) 推送给华北一厂所有用户
INSERT INTO push_results(user_id, event_id, push_date, match_score, score_breakdown,
                         push_reasons, push_type, is_read, is_clicked)
SELECT
  u.id,
  e.id,
  CURRENT_DATE,
  ROUND((0.85 + RANDOM() * 0.14)::numeric, 4),
  ('{"device_type":0.35,"behavior":0.00,"role":0.20,"manufacturer":0.00,"emergency":0.30}'::jsonb),
  ('["紧急事件实时推送","本厂事件：华北一厂#1机","级别：紧急"]'::jsonb),
  'emergency',
  RANDOM() > 0.2,
  RANDOM() > 0.4
FROM users u, events e
WHERE u.plant_id = 1 AND e.event_no = 'EVT-20260412-030'
ON CONFLICT (user_id, event_id, push_date) DO NOTHING;

-- ============================================================
-- 13. 补充标签（新增故障/关键词类型）
-- ============================================================
INSERT INTO tags(code, name, category, weight) VALUES
  ('tag_mfr_tbea',    '特变电工',     'manufacturer', 1.0),
  ('tag_fault_eff',   '效率下降',     'fault_type',   0.9),
  ('tag_fault_press', '压力异常',     'fault_type',   0.9),
  ('tag_fault_gas',   '气体纯度异常', 'fault_type',   0.9),
  ('tag_fault_water', '水质异常',     'fault_type',   0.8),
  ('tag_fault_inner', '内漏故障',     'fault_type',   0.9),
  ('tag_kw_exp',      '胀差',         'keyword',      0.9),
  ('tag_kw_hydrogen', '氢气',         'keyword',      0.8),
  ('tag_kw_dcs',      'DCS系统',      'keyword',      0.8),
  ('tag_kw_chrome',   '色谱',         'keyword',      0.8),
  ('tag_kw_safv',     '安全门',       'keyword',      0.8),
  ('tag_kw_oilfilm',  '油膜',         'keyword',      0.9)
ON CONFLICT (code) DO NOTHING;

-- ============================================================
-- 14. 新增工单（20条，2026年4月中旬—5月7日）
-- ============================================================
INSERT INTO events(event_no, plant_id, unit_id, device_type_id, manufacturer_id, model_id,
                   kks_code, title, content, level, event_type, status, occurred_at) VALUES

-- ── 今日事件（2026-05-07，供推送引擎直接命中）──────────────
('EVT-20260507-033', 1, 2, 1, 1, 1,
 '10MAA20AA004',
 '#2机中压缸胀差超限紧急停机',
 '#2机中压缸胀差持续增大，胀差值于2026-05-07 07:45达到+15.8mm，超过联锁停机保护定值（+15.0mm），机组自动停机。停机过程中各轴承振动正常，无异常声响。胀差超限原因初步分析为中压缸进汽温度突升（+12°C/5min），导致转子与汽缸热膨胀差异过大。目前机组盘车中，等待胀差恢复正常值后升速检查。已联系东方汽轮机厂技术人员远程支持。',
 '紧急', '热力异常', 'processing', '2026-05-07 07:45:00+08'),

('EVT-20260507-034', 1, 1, 1, 1, 1,
 '10MAA10AA006',
 '#1机润滑油系统压力低联锁报警',
 '#1机润滑油系统主油泵出口压力于今日10:22出现低压报警，主油泵出口压力从正常值0.35MPa降至0.28MPa，启动辅助油泵后压力恢复正常。排查原因为主油泵进口过滤器差压升高（差压0.12MPa，报警值0.08MPa），进行了在线反冲洗，过滤器差压恢复正常。计划本周末更换过滤器滤芯，目前辅助油泵热备用，主油泵继续运行，加强监视。',
 '重要', '压力异常', 'processing', '2026-05-07 10:22:00+08'),

('EVT-20260507-035', 2, 5, 8, 1, NULL,
 '20MAB10AA001',
 '#1机凝汽器铜管泄漏加剧真空下降',
 '华北二厂#1机凝汽器真空严密性检查发现，B侧水室进口端有3根铜管存在泄漏（2处微漏、1处明漏），总泄漏量估算约3.8L/min，影响真空度（当前-93.8kPa，正常-96.0kPa），机组热耗上升约0.8%。已申请停机消缺，计划本周四（5月9日）利用负荷低谷时段停机堵管，按1.1倍泄漏速率估算需堵管5-8根。',
 '重要', '泄漏故障', 'processing', '2026-05-07 08:30:00+08'),

('EVT-20260507-036', 3, 9, 6, 1, NULL,
 '30LAB10AP002',
 '#1机A给水泵汽轮机超速保护动作跳闸',
 '莱芜电厂#1机A侧汽动给水泵驱动小汽轮机于今日06:18突然跳闸，首出信号为"小汽轮机超速保护动作"，转速瞬时超过4200rpm（额定3000rpm），超速保护定值4050rpm。已切换至B侧给水泵，主给水流量快速恢复正常。初步分析为DEH调速系统调节阀油动机信号波动，导致调节阀误动全开引起超速。已对小汽轮机进行盘车检查，暂未发现机械损伤，等待进一步排查DEH信号回路。',
 '紧急', '超速跳机', 'processing', '2026-05-07 06:18:00+08'),

-- ── 5月5-6日 ──────────────────────────────────────────────
('EVT-20260506-037', 1, 4, 4, 5, 8,
 '10BBA40AA001',
 '#4机主变压器油中溶解气体分析异常',
 '#4机主变压器例行油色谱分析结果显示，乙炔（C₂H₂）含量从上次检测0.2μL/L升至3.8μL/L，总烃含量升至46μL/L，超过注意值预警阈值。乙炔升高通常表明变压器内部存在高能量放电（如电弧放电）。已申请缩短监测周期至每周一次，同时增加在线监测频次，联系特变电工厂家技术人员进行远程诊断，准备应急预案。若乙炔持续升高，将申请停电检查。',
 '紧急', '电气故障', 'processing', '2026-05-06 14:00:00+08'),

('EVT-20260506-038', 2, 7, 3, 4, 7,
 '20EXC30AA002',
 '#3机励磁调节器PSS参数优化建议',
 '华北二厂#3机电网振荡阻尼检测发现，当电网出现0.4-0.8Hz低频振荡时，#3机励磁系统电力系统稳定器（PSS）阻尼效果偏弱，与相邻机组相比模态阻尼比低约0.05。建议对PSS超前滞后环节时间常数重新整定，优化PSS参数以增强系统阻尼。建议在下次计划停机时组织励磁系统联调试验，重新整定PSS参数，提高电网稳定性。',
 '建议', '控制优化', 'open', '2026-05-06 09:30:00+08'),

('EVT-20260505-039', 1, 3, 5, 1, 10,
 '10HAB30AA002',
 '#3机锅炉过热器C侧安全门误动作',
 '#3机锅炉过热器C侧安全门于5月5日11:28误动作（当时主蒸汽压力24.1MPa，整定值24.5MPa），安全门持续动作约18秒后回座，期间主蒸汽压力降至22.8MPa，机组出力短暂下降至540MW。经检查确认为安全门弹簧预紧力因长期运行发生松弛，整定压力偏低导致误动。已申请在本月检修中对该安全门重新整定，同时对其余安全门进行全面检查校验。',
 '重要', '安全门故障', 'processing', '2026-05-05 11:28:00+08'),

('EVT-20260505-040', 1, 2, 1, 1, 1,
 '10MAA20AA005',
 '#2机DCS控制器与上位机通讯中断',
 '#2机DCS系统上位机工程师站与#2控制器通讯中断约3分钟（11:05-11:08），期间操作员无法从工程师站读取实时数据，但DCS控制功能正常，机组运行未受影响。通讯中断原因为DCS网络交换机端口发生短暂故障，自愈后通讯恢复。已对网络设备进行检查，更换了疑似老化的网络交换机端口模块，建议在年度大修中对DCS网络设备进行全面检测更换。',
 '重要', '控制系统故障', 'closed', '2026-05-05 11:05:00+08'),

-- ── 5月3-4日 ──────────────────────────────────────────────
('EVT-20260504-041', 3, 10, 2, 2, 6,
 '30MKA20AA003',
 '#2机发电机氢气纯度持续下降',
 '莱芜电厂#2机发电机氢气纯度监测值持续缓慢下降，当前纯度96.8%（正常值>98%），氢气消耗量较正常增加约15%。初步分析为发电机氢气密封系统密封瓦间隙增大，氢气从密封侧向外泄漏。已增加补氢频次，并对密封油系统进行检查，密封油压差正常。建议在本次小修中对密封瓦进行检查测量，确认磨损程度，必要时更换密封瓦。',
 '重要', '气体纯度异常', 'processing', '2026-05-04 15:40:00+08'),

('EVT-20260503-042', 2, 6, 7, 1, NULL,
 '20MAF20AA001',
 '#2机循环水A泵叶轮汽蚀磨损检查',
 '华北二厂#2机循环水A泵年度检修揭泵后检查，发现叶轮流道存在明显汽蚀磨损痕迹，最大蚀坑深度约8mm，叶轮进口边磨损量约3-5mm，影响泵效率（估算效率下降约4%）。鉴于磨损程度建议更换叶轮，原叶轮可送厂修复备用。已联系厂家采购备品叶轮，预计2周内到货，安排叶轮到货后完成换装。',
 '一般', '磨损故障', 'processing', '2026-05-03 09:00:00+08'),

-- ── 4月下旬 ──────────────────────────────────────────────
('EVT-20260430-043', 1, 1, 1, 1, 1,
 '10MAA10AA007',
 '#1机中压缸前汽封磨损量超设计上限',
 '#1机大修揭缸检查，中压缸前汽封（共6道）磨损量测量结果：平均径向间隙3.68mm，超过设计最大值3.20mm，部分汽封片已磨平。预计泄汽量因此增加约0.8t/h，影响热耗约0.6%。已向东方汽轮机采购汽封片备件（型号：ZFY-48-3.0），计划在本次大修中更换全部汽封片，恢复设计间隙值（2.80-3.00mm）。',
 '一般', '磨损故障', 'processing', '2026-04-30 10:00:00+08'),

('EVT-20260428-044', 2, 8, 1, 2, 3,
 '20MAA40AA003',
 '#4机（1000MW）高中压联合汽阀内漏量超标',
 '华北二厂#4机1000MW汽轮机高中压联合汽阀（HPCV）活动试验中发现阀门关闭后有明显内漏，内漏量估算约35t/h（正常值<5t/h），阀杆密封磨损严重。内漏量偏大影响机组停机后的汽缸散热，增加再启动时的热损耗。计划在5月份计划检修中对阀杆密封进行更换，同时检查阀碟与阀座密封面配合状态，必要时进行研磨修复。',
 '重要', '内漏故障', 'processing', '2026-04-28 13:00:00+08'),

('EVT-20260425-045', 1, 4, 6, 1, NULL,
 '10LAB40AP001',
 '#4机A给水泵汽轮机低负荷油膜振荡',
 '#4机A侧汽动给水泵于2026-04-25 03:40在低负荷工况（功率约15%额定）下发生油膜振荡，轴承振动从正常5mm/s突升至38mm/s，振荡频率28.5Hz（低于转频的一半，为典型油膜振荡特征）。运行人员立即提升给泵转速，油膜振荡自行消失。分析认为油温偏低（38°C，设计范围45-55°C）是诱发油膜振荡的主要原因。已调整油冷却器旁路阀开度，确保低负荷时油温维持在设计范围内。',
 '紧急', '油膜振荡', 'processing', '2026-04-25 03:40:00+08'),

-- ── 4月中旬 ──────────────────────────────────────────────
('EVT-20260422-046', 2, 6, 1, 1, 2,
 '20MAA20AA001',
 '#2机高压缸热效率持续下降趋势分析',
 '华北二厂#2机热力性能在线监测系统显示，近3个月内高压缸效率持续缓慢下降，月均下降约0.4%，累计下降1.2%（当前83.1%），同比往年同期偏低约1.8%。初步判断为高压缸通流部分结垢或轻微汽蚀导致流道截面积变化。建议在年度大修中对高压缸进行全面检查，包括隔板、叶栅、轴封状态等，明确效率下降原因并针对性处理。',
 '建议', '性能劣化', 'open', '2026-04-22 09:00:00+08'),

('EVT-20260420-047', 3, 9, 1, 2, 3,
 '30MAA10AA003',
 '#1机中压调速阀液压执行机构LVDT传感器故障',
 '莱芜电厂#1机中压调速阀（ICV）液压执行机构位移传感器（LVDT）发出"信号超量程"故障报警，DEH系统自动切换至备用传感器。主传感器检查发现内部线圈局部短路，信号输出异常（满量程输出）。已更换主传感器并完成标定，DEH系统切回主传感器正常运行。备用传感器已取下送厂检修，计划更换新品备用。',
 '一般', '传感器故障', 'closed', '2026-04-20 14:30:00+08'),

('EVT-20260418-048', 1, 3, 5, 1, 10,
 '10HAC30AA001',
 '#3机锅炉A侧引风机电机绕组温度超限',
 '#3机锅炉A侧引风机驱动电机定子绕组温度（三相平均值）持续偏高，当前138°C（设计额定值130°C），已超过报警值（135°C）。排查原因：冷却风道积灰严重，导致电机散热效果下降。已对冷却风道进行清灰处理，电机绕组温度下降至128°C，恢复正常。建议适当缩短冷却风道清灰周期（从每季度一次改为每月一次），并检查冷却风机运行状况。',
 '一般', '超温故障', 'closed', '2026-04-18 16:20:00+08'),

('EVT-20260416-049', 2, 6, 2, 1, 5,
 '20MKA20AA002',
 '#2机发电机定子冷却水导电率超标',
 '华北二厂#2机发电机定子冷却水在线监测显示水质导电率超标，当前值2.8μS/cm，超过设计允许值2.0μS/cm，可能影响定子绕组绝缘。检查发现混床离子交换树脂已饱和失效，导致水质净化能力下降。已更换混床树脂，处理后导电率降至0.8μS/cm，恢复正常。建议根据实际运行监测数据适当缩短树脂更换周期。',
 '重要', '水质异常', 'closed', '2026-04-16 10:45:00+08'),

('EVT-20260415-050', 1, 2, 1, 1, 1,
 '10MAA20AA006',
 '#2机高压主汽阀阀杆卡涩活动试验不合格',
 '#2机高压主汽阀（MSV）按规程进行每月一次活动试验，阀杆在60%开度位置卡涩，活动试验不合格。检查发现阀杆密封填料压盖过紧，导致阀杆运动阻力增大。现场对填料压盖紧力进行调整，复测活动试验合格，阀门动作灵活。已记录此次卡涩情况，建议在下次大修中对阀杆密封系统进行全面检查，评估填料磨损状况。',
 '重要', '控制系统故障', 'closed', '2026-04-15 08:30:00+08'),

-- ── 4月13-14日（紧接原有数据）────────────────────────────
('EVT-20260414-051', 1, 4, 9, 1, NULL,
 '10MAF40AA002',
 '#4机空冷A列清洗完成效果验证',
 '根据EVT-20260408-028，#4机空冷系统A列散热翅片高压水冲洗作业已完成，历时约10小时。清洗后翅片积灰基本清除，目测堵塞率由30%降至5%以下。机组背压由冲洗前9.2kPa降至7.6kPa，恢复至设计范围（<8kPa），热耗下降约0.3%。清洗过程中同步检查了自动清洗系统，发现2个喷嘴堵塞已更换，自动清洗功能恢复正常。工单闭合。',
 '一般', '积灰堵塞', 'closed', '2026-04-14 18:00:00+08'),

('EVT-20260413-052', 2, 7, 1, 1, 2,
 '20MAA30AA003',
 '#3机高压缸3号轴承振动趋势跟踪报告',
 '华北二厂#3机高压缸3号轴承（高压转子前轴承）振动持续跟踪监视报告：该轴承X向振动近30日均值68μm，Y向72μm，均在报警值（100μm）以下，但较3个月前（X:52μm，Y:55μm）有明显上升趋势，月均增加约5μm。分析认为与轴承乌金面轻微磨损有关。建议继续加密监视（每班记录一次），并在下次停机机会安排轴承检查，重点测量轴承间隙和乌金面状态。',
 '一般', '振动异常', 'open', '2026-04-13 16:00:00+08');

-- ============================================================
-- 15. 新增工单 NLP 标签
-- ============================================================
-- 今日事件
INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.97, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260507-033'
  AND t.code IN ('tag_turbine','tag_fault_over','tag_kw_exp','tag_mfr_dfst','tag_sym_alarm');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.93, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260507-034'
  AND t.code IN ('tag_turbine','tag_fault_press','tag_kw_lube','tag_mfr_dfst','tag_sym_alarm');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.92, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260507-035'
  AND t.code IN ('tag_condenser','tag_fault_leak','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.96, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260507-036'
  AND t.code IN ('tag_fwp','tag_turbine','tag_sym_trip','tag_fault_ctrl','tag_mfr_dfst');

-- 5月5-6日
INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.98, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260506-037'
  AND t.code IN ('tag_transformer','tag_fault_elec','tag_kw_chrome','tag_mfr_tbea','tag_sym_alarm');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.88, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260506-038'
  AND t.code IN ('tag_exciter','tag_mfr_nari');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.94, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260505-039'
  AND t.code IN ('tag_boiler','tag_fault_press','tag_kw_safv','tag_mfr_dfst','tag_sym_alarm');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.91, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260505-040'
  AND t.code IN ('tag_turbine','tag_fault_ctrl','tag_kw_dcs','tag_mfr_dfst');

-- 5月3-4日
INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.93, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260504-041'
  AND t.code IN ('tag_generator','tag_fault_gas','tag_kw_hydrogen','tag_fault_seal','tag_mfr_harbin');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.89, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260503-042'
  AND t.code IN ('tag_cwp','tag_fault_eff','tag_mfr_dfst');

-- 4月下旬
INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.92, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260430-043'
  AND t.code IN ('tag_turbine','tag_fault_seal','tag_kw_seal','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.95, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260428-044'
  AND t.code IN ('tag_turbine','tag_fault_inner','tag_fault_seal','tag_mfr_harbin');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.97, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260425-045'
  AND t.code IN ('tag_fwp','tag_turbine','tag_fault_vib','tag_kw_oilfilm','tag_kw_bearing','tag_mfr_dfst');

-- 4月中旬
INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.87, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260422-046'
  AND t.code IN ('tag_turbine','tag_fault_eff','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.90, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260420-047'
  AND t.code IN ('tag_turbine','tag_fault_ctrl','tag_mfr_harbin');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.90, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260418-048'
  AND t.code IN ('tag_boiler','tag_fault_over','tag_sym_heat','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.91, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260416-049'
  AND t.code IN ('tag_generator','tag_fault_water','tag_fault_cool','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.93, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260415-050'
  AND t.code IN ('tag_turbine','tag_fault_ctrl','tag_fault_seal','tag_mfr_dfst');

-- 4月13-14日
INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.85, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260414-051'
  AND t.code IN ('tag_acc','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method) SELECT e.id, t.id, 0.89, 'nlp'
FROM events e, tags t WHERE e.event_no = 'EVT-20260413-052'
  AND t.code IN ('tag_turbine','tag_fault_vib','tag_kw_bearing','tag_mfr_dfst');

-- ============================================================
-- 16. 事件附件（8条事件，共12个附件）
-- ============================================================
INSERT INTO event_attachments(event_id, file_name, file_type, file_size, storage_url)
SELECT e.id, '叶片损伤检查报告.pdf', 'pdf', 2458624,
  '/attachments/EVT-20260101-001_blade_inspection.pdf'
FROM events e WHERE e.event_no = 'EVT-20260101-001';

INSERT INTO event_attachments(event_id, file_name, file_type, file_size, storage_url)
SELECT e.id, '振动超标分析报告.pdf', 'pdf', 1843200,
  '/attachments/EVT-20260101-001_vibration_analysis.pdf'
FROM events e WHERE e.event_no = 'EVT-20260101-001';

INSERT INTO event_attachments(event_id, file_name, file_type, file_size, storage_url)
SELECT e.id, '超声波探伤检查报告.pdf', 'pdf', 3276800,
  '/attachments/EVT-20260122-010_ut_report.pdf'
FROM events e WHERE e.event_no = 'EVT-20260122-010';

INSERT INTO event_attachments(event_id, file_name, file_type, file_size, storage_url)
SELECT e.id, '焊口修复技术方案.pdf', 'pdf', 1536000,
  '/attachments/EVT-20260122-010_repair_plan.pdf'
FROM events e WHERE e.event_no = 'EVT-20260122-010';

INSERT INTO event_attachments(event_id, file_name, file_type, file_size, storage_url)
SELECT e.id, '轴承温度跟踪记录.xlsx', 'xlsx', 524288,
  '/attachments/EVT-20260125-011_bearing_temp_log.xlsx'
FROM events e WHERE e.event_no = 'EVT-20260125-011';

INSERT INTO event_attachments(event_id, file_name, file_type, file_size, storage_url)
SELECT e.id, 'PT探伤原始记录.pdf', 'pdf', 4194304,
  '/attachments/EVT-20260412-030_pt_record.pdf'
FROM events e WHERE e.event_no = 'EVT-20260412-030';

INSERT INTO event_attachments(event_id, file_name, file_type, file_size, storage_url)
SELECT e.id, '末级叶片裂纹处理方案.pdf', 'pdf', 2097152,
  '/attachments/EVT-20260412-030_repair_scheme.pdf'
FROM events e WHERE e.event_no = 'EVT-20260412-030';

INSERT INTO event_attachments(event_id, file_name, file_type, file_size, storage_url)
SELECT e.id, '汽封片检查记录表.xlsx', 'xlsx', 307200,
  '/attachments/EVT-20260413-031_seal_inspection.xlsx'
FROM events e WHERE e.event_no = 'EVT-20260413-031';

INSERT INTO event_attachments(event_id, file_name, file_type, file_size, storage_url)
SELECT e.id, '胀差监测数据记录.xlsx', 'xlsx', 409600,
  '/attachments/EVT-20260507-033_exp_data.xlsx'
FROM events e WHERE e.event_no = 'EVT-20260507-033';

INSERT INTO event_attachments(event_id, file_name, file_type, file_size, storage_url)
SELECT e.id, '主变色谱分析报告.pdf', 'pdf', 1720320,
  '/attachments/EVT-20260506-037_chromatography.pdf'
FROM events e WHERE e.event_no = 'EVT-20260506-037';

INSERT INTO event_attachments(event_id, file_name, file_type, file_size, storage_url)
SELECT e.id, '油膜振荡频谱分析报告.pdf', 'pdf', 2621440,
  '/attachments/EVT-20260425-045_oil_film_analysis.pdf'
FROM events e WHERE e.event_no = 'EVT-20260425-045';

INSERT INTO event_attachments(event_id, file_name, file_type, file_size, storage_url)
SELECT e.id, '转子中心孔探伤报告.pdf', 'pdf', 3932160,
  '/attachments/EVT-20260405-027_inspection_report.pdf'
FROM events e WHERE e.event_no = 'EVT-20260405-027';

-- ============================================================
-- 验证查询
-- ============================================================
-- SELECT 'plants' AS tbl, COUNT(*) FROM plants
-- UNION ALL SELECT 'units', COUNT(*) FROM units
-- UNION ALL SELECT 'users', COUNT(*) FROM users
-- UNION ALL SELECT 'events', COUNT(*) FROM events
-- UNION ALL SELECT 'tags', COUNT(*) FROM tags
-- UNION ALL SELECT 'event_tags', COUNT(*) FROM event_tags
-- UNION ALL SELECT 'user_behaviors', COUNT(*) FROM user_behaviors
-- UNION ALL SELECT 'user_profiles', COUNT(*) FROM user_profiles
-- UNION ALL SELECT 'push_results', COUNT(*) FROM push_results
-- UNION ALL SELECT 'push_configs', COUNT(*) FROM push_configs;
