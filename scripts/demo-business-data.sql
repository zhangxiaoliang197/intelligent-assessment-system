-- ============================================================
-- 演示业务库 demo_business 初始化脚本
-- 用途：为智能评估系统的 Skill / 数据源功能提供可运行的业务数据。
-- 覆盖作战任务、战果、战损、资源消耗、武器、兵力、装备、库存、
-- 补给、空中能力、威胁目标、指挥指令等评估域。
-- 用法：
--   mysql -h localhost -P 3306 -u root -proot --default-character-set=utf8mb4 < scripts/demo-business-data.sql
-- ============================================================

CREATE DATABASE IF NOT EXISTS demo_business
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE demo_business;

-- ─────────────────────────── 作战任务 ───────────────────────────
CREATE TABLE IF NOT EXISTS t_mission (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '任务ID',
  mission_no    VARCHAR(50)  NOT NULL COMMENT '任务编号',
  mission_name  VARCHAR(200) COMMENT '任务名称',
  mission_type  VARCHAR(50)  COMMENT '任务类型',
  target_name   VARCHAR(100) COMMENT '目标任务',
  unit_id       VARCHAR(50)  COMMENT '执行单位',
  sorties       INT          DEFAULT 0 COMMENT '出动架次',
  status        VARCHAR(20)  COMMENT '任务状态',
  start_time    DATETIME     COMMENT '开始时间',
  end_time      DATETIME     COMMENT '完成时间'
) COMMENT='作战任务表';

INSERT INTO t_mission (mission_no, mission_name, mission_type, target_name, unit_id, sorties, status, start_time, end_time) VALUES
('M-2026-001', '对敌指挥所火力打击', '火力打击',  '敌一号指挥所', 'U-101', 12, '已完成', '2026-07-01 08:00:00', '2026-07-01 09:30:00'),
('M-2026-002', '前沿机场压制',        '火力打击',  '敌前沿机场',   'U-102', 18, '已完成', '2026-07-02 02:00:00', '2026-07-02 04:15:00'),
('M-2026-003', '雷达站侦察确认',      '侦察监视',  '敌雷达站',     'U-103',  8, '已完成', '2026-07-03 10:00:00', '2026-07-03 11:20:00'),
('M-2026-004', '弹药库打击',          '火力打击',  '敌弹药库',     'U-101', 10, '执行中', '2026-07-05 06:30:00', NULL),
('M-2026-005', '预警机协同警戒',      '侦察监视',  '区域警戒',     'U-104',  6, '已完成', '2026-07-06 00:00:00', '2026-07-06 06:00:00'),
('M-2026-006', '装甲集群突击',        '地面突击',  '敌装甲集群',   'U-201', 20, '已完成', '2026-07-08 05:00:00', '2026-07-08 09:00:00');

-- ─────────────────────────── 作战战果 ───────────────────────────
CREATE TABLE IF NOT EXISTS t_combat_result (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '战果ID',
  mission_no      VARCHAR(50) COMMENT '任务编号',
  unit_id         VARCHAR(50) COMMENT '作战单位',
  weapon_type     VARCHAR(50) COMMENT '武器类型',
  target_type     VARCHAR(50) COMMENT '目标类型',
  target_name     VARCHAR(100) COMMENT '目标名称',
  hit_count       INT DEFAULT 0 COMMENT '命中数',
  destroyed_count INT DEFAULT 0 COMMENT '摧毁数',
  target_achieved VARCHAR(20) COMMENT '目标达成情况',
  record_time     DATETIME COMMENT '记录时间'
) COMMENT='作战战果表';

INSERT INTO t_combat_result (mission_no, unit_id, weapon_type, target_type, target_name, hit_count, destroyed_count, target_achieved, record_time) VALUES
('M-2026-001', 'U-101', '空地导弹', '指挥所',    '敌一号指挥所', 8, 2, '达成', '2026-07-01 09:45:00'),
('M-2026-001', 'U-101', '精确制导炸弹', '指挥所', '敌一号指挥所', 6, 1, '达成', '2026-07-01 09:50:00'),
('M-2026-002', 'U-102', '反跑道弹药', '机场',     '敌前沿机场',   12, 3, '达成', '2026-07-02 04:30:00'),
('M-2026-003', 'U-103', '侦察载荷',   '雷达站',   '敌雷达站',     5, 1, '部分达成', '2026-07-03 11:30:00'),
('M-2026-004', 'U-101', '空地导弹',   '弹药库',   '敌弹药库',     9, 2, '执行中', '2026-07-05 07:00:00'),
('M-2026-006', 'U-201', '反装甲导弹', '装甲目标', '敌装甲集群',   15, 5, '达成', '2026-07-08 09:20:00');

-- ─────────────────────────── 作战战损 ───────────────────────────
CREATE TABLE IF NOT EXISTS t_combat_loss (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '战损ID',
  mission_no      VARCHAR(50) COMMENT '任务编号',
  unit_id         VARCHAR(50) COMMENT '所属单位',
  equipment_type  VARCHAR(50) COMMENT '装备类型',
  loss_type       VARCHAR(50) COMMENT '损失原因',
  loss_count      INT DEFAULT 0 COMMENT '损失数量',
  casualty_count  INT DEFAULT 0 COMMENT '伤亡人数',
  loss_time       DATETIME COMMENT '损失时间'
) COMMENT='作战战损表';

INSERT INTO t_combat_loss (mission_no, unit_id, equipment_type, loss_type, loss_count, casualty_count, loss_time) VALUES
('M-2026-001', 'U-101', '战斗机',    '敌方防空火力', 1, 0, '2026-07-01 08:40:00'),
('M-2026-002', 'U-102', '战斗机',    '机械故障',     1, 0, '2026-07-02 03:20:00'),
('M-2026-004', 'U-101', '无人机',    '敌方电子干扰', 2, 0, '2026-07-05 06:50:00'),
('M-2026-006', 'U-201', '装甲车',    '地雷',         2, 3, '2026-07-08 07:10:00'),
('M-2026-006', 'U-201', '坦克',      '敌方反坦克武器', 1, 1, '2026-07-08 08:30:00');

-- ─────────────────────────── 资源消耗 ───────────────────────────
CREATE TABLE IF NOT EXISTS t_resource_consume (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '消耗ID',
  mission_no    VARCHAR(50) COMMENT '任务编号',
  resource_type VARCHAR(50) COMMENT '资源类型',
  resource_name VARCHAR(100) COMMENT '资源名称',
  consume_count DECIMAL(12,2) DEFAULT 0 COMMENT '消耗量',
  unit          VARCHAR(20) COMMENT '计量单位',
  consume_time  DATETIME COMMENT '消耗时间'
) COMMENT='资源消耗表';

INSERT INTO t_resource_consume (mission_no, resource_type, resource_name, consume_count, unit, consume_time) VALUES
('M-2026-001', '弹药', '空空导弹', 24.00, '枚', '2026-07-01 09:10:00'),
('M-2026-001', '燃料', '航空燃油', 35.50, '吨', '2026-07-01 09:30:00'),
('M-2026-002', '弹药', '精确制导炸弹', 18.00, '枚', '2026-07-02 04:00:00'),
('M-2026-004', '物资', '通信设备', 6.00, '套', '2026-07-05 07:20:00'),
('M-2026-006', '弹药', '反装甲导弹', 20.00, '枚', '2026-07-08 08:50:00');

-- ─────────────────────────── 武器装备 ───────────────────────────
CREATE TABLE IF NOT EXISTS t_weapon (
  id          BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '武器ID',
  weapon_name VARCHAR(100) COMMENT '武器名称',
  weapon_type VARCHAR(50) COMMENT '武器类型',
  model       VARCHAR(50) COMMENT '型号',
  total_count INT DEFAULT 0 COMMENT '数量',
  range_km    DECIMAL(10,2) COMMENT '射程(公里)',
  status      VARCHAR(20) COMMENT '状态',
  unit_id     VARCHAR(50) COMMENT '所属单位'
) COMMENT='武器装备表';

INSERT INTO t_weapon (weapon_name, weapon_type, model, total_count, range_km, status, unit_id) VALUES
('歼击机-10A', '战斗机', 'J-10A', 24, 1200.00, '可用', 'U-101'),
('歼击机-16',  '战斗机', 'J-16',  18, 1500.00, '可用', 'U-101'),
('武装直升机-10', '直升机', 'WZ-10', 12, 400.00, '可用', 'U-201'),
('防空导弹系统', '防空武器', 'HQ-9', 16, 200.00, '部分可用', 'U-301'),
('察打一体无人机', '无人机', 'CH-5', 20, 3000.00, '可用', 'U-103');

-- ─────────────────────────── 兵力单位 ───────────────────────────
CREATE TABLE IF NOT EXISTS t_force (
  id               BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '单位ID',
  unit_id          VARCHAR(50) COMMENT '单位编号',
  unit_name        VARCHAR(100) COMMENT '单位名称',
  force_type       VARCHAR(50) COMMENT '军种',
  establishment    INT DEFAULT 0 COMMENT '编制人数',
  present_count    INT DEFAULT 0 COMMENT '在位人数',
  deployable_count INT DEFAULT 0 COMMENT '可出动人数'
) COMMENT='兵力单位表';

INSERT INTO t_force (unit_id, unit_name, force_type, establishment, present_count, deployable_count) VALUES
('U-101', '第一航空兵旅', '空军', 1200, 1150, 980),
('U-102', '第二航空兵旅', '空军', 1100, 1080, 900),
('U-103', '无人侦察大队', '空军', 400, 380, 350),
('U-201', '第一装甲旅',   '陆军', 1800, 1700, 1500),
('U-301', '防空导弹旅',   '防空', 800, 780, 720);

-- ─────────────────────────── 装备完好 ───────────────────────────
CREATE TABLE IF NOT EXISTS t_equipment (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '装备ID',
  unit_id         VARCHAR(50) COMMENT '所属单位',
  equipment_type  VARCHAR(50) COMMENT '装备类型',
  model           VARCHAR(50) COMMENT '型号',
  total_count     INT DEFAULT 0 COMMENT '装备总数',
  available_count INT DEFAULT 0 COMMENT '完好可用数',
  faulty_count    INT DEFAULT 0 COMMENT '故障数',
  online_count    INT DEFAULT 0 COMMENT '在位数量'
) COMMENT='装备完好表';

INSERT INTO t_equipment (unit_id, equipment_type, model, total_count, available_count, faulty_count, online_count) VALUES
('U-101', '战斗机', 'J-10A', 24, 22, 2, 20),
('U-101', '战斗机', 'J-16',  18, 17, 1, 16),
('U-201', '坦克',   'ZTZ-99A', 60, 55, 5, 50),
('U-301', '防空系统', 'HQ-9', 16, 15, 1, 14),
('U-103', '无人机', 'CH-5', 20, 18, 2, 17);

-- ─────────────────────────── 物资库存 ───────────────────────────
CREATE TABLE IF NOT EXISTS t_inventory (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '库存ID',
  resource_type VARCHAR(50) COMMENT '资源类型',
  resource_name VARCHAR(100) COMMENT '物资名称',
  stock_count   DECIMAL(12,2) DEFAULT 0 COMMENT '库存量',
  unit          VARCHAR(20) COMMENT '计量单位',
  alert_level   VARCHAR(20) COMMENT '警戒等级',
  warehouse     VARCHAR(100) COMMENT '仓库',
  update_time   DATETIME COMMENT '更新时间'
) COMMENT='物资库存表';

INSERT INTO t_inventory (resource_type, resource_name, stock_count, unit, alert_level, warehouse, update_time) VALUES
('弹药', '空空导弹', 320.00, '枚', '正常', '弹药库A', '2026-07-31 08:00:00'),
('弹药', '精确制导炸弹', 180.00, '枚', '正常', '弹药库A', '2026-07-31 08:00:00'),
('燃料', '航空燃油', 850.00, '吨', '正常', '油库B',   '2026-07-31 08:00:00'),
('备件', '发动机备件', 45.00, '套', '紧缺', '备件库C', '2026-07-31 08:00:00'),
('物资', '野战食品', 1200.00, '箱', '正常', '物资库D', '2026-07-31 08:00:00');

-- ─────────────────────────── 补给保障 ───────────────────────────
CREATE TABLE IF NOT EXISTS t_supply (
  id               BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '补给ID',
  plan_no          VARCHAR(50) COMMENT '补给计划编号',
  resource_type    VARCHAR(50) COMMENT '资源类型',
  resource_name    VARCHAR(100) COMMENT '资源名称',
  planned_count    DECIMAL(12,2) DEFAULT 0 COMMENT '计划量',
  delivered_count  DECIMAL(12,2) DEFAULT 0 COMMENT '到货量',
  progress         DECIMAL(5,2) COMMENT '完成进度',
  status           VARCHAR(20) COMMENT '状态',
  transport_ability VARCHAR(100) COMMENT '运输能力'
) COMMENT='补给保障表';

INSERT INTO t_supply (plan_no, resource_type, resource_name, planned_count, delivered_count, progress, status, transport_ability) VALUES
('P-001', '弹药', '空空导弹', 200.00, 120.00, 60.00, '进行中', '空运 30 吨/日'),
('P-002', '燃料', '航空燃油', 500.00, 500.00, 100.00, '已完成', '铁路 200 吨/日'),
('P-003', '备件', '发动机备件', 50.00, 10.00, 20.00, '进行中', '公路 5 吨/日'),
('P-004', '物资', '野战食品', 800.00, 800.00, 100.00, '已完成', '公路 40 吨/日');

-- ─────────────────────────── 空中能力 ───────────────────────────
CREATE TABLE IF NOT EXISTS t_air_capability (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '能力ID',
  unit_id         VARCHAR(50) COMMENT '单位',
  capability_type VARCHAR(50) COMMENT '能力分项',
  score           DECIMAL(5,2) COMMENT '评分',
  weight          DECIMAL(5,2) COMMENT '权重',
  eval_date       DATE COMMENT '评估日期'
) COMMENT='空中能力评估表';

INSERT INTO t_air_capability (unit_id, capability_type, score, weight, eval_date) VALUES
('U-101', '占位能力',   88.50, 0.30, '2026-07-31'),
('U-101', '打击能力',   92.00, 0.35, '2026-07-31'),
('U-101', '侦察能力',   85.00, 0.20, '2026-07-31'),
('U-101', '预警能力',   82.00, 0.15, '2026-07-31'),
('U-102', '占位能力',   84.00, 0.30, '2026-07-31'),
('U-102', '打击能力',   89.50, 0.35, '2026-07-31'),
('U-102', '侦察能力',   80.00, 0.20, '2026-07-31'),
('U-102', '预警能力',   78.50, 0.15, '2026-07-31');

-- ─────────────────────────── 威胁目标 ───────────────────────────
CREATE TABLE IF NOT EXISTS t_threat (
  id           BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '目标ID',
  target_name  VARCHAR(100) COMMENT '目标名称',
  target_type  VARCHAR(50) COMMENT '目标类型',
  threat_level VARCHAR(20) COMMENT '威胁等级',
  location     VARCHAR(200) COMMENT '位置',
  status       VARCHAR(20) COMMENT '活动状态',
  detect_time  DATETIME COMMENT '发现时间'
) COMMENT='威胁目标表';

INSERT INTO t_threat (target_name, target_type, threat_level, location, status, detect_time) VALUES
('敌一号指挥所', '指挥设施', '高', '北纬32.5 东经118.2', '活跃', '2026-07-01 06:30:00'),
('敌前沿机场',   '机场',     '高', '北纬32.1 东经117.8', '活跃', '2026-07-02 01:00:00'),
('敌雷达站',     '雷达设施', '中', '北纬31.8 东经118.5', '待确认', '2026-07-03 09:30:00'),
('敌弹药库',     '后勤设施', '高', '北纬32.2 东经118.9', '活跃', '2026-07-05 05:40:00'),
('敌装甲集群',   '装甲目标', '中', '北纬31.5 东经117.5', '移动中', '2026-07-08 04:20:00');

-- ─────────────────────────── 指挥指令 ───────────────────────────
CREATE TABLE IF NOT EXISTS t_command_order (
  id             BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '指令ID',
  order_no       VARCHAR(50) COMMENT '指令编号',
  command_level  VARCHAR(50) COMMENT '指挥层级',
  content        VARCHAR(500) COMMENT '指令内容',
  issue_time     DATETIME COMMENT '下达时间',
  execute_status VARCHAR(20) COMMENT '执行状态',
  response_time  DATETIME COMMENT '响应时间'
) COMMENT='指挥指令表';

INSERT INTO t_command_order (order_no, command_level, content, issue_time, execute_status, response_time) VALUES
('ORD-1001', '战区级', '对敌一号指挥所实施第一波火力打击', '2026-07-01 07:00:00', '已执行', '2026-07-01 07:15:00'),
('ORD-1002', '集团军级', '前沿机场压制任务由第二航空兵旅执行', '2026-07-02 01:30:00', '已执行', '2026-07-02 01:45:00'),
('ORD-1003', '师级', '无人机大队持续侦察敌雷达站动向', '2026-07-03 09:45:00', '已执行', '2026-07-03 10:00:00'),
('ORD-1004', '战区级', '对敌弹药库实施精确打击', '2026-07-05 05:50:00', '执行中', NULL),
('ORD-1005', '集团军级', '装甲集群突击任务启动', '2026-07-08 04:30:00', '已执行', '2026-07-08 04:45:00');
