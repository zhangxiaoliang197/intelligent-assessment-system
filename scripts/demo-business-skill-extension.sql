-- ============================================================
-- demo_business Skill 语义补充数据
-- 用于为内置 Skill 提供稳定、独立、可追溯的证据表。
-- 脚本可重复执行：主键冲突时更新演示记录。
-- ============================================================

CREATE DATABASE IF NOT EXISTS demo_business
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE demo_business;

CREATE TABLE IF NOT EXISTS t_air_overall (
  eval_no          VARCHAR(50) PRIMARY KEY COMMENT '评估编号',
  side_name        VARCHAR(30)  NOT NULL COMMENT '对抗方',
  unit_id          VARCHAR(50)  COMMENT '单位编号',
  overall_score    DECIMAL(5,2) COMMENT '总体制空能力评分',
  air_control_level VARCHAR(30) COMMENT '制空权等级',
  eval_date        DATE         COMMENT '评估日期',
  evidence_summary VARCHAR(300) COMMENT '评估依据'
) COMMENT='总体制空能力评估表';

INSERT INTO t_air_overall
  (eval_no, side_name, unit_id, overall_score, air_control_level, eval_date, evidence_summary)
VALUES
  ('AIR-20260731-R1', '红方', 'U-101', 87.90, '区域优势', '2026-07-31', '占位、打击、侦察和预警加权结果'),
  ('AIR-20260731-R2', '红方', 'U-102', 84.10, '区域优势', '2026-07-31', '第二航空兵旅综合能力评估'),
  ('AIR-20260731-B1', '蓝方', 'B-201', 76.30, '局部均势', '2026-07-31', '敌前沿机场与雷达站能力综合评估'),
  ('AIR-20260731-B2', '蓝方', 'B-202', 71.80, '局部劣势', '2026-07-31', '敌防空节点和可用架次综合评估')
ON DUPLICATE KEY UPDATE
  overall_score = VALUES(overall_score),
  air_control_level = VALUES(air_control_level),
  evidence_summary = VALUES(evidence_summary);

CREATE TABLE IF NOT EXISTS t_recon_intelligence (
  recon_no               VARCHAR(50) PRIMARY KEY COMMENT '侦察编号',
  mission_no             VARCHAR(50) COMMENT '任务编号',
  unit_id                VARCHAR(50) COMMENT '侦察单位',
  target_name            VARCHAR(100) COMMENT '发现目标',
  intelligence_source    VARCHAR(50) COMMENT '情报来源',
  coverage_rate          DECIMAL(5,2) COMMENT '侦察覆盖率百分比',
  identification_accuracy DECIMAL(5,2) COMMENT '识别准确率百分比',
  confidence_level       VARCHAR(20) COMMENT '情报可信度',
  discovered_time        DATETIME COMMENT '发现时间'
) COMMENT='侦察情报发现记录表';

INSERT INTO t_recon_intelligence
  (recon_no, mission_no, unit_id, target_name, intelligence_source, coverage_rate, identification_accuracy, confidence_level, discovered_time)
VALUES
  ('REC-001', 'M-2026-003', 'U-103', '敌雷达站', '无人机光电', 92.00, 96.50, '高', '2026-07-03 09:30:00'),
  ('REC-002', 'M-2026-005', 'U-104', '区域不明目标', '预警机雷达', 88.00, 91.20, '中', '2026-07-06 01:15:00'),
  ('REC-003', 'M-2026-004', 'U-103', '敌弹药库', '卫星图像', 85.50, 94.00, '高', '2026-07-05 05:20:00'),
  ('REC-004', 'M-2026-006', 'U-103', '敌装甲集群', '无人机合成孔径雷达', 79.00, 89.50, '中', '2026-07-08 04:00:00')
ON DUPLICATE KEY UPDATE
  coverage_rate = VALUES(coverage_rate),
  identification_accuracy = VALUES(identification_accuracy),
  confidence_level = VALUES(confidence_level);

CREATE TABLE IF NOT EXISTS t_warning_event (
  warning_no      VARCHAR(50) PRIMARY KEY COMMENT '预警编号',
  target_name     VARCHAR(100) COMMENT '告警目标',
  warning_level   VARCHAR(20) COMMENT '告警等级',
  advance_minutes INT COMMENT '预警提前量分钟',
  detection_source VARCHAR(50) COMMENT '探测来源',
  handling_status VARCHAR(30) COMMENT '处置状态',
  warning_time    DATETIME COMMENT '告警时间',
  response_time   DATETIME COMMENT '处置响应时间'
) COMMENT='预警告警处置记录表';

INSERT INTO t_warning_event
  (warning_no, target_name, warning_level, advance_minutes, detection_source, handling_status, warning_time, response_time)
VALUES
  ('WAR-001', '敌前沿机场机群', '高', 28, '预警机雷达', '已处置', '2026-07-02 01:02:00', '2026-07-02 01:08:00'),
  ('WAR-002', '区域不明目标', '中', 18, '地面相控阵列', '已核验', '2026-07-06 01:20:00', '2026-07-06 01:31:00'),
  ('WAR-003', '敌防空雷达开机', '高', 35, '电子侦察', '已分发', '2026-07-03 09:32:00', '2026-07-03 09:36:00'),
  ('WAR-004', '敌装甲集群机动', '中', 22, '无人机雷达', '已处置', '2026-07-08 04:05:00', '2026-07-08 04:12:00')
ON DUPLICATE KEY UPDATE
  advance_minutes = VALUES(advance_minutes),
  handling_status = VALUES(handling_status),
  response_time = VALUES(response_time);

CREATE TABLE IF NOT EXISTS t_maintenance (
  maintenance_no  VARCHAR(50) PRIMARY KEY COMMENT '维修记录编号',
  unit_id         VARCHAR(50) COMMENT '所属单位',
  equipment_type  VARCHAR(50) COMMENT '装备类型',
  model           VARCHAR(50) COMMENT '装备型号',
  fault_count     INT COMMENT '故障数量',
  repaired_count  INT COMMENT '已修复数量',
  pending_count   INT COMMENT '待修数量',
  spare_part_status VARCHAR(30) COMMENT '备件保障状态',
  recovery_hours  DECIMAL(8,2) COMMENT '预计恢复时长小时',
  record_time     DATETIME COMMENT '统计时间'
) COMMENT='装备维修保障记录表';

INSERT INTO t_maintenance
  (maintenance_no, unit_id, equipment_type, model, fault_count, repaired_count, pending_count, spare_part_status, recovery_hours, record_time)
VALUES
  ('MNT-001', 'U-101', '战斗机', 'J-10A', 2, 1, 1, '充足', 6.00, '2026-07-31 08:00:00'),
  ('MNT-002', 'U-101', '战斗机', 'J-16', 1, 1, 0, '充足', 0.00, '2026-07-31 08:00:00'),
  ('MNT-003', 'U-201', '坦克', 'ZTZ-99A', 5, 3, 2, '紧张', 18.00, '2026-07-31 08:00:00'),
  ('MNT-004', 'U-301', '防空系统', 'HQ-9', 1, 0, 1, '充足', 8.00, '2026-07-31 08:00:00'),
  ('MNT-005', 'U-103', '无人机', 'CH-5', 2, 1, 1, '紧张', 12.00, '2026-07-31 08:00:00')
ON DUPLICATE KEY UPDATE
  fault_count = VALUES(fault_count),
  repaired_count = VALUES(repaired_count),
  pending_count = VALUES(pending_count),
  spare_part_status = VALUES(spare_part_status),
  recovery_hours = VALUES(recovery_hours);

CREATE TABLE IF NOT EXISTS t_deployment (
  deployment_no   VARCHAR(50) PRIMARY KEY COMMENT '部署编号',
  side_name       VARCHAR(30) COMMENT '对抗方',
  unit_id         VARCHAR(50) COMMENT '单位编号',
  force_type      VARCHAR(50) COMMENT '兵力类型',
  region          VARCHAR(100) COMMENT '部署区域',
  personnel_count INT COMMENT '人员数量',
  equipment_count INT COMMENT '装备数量',
  readiness_status VARCHAR(30) COMMENT '战备状态',
  update_time     DATETIME COMMENT '更新时间'
) COMMENT='兵力部署态势表';

INSERT INTO t_deployment
  (deployment_no, side_name, unit_id, force_type, region, personnel_count, equipment_count, readiness_status, update_time)
VALUES
  ('DEP-001', '红方', 'U-101', '航空兵', 'A区域东部', 980, 38, '一级战备', '2026-07-31 08:00:00'),
  ('DEP-002', '红方', 'U-201', '装甲兵', 'B区域南部', 1500, 50, '二级战备', '2026-07-31 08:00:00'),
  ('DEP-003', '红方', 'U-301', '防空兵', 'A区域西部', 720, 14, '一级战备', '2026-07-31 08:00:00'),
  ('DEP-004', '蓝方', 'B-201', '航空兵', 'A区域北部', 860, 30, '二级战备', '2026-07-31 08:00:00'),
  ('DEP-005', '蓝方', 'B-301', '防空兵', 'B区域北部', 640, 12, '二级战备', '2026-07-31 08:00:00')
ON DUPLICATE KEY UPDATE
  personnel_count = VALUES(personnel_count),
  equipment_count = VALUES(equipment_count),
  readiness_status = VALUES(readiness_status);

CREATE TABLE IF NOT EXISTS t_defense (
  defense_no        VARCHAR(50) PRIMARY KEY COMMENT '防御单元编号',
  unit_id           VARCHAR(50) COMMENT '所属单位',
  region            VARCHAR(100) COMMENT '防护区域',
  defense_type      VARCHAR(50) COMMENT '防御类型',
  coverage_km       DECIMAL(10,2) COMMENT '防护覆盖半径公里',
  protection_level  VARCHAR(30) COMMENT '防护等级',
  interceptor_count INT COMMENT '拦截弹数量',
  available_count   INT COMMENT '可用拦截数量',
  status            VARCHAR(30) COMMENT '防御状态'
) COMMENT='防御防护配置表';

INSERT INTO t_defense
  (defense_no, unit_id, region, defense_type, coverage_km, protection_level, interceptor_count, available_count, status)
VALUES
  ('DEF-001', 'U-301', 'A区域东部', '远程防空', 200.00, '一级', 48, 44, '战备'),
  ('DEF-002', 'U-301', 'A区域西部', '中程防空', 80.00, '二级', 36, 31, '战备'),
  ('DEF-003', 'U-201', 'B区域南部', '野战防护', 25.00, '二级', 24, 20, '机动中'),
  ('DEF-004', 'U-101', 'A区域东部', '机场要地防护', 45.00, '一级', 32, 30, '战备')
ON DUPLICATE KEY UPDATE
  coverage_km = VALUES(coverage_km),
  protection_level = VALUES(protection_level),
  available_count = VALUES(available_count),
  status = VALUES(status);

CREATE TABLE IF NOT EXISTS t_unit_master (
  unit_id       VARCHAR(50) PRIMARY KEY COMMENT '单位编号',
  unit_name     VARCHAR(100) NOT NULL COMMENT '单位名称',
  parent_unit   VARCHAR(100) COMMENT '上级单位',
  force_type    VARCHAR(50) COMMENT '军兵种',
  region        VARCHAR(100) COMMENT '所属区域',
  commander     VARCHAR(50) COMMENT '指挥员',
  establishment INT COMMENT '编制人数',
  status        VARCHAR(30) COMMENT '单位状态'
) COMMENT='单位主数据基础表';

INSERT INTO t_unit_master
  (unit_id, unit_name, parent_unit, force_type, region, commander, establishment, status)
VALUES
  ('U-101', '第一航空兵旅', '空军指挥部', '空军', 'A区域', '张某', 1200, '现役'),
  ('U-102', '第二航空兵旅', '空军指挥部', '空军', 'A区域', '李某', 1100, '现役'),
  ('U-103', '无人侦察大队', '空军指挥部', '空军', 'A区域', '王某', 400, '现役'),
  ('U-201', '第一装甲旅', '陆军指挥部', '陆军', 'B区域', '赵某', 1800, '现役'),
  ('U-301', '防空导弹旅', '战区指挥部', '防空', 'A区域', '陈某', 800, '现役')
ON DUPLICATE KEY UPDATE
  unit_name = VALUES(unit_name),
  parent_unit = VALUES(parent_unit),
  region = VALUES(region),
  establishment = VALUES(establishment),
  status = VALUES(status);
