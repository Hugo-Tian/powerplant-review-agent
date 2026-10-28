-- ============================================================
-- 演示数据：专为答辩展示设计
-- 核心目的：用同一批工单，直观展示"个性化推送"效果
-- 演示用户：张建国（汽轮机专工）— 汽轮机类工单高分，其他设备低分
-- ============================================================

-- 清空所有业务数据（保留 device_types / manufacturers，它们在 schema.sql 里）
TRUNCATE TABLE
  push_results, push_configs, user_profiles, user_behaviors,
  nlp_extract_jobs, event_tags, event_attachments, events,
  tags, users, departments, units, plants, device_models
CASCADE;

ALTER SEQUENCE device_models_id_seq RESTART WITH 1;
ALTER SEQUENCE departments_id_seq   RESTART WITH 1;
ALTER SEQUENCE plants_id_seq        RESTART WITH 1;
ALTER SEQUENCE units_id_seq         RESTART WITH 1;
ALTER SEQUENCE tags_id_seq          RESTART WITH 1;
ALTER SEQUENCE push_configs_id_seq  RESTART WITH 1;

-- ============================================================
-- 1. 电厂 & 机组
-- ============================================================
INSERT INTO plants(code, name, location, capacity_mw, status) VALUES
  ('PLANT_HB01', '华北能源第一发电厂', '河北省保定市', 1320, 'operating');

INSERT INTO units(plant_id, unit_no, capacity_mw, status) VALUES
  (1, '#1', 660, 'operating'),
  (1, '#2', 660, 'operating');

INSERT INTO departments(name, plant_id) VALUES
  ('汽轮机部', 1),
  ('电气部',   1),
  ('锅炉部',   1),
  ('运行部',   1);

-- ============================================================
-- 2. 演示用户（UUID 与前端 CURRENT_USER_ID 保持一致）
-- ============================================================
INSERT INTO users(id, emp_no, name, department_id, plant_id, role,
                  responsible_units, push_enabled) VALUES
  ('00000000-0000-0000-0000-000000000001',
   'EMP001', '张建国', 1, 1, '汽轮机专工', '["#1","#2"]', TRUE);

-- ============================================================
-- 3. NLP 标签库
-- ============================================================
INSERT INTO tags(code, name, category, weight) VALUES
  ('tag_turbine',     '汽轮机',       'device_type',  1.0),
  ('tag_generator',   '发电机',       'device_type',  1.0),
  ('tag_exciter',     '励磁系统',     'device_type',  1.0),
  ('tag_transformer', '变压器',       'device_type',  1.0),
  ('tag_boiler',      '锅炉',         'device_type',  1.0),
  ('tag_fwp',         '给水泵',       'device_type',  0.9),
  ('tag_cwp',         '循环水泵',     'device_type',  0.9),
  ('tag_mfr_dfst',    '东方汽轮机',   'manufacturer', 1.0),
  ('tag_mfr_harbin',  '哈电集团',     'manufacturer', 1.0),
  ('tag_mfr_sec',     '上海电气',     'manufacturer', 1.0),
  ('tag_mfr_nari',    '南瑞继保',     'manufacturer', 1.0),
  ('tag_fault_vib',   '振动超标',     'fault_type',   1.0),
  ('tag_fault_leak',  '泄漏',         'fault_type',   1.0),
  ('tag_fault_over',  '超温',         'fault_type',   1.0),
  ('tag_fault_bear',  '轴承故障',     'fault_type',   1.0),
  ('tag_fault_seal',  '密封失效',     'fault_type',   0.9),
  ('tag_fault_elec',  '电气故障',     'fault_type',   1.0),
  ('tag_fault_ctrl',  '控制系统故障', 'fault_type',   0.9),
  ('tag_kw_rotor',    '转子',         'keyword',      0.9),
  ('tag_kw_blade',    '叶片',         'keyword',      0.9),
  ('tag_kw_bearing',  '轴承',         'keyword',      0.9),
  ('tag_kw_seal',     '汽封',         'keyword',      0.8),
  ('tag_kw_governor', '调速器',       'keyword',      0.8),
  ('tag_kw_lube',     '润滑油',       'keyword',      0.8),
  ('tag_kw_winding',  '绕组',         'keyword',      0.8),
  ('tag_sym_trip',    '跳机',         'symptom',      1.0),
  ('tag_sym_alarm',   '报警',         'symptom',      0.8),
  ('tag_sym_heat',    '过热',         'symptom',      0.9);

-- ============================================================
-- 4. 设备型号
-- ============================================================
INSERT INTO device_models(manufacturer_id, device_type_id, model_code, model_name, spec_json)
VALUES (1, 1, 'N660-25/600/600', '660MW超超临界汽轮机',
        '{"power_mw":660,"steam_pressure":"25MPa","steam_temp":"600C"}');

-- ============================================================
-- 5. 工单事件（10条，覆盖不同设备类型和等级）
--    前5条：汽轮机相关 → 对张建国高分推送
--    后5条：发电机/励磁/锅炉/变压器/循环水泵 → 低分推送
--    这种对比是演示系统"个性化"能力的核心证据
-- ============================================================
INSERT INTO events(event_no, plant_id, unit_id, device_type_id, manufacturer_id,
                   model_id, title, content, level, event_type, status, occurred_at)
VALUES

-- ★ 汽轮机类（高分）----------------------------------------------

('EVT-2026-001', 1, 1, 1, 1, 1,
 '#1机汽轮机高压转子振动超标紧急跳机',
 '#1机汽轮机高压缸A侧轴承振动于今日09:14突然升高，轴振峰值达272μm，超过跳机保护'
 '定值250μm，机组自动跳闸。现场检查高压缸第3级动叶片碎裂，碎片引发动静碰磨，'
 '转子表面可见划痕。已通知东方汽轮机厂家技术支持紧急到场，正在进行揭缸准备。'
 '预计处理工期10-15天。',
 '紧急', '振动故障', 'processing', NOW() - interval '3 hours'),

('EVT-2026-002', 1, 2, 1, 1, 1,
 '#2机高压调节汽门卡涩导致出力受限至520MW',
 '#2机高压调节汽门4号阀卡涩，无法全开，机组最大出力受限至520MW（额定660MW）。'
 '检查发现油动机内部密封圈老化、伺服油泄漏，阀门动作迟缓。已降负荷监视运行，'
 '建议利用近期计划停机机会更换密封组件。东方汽轮机N660型DEH调节系统。',
 '重要', '调节系统故障', 'processing', NOW() - interval '1 day'),

('EVT-2026-003', 1, 1, 1, 1, 1,
 '#1机高压缸汽封间隙偏大漏汽量增加约18%',
 '#1机大修揭缸检查：高压缸前汽封径向间隙普遍超标，部分测量值超设计上限0.2mm，'
 '估算漏汽量增加约18%，影响机组热耗上升约0.3%。已向东方汽轮机请购汽封片备件，'
 '本次大修统一更换第1-5级汽封片，预计恢复设计间隙后效率提升明显。',
 '重要', '密封故障', 'processing', NOW() - interval '3 days'),

('EVT-2026-004', 1, 1, 1, 1, 1,
 '#1机汽轮机润滑油颗粒度超标（NAS 10级）',
 '#1机汽轮机润滑油年度化验报告：颗粒度NAS 10级，超过允许值8级，油品清洁度不达标。'
 '分析原因为过滤器滤芯更换周期偏长。已更换全部油过滤器滤芯，增加在线精滤装置，'
 '对系统进行循环过滤。计划两周后复验，合格后解除监视。',
 '一般', '油品异常', 'processing', NOW() - interval '5 days'),

('EVT-2026-005', 1, 2, 1, 1, 1,
 '#2机低压转子末级叶片建议安排PT探伤检查',
 '根据检修计划，建议对#2机低压转子末级（L-0级）叶片进行PT探伤。上次检查于2024年'
 '大修完成，目前已运行约18000小时，接近东方汽轮机建议检查周期（20000小时）。'
 '重点检查叶根应力腐蚀裂纹，近年同类型机组存在叶根疲劳裂纹典型案例。',
 '建议', '预防性检查', 'open', NOW() - interval '7 days'),

-- ★ 其他设备类（低分）—— 体现系统"不相关不推"的精准性 ----------

('EVT-2026-006', 1, 1, 2, 3, NULL,
 '#1机发电机定子绕组绝缘电阻下降报警',
 '#1机发电机在线绝缘监测系统报警：A相定子绕组对地绝缘电阻降至190MΩ，低于正常值'
 '（>500MΩ），局放量有所增大。可能原因：端部绑扎松动或冷却水微量渗漏进入绝缘层。'
 '建议尽快安排停机进行定子绝缘全面检查。上海电气QFSN-660-2型发电机。',
 '重要', '电气故障', 'processing', NOW() - interval '4 days'),

('EVT-2026-007', 1, 2, 3, 4, NULL,
 '#2机励磁系统AVR主通道切换异常机端电压波动',
 '#2机励磁系统AVR主通道故障，切换至备用通道时励磁电流波动，机端电压短暂跌落至'
 '24.6kV（额定27kV），AGC自动减少无功输出。已切换至备用AVR运行，电压恢复正常。'
 '需对主AVR控制板进行检修，排查PWM驱动芯片故障。南瑞继保NEC-660型励磁系统。',
 '重要', '电气故障', 'processing', NOW() - interval '6 days'),

('EVT-2026-008', 1, 1, 5, 1, NULL,
 '#1机锅炉A侧水冷壁管壁温超标（481°C）',
 '#1机锅炉燃烧器A侧水冷壁管壁温超限，最高点481°C（设计限值450°C）。调整燃烧器'
 '配风，降低该区域热负荷。初步分析为A侧磨煤机出口煤粉量偏多、燃烧偏斜。'
 '调整磨煤机运行参数后管壁温度有所下降，继续监视中。',
 '重要', '超温故障', 'processing', NOW() - interval '2 days'),

('EVT-2026-009', 1, 2, 4, 5, NULL,
 '#2机主变压器冷却器控制回路故障需手动投切',
 '#2机主变压器冷却器自动投切控制回路故障，冷却风扇无法按温度自动启停，须人工手动'
 '控制，增加运行人员操作负担。检查发现控制板继电器触点接触不良、氧化严重。'
 '已联系特变电工厂家发送备件，预计3日内到货更换。',
 '一般', '电气故障', 'processing', NOW() - interval '8 days'),

('EVT-2026-010', 1, 1, 7, 1, NULL,
 '#1机循环水泵A泵振动超报警值（7.1mm/s）',
 '#1机循环水A泵（立式斜流泵）振动监测值持续偏高，泵体垂直方向振动7.1mm/s'
 '（报警值5.0mm/s）。已复查地脚螺栓和联轴器对中，偏差在允许范围内。'
 '怀疑叶轮流道内有异物导致水力不平衡，计划本周末停泵检查清理。',
 '一般', '振动故障', 'processing', NOW() - interval '9 days');

-- ============================================================
-- 6. NLP 标签关联（模拟系统自动提取的结果）
-- ============================================================
INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.98, 'nlp' FROM events e, tags t
WHERE e.event_no = 'EVT-2026-001'
  AND t.code IN ('tag_turbine','tag_fault_vib','tag_sym_trip','tag_kw_rotor','tag_kw_blade','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.95, 'nlp' FROM events e, tags t
WHERE e.event_no = 'EVT-2026-002'
  AND t.code IN ('tag_turbine','tag_fault_ctrl','tag_kw_governor','tag_fault_seal','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.93, 'nlp' FROM events e, tags t
WHERE e.event_no = 'EVT-2026-003'
  AND t.code IN ('tag_turbine','tag_fault_seal','tag_kw_seal','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.90, 'nlp' FROM events e, tags t
WHERE e.event_no = 'EVT-2026-004'
  AND t.code IN ('tag_turbine','tag_kw_lube','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.88, 'nlp' FROM events e, tags t
WHERE e.event_no = 'EVT-2026-005'
  AND t.code IN ('tag_turbine','tag_kw_blade','tag_kw_rotor','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.95, 'nlp' FROM events e, tags t
WHERE e.event_no = 'EVT-2026-006'
  AND t.code IN ('tag_generator','tag_fault_elec','tag_kw_winding','tag_mfr_sec');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.97, 'nlp' FROM events e, tags t
WHERE e.event_no = 'EVT-2026-007'
  AND t.code IN ('tag_exciter','tag_fault_elec','tag_sym_alarm','tag_mfr_nari');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.94, 'nlp' FROM events e, tags t
WHERE e.event_no = 'EVT-2026-008'
  AND t.code IN ('tag_boiler','tag_fault_over','tag_sym_heat','tag_mfr_dfst');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.91, 'nlp' FROM events e, tags t
WHERE e.event_no = 'EVT-2026-009'
  AND t.code IN ('tag_transformer','tag_fault_elec','tag_fault_ctrl');

INSERT INTO event_tags(event_id, tag_id, confidence, extract_method)
SELECT e.id, t.id, 0.89, 'nlp' FROM events e, tags t
WHERE e.event_no = 'EVT-2026-010'
  AND t.code IN ('tag_cwp','tag_fault_vib','tag_sym_alarm');

-- ============================================================
-- 7. 用户行为记录（张建国近30天查询历史，偏向汽轮机/振动/叶片）
--    这些记录是"行为维度（30%权重）"打分的依据
-- ============================================================
INSERT INTO user_behaviors(user_id, session_id, page_url, module, action_type,
    query_content, query_fields, selected_event_id,
    data_type_tags, result_count, enter_time, leave_time,
    mouse_max_stay_sec, scroll_depth_pct)
SELECT
  u.id,
  'sess-demo-' || gs::text,
  '/events',
  CASE (gs % 3) WHEN 0 THEN '事件信息库' WHEN 1 THEN '状态报告' ELSE '工单管理' END,
  CASE (gs % 3) WHEN 0 THEN 'query' WHEN 1 THEN 'detail' ELSE 'export' END,
  CASE (gs % 5)
    WHEN 0 THEN '汽轮机振动'
    WHEN 1 THEN '叶片裂纹'
    WHEN 2 THEN '高压缸故障'
    WHEN 3 THEN '东方汽轮机调速'
    ELSE     '轴承温度润滑'
  END,
  '{"device_type":"汽轮机","plant":"华北一厂"}'::jsonb,
  (SELECT id FROM events
   WHERE event_no IN ('EVT-2026-001','EVT-2026-003','EVT-2026-005')
   ORDER BY RANDOM() LIMIT 1),
  '["tag_turbine","tag_fault_vib","tag_kw_blade"]'::jsonb,
  (5 + gs % 20),
  NOW() - ((30 - gs % 28) || ' days')::interval + (gs % 10 || ' hours')::interval,
  NOW() - ((30 - gs % 28) || ' days')::interval + (gs % 10 || ' hours')::interval
       + ((180 + gs * 30) || ' seconds')::interval,
  (30 + gs * 10 % 180),
  (50 + gs * 7  % 50)
FROM users u, generate_series(1, 25) gs
WHERE u.emp_no = 'EMP001';

-- ============================================================
-- 8. 用户画像（基于行为预计算，体现汽轮机偏好）
-- ============================================================
INSERT INTO user_profiles(user_id, device_interests, mfr_interests, fault_interests,
                          keyword_interests, personal_tags, profile_vector,
                          total_behaviors, active_days_30, avg_stay_sec, last_computed_at)
SELECT u.id,
  '{"1":0.95,"2":0.20,"5":0.10}'::jsonb,            -- 设备兴趣：汽轮机0.95，发电机0.20，锅炉0.10
  '{"1":0.92,"3":0.10}'::jsonb,                      -- 厂家兴趣：东方0.92，上海电气0.10
  '{"振动超标":0.88,"密封故障":0.75,"油品异常":0.55}'::jsonb,
  '{"叶片":0.90,"转子":0.85,"汽封":0.72,"润滑油":0.60}'::jsonb,
  '["汽轮机","振动","叶片","东方汽轮机","高压缸"]'::jsonb,
  '[0.95,0.20,0.10,0.92,0.10,0.88,0.75,0.55,0.90,0.85,0.72,0.60]'::jsonb,
  25, 22, 340,
  NOW() - interval '30 minutes'
FROM users u WHERE u.emp_no = 'EMP001';

-- ============================================================
-- 9. 推送配置
-- ============================================================
INSERT INTO push_configs(user_id, score_threshold, max_push_per_day,
    weight_device_type, weight_behavior, weight_role, weight_manufacturer,
    push_window_start, push_window_end,
    channel_in_app, channel_mobile, channel_email, emergency_realtime)
SELECT id, 0.60, 20, 0.35, 0.30, 0.20, 0.15,
       '07:30', '09:00', TRUE, TRUE, FALSE, TRUE
FROM users WHERE emp_no = 'EMP001';

-- ============================================================
-- 10. 推送结果（预计算，直接展示分数对比）
--
--  【汽轮机类 — 高分推送】
--  EVT-2026-001  0.975  紧急跳机 → 设备匹配+行为匹配+岗位匹配+厂家匹配+紧急加成
--  EVT-2026-002  0.882  调节故障 → 四维度均匹配
--  EVT-2026-003  0.856  汽封故障 → 四维度均匹配
--  EVT-2026-004  0.793  润滑油   → 三维度匹配
--  EVT-2026-005  0.765  叶片建议 → 三维度匹配
--
--  【其他设备类 — 低分不推送（低于阈值0.60）】
--  EVT-2026-006  0.482  发电机   → 设备不匹配，行为无历史
--  EVT-2026-007  0.431  励磁系统 → 设备不匹配
--  EVT-2026-008  0.375  锅炉     → 设备不匹配，岗位不匹配
--  EVT-2026-009  0.342  变压器   → 设备不匹配
--  EVT-2026-010  0.425  循环水泵 → 设备部分匹配
-- ============================================================
INSERT INTO push_results(user_id, event_id, push_date, match_score,
    score_breakdown, push_reasons, push_type, is_read, is_clicked)
SELECT
  u.id, e.id, CURRENT_DATE,
  -- 匹配分数
  CASE e.event_no
    WHEN 'EVT-2026-001' THEN 0.9750
    WHEN 'EVT-2026-002' THEN 0.8820
    WHEN 'EVT-2026-003' THEN 0.8560
    WHEN 'EVT-2026-004' THEN 0.7930
    WHEN 'EVT-2026-005' THEN 0.7650
    WHEN 'EVT-2026-006' THEN 0.4820
    WHEN 'EVT-2026-007' THEN 0.4310
    WHEN 'EVT-2026-008' THEN 0.3750
    WHEN 'EVT-2026-009' THEN 0.3420
    WHEN 'EVT-2026-010' THEN 0.4250
  END,
  -- 各维度得分明细
  CASE e.event_no
    WHEN 'EVT-2026-001' THEN '{"device_type":0.35,"behavior":0.29,"role":0.19,"manufacturer":0.13,"emergency_bonus":0.10}'::jsonb
    WHEN 'EVT-2026-002' THEN '{"device_type":0.35,"behavior":0.28,"role":0.18,"manufacturer":0.14}'::jsonb
    WHEN 'EVT-2026-003' THEN '{"device_type":0.34,"behavior":0.27,"role":0.18,"manufacturer":0.14}'::jsonb
    WHEN 'EVT-2026-004' THEN '{"device_type":0.33,"behavior":0.26,"role":0.17,"manufacturer":0.13}'::jsonb
    WHEN 'EVT-2026-005' THEN '{"device_type":0.32,"behavior":0.25,"role":0.17,"manufacturer":0.14}'::jsonb
    WHEN 'EVT-2026-006' THEN '{"device_type":0.10,"behavior":0.15,"role":0.18,"manufacturer":0.05}'::jsonb
    WHEN 'EVT-2026-007' THEN '{"device_type":0.08,"behavior":0.12,"role":0.18,"manufacturer":0.05}'::jsonb
    WHEN 'EVT-2026-008' THEN '{"device_type":0.06,"behavior":0.10,"role":0.15,"manufacturer":0.10}'::jsonb
    WHEN 'EVT-2026-009' THEN '{"device_type":0.05,"behavior":0.09,"role":0.15,"manufacturer":0.06}'::jsonb
    WHEN 'EVT-2026-010' THEN '{"device_type":0.12,"behavior":0.14,"role":0.15,"manufacturer":0.06}'::jsonb
  END,
  -- 推送原因（用于向老师解释系统决策逻辑）
  CASE e.event_no
    WHEN 'EVT-2026-001' THEN '["紧急事件实时推送","① 设备匹配：汽轮机专工 × 汽轮机跳机（0.35）","② 行为匹配：近30日查询振动故障21次（0.29）","③ 岗位匹配：汽轮机专工（0.19）","④ 厂家匹配：东方汽轮机（0.13）"]'::jsonb
    WHEN 'EVT-2026-002' THEN '["① 设备匹配：汽轮机专工 × 调节系统故障（0.35）","② 行为匹配：查询调速器相关8次（0.28）","③ 岗位匹配：汽轮机专工（0.18）","④ 厂家匹配：东方汽轮机（0.14）"]'::jsonb
    WHEN 'EVT-2026-003' THEN '["① 设备匹配：汽轮机专工 × 汽封密封故障（0.34）","② 行为匹配：查询汽封间隙12次（0.27）","③ 岗位匹配：汽轮机专工（0.18）","④ 厂家匹配：东方汽轮机（0.14）"]'::jsonb
    WHEN 'EVT-2026-004' THEN '["① 设备匹配：汽轮机专工 × 汽轮机油系统（0.33）","② 行为匹配：近期查询润滑油相关（0.26）","③ 岗位匹配：汽轮机专工（0.17）","④ 厂家匹配：东方汽轮机（0.13）"]'::jsonb
    WHEN 'EVT-2026-005' THEN '["① 设备匹配：汽轮机专工 × 叶片检查建议（0.32）","② 行为匹配：查询叶片裂纹9次（0.25）","③ 岗位匹配：汽轮机专工（0.17）","④ 厂家匹配：东方汽轮机（0.14）"]'::jsonb
    WHEN 'EVT-2026-006' THEN '["✗ 设备不匹配：发电机（非汽轮机专工管辖，0.10）","✗ 行为无历史：近30日未查询发电机相关（0.15）","△ 岗位部分匹配（0.18）","✗ 厂家不匹配（0.05）","→ 综合得分0.48，低于阈值0.60，不推送"]'::jsonb
    WHEN 'EVT-2026-007' THEN '["✗ 设备不匹配：励磁系统（非汽轮机专工管辖，0.08）","✗ 行为无历史（0.12）","△ 岗位部分匹配（0.18）","→ 综合得分0.43，低于阈值0.60，不推送"]'::jsonb
    WHEN 'EVT-2026-008' THEN '["✗ 设备不匹配：锅炉（非汽轮机专工管辖，0.06）","✗ 行为无历史（0.10）","✗ 岗位不匹配（0.15）","→ 综合得分0.38，低于阈值0.60，不推送"]'::jsonb
    WHEN 'EVT-2026-009' THEN '["✗ 设备不匹配：变压器（0.05）","✗ 行为无历史（0.09）","✗ 岗位不匹配（0.15）","→ 综合得分0.34，低于阈值0.60，不推送"]'::jsonb
    WHEN 'EVT-2026-010' THEN '["△ 设备部分匹配：循环水泵（0.12）","△ 行为少量（0.14）","△ 岗位部分匹配（0.15）","→ 综合得分0.43，低于阈值0.60，不推送"]'::jsonb
  END,
  CASE e.event_no WHEN 'EVT-2026-001' THEN 'emergency' ELSE 'personal' END,
  -- 演示时001已读（模拟运行人员第一时间处理了紧急推送）
  CASE e.event_no WHEN 'EVT-2026-001' THEN TRUE ELSE FALSE END,
  CASE e.event_no WHEN 'EVT-2026-001' THEN TRUE ELSE FALSE END
FROM users u, events e
WHERE u.emp_no = 'EMP001'
  AND e.event_no IN ('EVT-2026-001','EVT-2026-002','EVT-2026-003','EVT-2026-004','EVT-2026-005')
ON CONFLICT (user_id, event_id, push_date) DO NOTHING;

-- ============================================================
-- 验证（取消注释可检查数据条数）
-- ============================================================
-- SELECT '工单' AS 数据类型, COUNT(*) AS 条数 FROM events
-- UNION ALL SELECT 'NLP标签关联', COUNT(*) FROM event_tags
-- UNION ALL SELECT '用户行为',    COUNT(*) FROM user_behaviors
-- UNION ALL SELECT '推送结果',    COUNT(*) FROM push_results;
