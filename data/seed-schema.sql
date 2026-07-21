-- 业务数据表结构 + 种子数据
USE `assessment`;

-- 战斗损耗表
CREATE TABLE IF NOT EXISTS `combat_loss` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `unit_name` VARCHAR(100),
    `equipment_type` VARCHAR(100),
    `loss_count` INT,
    `loss_reason` VARCHAR(255),
    `report_time` DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 战斗结果表
CREATE TABLE IF NOT EXISTS `combat_result` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `unit_name` VARCHAR(100),
    `hit_count` INT,
    `destroy_count` INT,
    `battle_name` VARCHAR(100),
    `report_time` DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 为命中率指标补充分母列：射击次数（如已存在则跳过）
-- 命中率 = SUM(hit_count) / SUM(shot_count) × 100%
SET @col_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA='assessment' AND TABLE_NAME='combat_result' AND COLUMN_NAME='shot_count');
SET @sql = IF(@col_exists = 0,
    'ALTER TABLE combat_result ADD COLUMN `shot_count` INT DEFAULT 0 COMMENT ''射击次数'' AFTER `hit_count`',
    'SELECT ''shot_count column already exists'' AS msg');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 资源消耗表
CREATE TABLE IF NOT EXISTS `resource_consume` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `resource_type` VARCHAR(100),
    `amount` DECIMAL(10,2),
    `unit` VARCHAR(50),
    `consumer` VARCHAR(100),
    `report_time` DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 为补给效率指标补充分母/分子列（如已存在则跳过）
-- 补给效率 = SUM(delivered_amount) / SUM(requested_amount) × 100%
SET @col_req = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA='assessment' AND TABLE_NAME='resource_consume' AND COLUMN_NAME='requested_amount');
SET @sql_req = IF(@col_req = 0,
    'ALTER TABLE resource_consume ADD COLUMN `requested_amount` DECIMAL(10,2) DEFAULT 0 COMMENT ''requested_amount'' AFTER `amount`',
    'SELECT ''requested_amount column already exists'' AS msg');
PREPARE stmt_req FROM @sql_req;
EXECUTE stmt_req;
DEALLOCATE PREPARE stmt_req;

SET @col_del = (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA='assessment' AND TABLE_NAME='resource_consume' AND COLUMN_NAME='delivered_amount');
SET @sql_del = IF(@col_del = 0,
    'ALTER TABLE resource_consume ADD COLUMN `delivered_amount` DECIMAL(10,2) DEFAULT 0 COMMENT ''delivered_amount'' AFTER `requested_amount`',
    'SELECT ''delivered_amount column already exists'' AS msg');
PREPARE stmt_del FROM @sql_del;
EXECUTE stmt_del;
DEALLOCATE PREPARE stmt_del;

-- 空中能力表
CREATE TABLE IF NOT EXISTS `air_capability` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `side` VARCHAR(50),
    `capability_type` VARCHAR(50),
    `capability_score` DECIMAL(5,1),
    `aircraft_count` INT,
    `patrol_coverage` DECIMAL(10,1),
    `weapon_count` INT,
    `strike_range` DECIMAL(10,1),
    `recon_range` DECIMAL(10,1),
    `detection_accuracy` DECIMAL(3,2),
    `region` VARCHAR(50)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 单位存活统计表（指标：存活率 = 存活数量 / 初始数量 × 100%）
CREATE TABLE IF NOT EXISTS `unit_survival` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `unit_name` VARCHAR(100),
    `engagement_name` VARCHAR(100),
    `initial_count` INT COMMENT '投入数量',
    `surviving_count` INT COMMENT '存活数量',
    `report_time` DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 突防记录表（指标：突防率 = 成功突防次数 / 总突防次数 × 100%）
CREATE TABLE IF NOT EXISTS `penetration_record` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `unit_name` VARCHAR(100),
    `defense_system` VARCHAR(100) COMMENT '防空体系',
    `total_attempts` INT COMMENT '总突防次数',
    `successful_breaches` INT COMMENT '成功突防次数',
    `report_time` DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 防护能力表（指标：防护能力 = Σ(分项得分 × 权重)）
CREATE TABLE IF NOT EXISTS `protection_capability` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `unit_name` VARCHAR(100),
    `armor_score` DECIMAL(5,1) COMMENT '装甲防护得分',
    `ecm_score` DECIMAL(5,1) COMMENT '电子对抗得分',
    `camouflage_score` DECIMAL(5,1) COMMENT '伪装隐蔽得分',
    `active_defense_score` DECIMAL(5,1) COMMENT '主动防御得分',
    `report_time` DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 维护记录表（指标：维护能力 = 修复次数 / 故障次数）
CREATE TABLE IF NOT EXISTS `maintenance_record` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `unit_name` VARCHAR(100),
    `equipment_type` VARCHAR(100) COMMENT '装备型号',
    `fault_count` INT COMMENT '故障次数',
    `repair_count` INT COMMENT '修复次数',
    `avg_repair_hours` DECIMAL(5,1) COMMENT '平均修复耗时',
    `report_time` DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 任务记录表（指标：任务达成率 = 成功次数 / 总任务数 × 100%）
CREATE TABLE IF NOT EXISTS `mission_record` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `unit_name` VARCHAR(100),
    `mission_type` VARCHAR(100) COMMENT '任务类型',
    `mission_name` VARCHAR(100) COMMENT '任务名称',
    `total_missions` INT COMMENT '总任务数',
    `success_count` INT COMMENT '成功完成数',
    `report_time` DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 任务耗时表（指标：时间效能 = 实际耗时 vs 计划耗时，反应速度 = 响应时间）
CREATE TABLE IF NOT EXISTS `mission_timing` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `unit_name` VARCHAR(100),
    `mission_type` VARCHAR(100) COMMENT '任务类型',
    `planned_hours` DECIMAL(5,1) COMMENT '计划耗时',
    `actual_hours` DECIMAL(5,1) COMMENT '实际耗时',
    `reaction_minutes` DECIMAL(5,1) COMMENT '响应时间',
    `report_time` DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 空中综合评分表
CREATE TABLE IF NOT EXISTS `air_overall` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `side` VARCHAR(50),
    `total_score` DECIMAL(5,1),
    `occupation_score` DECIMAL(5,1),
    `strike_score` DECIMAL(5,1),
    `recon_score` DECIMAL(5,1),
    `region` VARCHAR(50)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 导入种子数据
INSERT INTO combat_loss (unit_name, equipment_type, loss_count, loss_reason, report_time) VALUES
('红方1营','99A坦克',3,'被反坦克导弹击中','2026-07-10 08:30:00'),
('红方2营','ZBD-04步战车',2,'触雷损毁','2026-07-10 09:15:00'),
('红方3营','PLZ-05自行榴弹炮',1,'被精确制导打击','2026-07-10 10:00:00'),
('蓝方A旅','M1A2坦克',5,'被红方空中打击','2026-07-10 14:00:00'),
('蓝方B旅','M2步战车',4,'被炮火覆盖','2026-07-10 15:30:00'),
('蓝方C旅','M109自行炮',2,'被无人机猎杀','2026-07-10 16:00:00'),
('红方1营','04A步战车',1,'机械故障','2026-07-11 07:00:00'),
('蓝方A旅','AH-64武装直升机',2,'被防空导弹击落','2026-07-11 08:30:00');

INSERT INTO combat_result (unit_name, hit_count, destroy_count, battle_name, report_time) VALUES
('红方1营',15,8,'A区突击战','2026-07-10 12:00:00'),
('红方2营',10,5,'B区遭遇战','2026-07-10 12:30:00'),
('蓝方A旅',12,6,'A区防御战','2026-07-10 18:00:00'),
('红方1营',20,12,'C区歼灭战','2026-07-11 10:00:00'),
('蓝方B旅',8,3,'C区阻击战','2026-07-11 18:00:00'),
('红方3营',18,9,'D区火力战','2026-07-12 09:00:00');

INSERT INTO resource_consume (resource_type, amount, unit, consumer, report_time) VALUES
('125mm穿甲弹',320,'发','红方1营','2026-07-10 12:00:00'),
('30mm机关炮弹',1500,'发','红方2营','2026-07-10 12:30:00'),
('155mm榴弹',85,'发','红方3营','2026-07-10 13:00:00'),
('柴油',12.5,'吨','红方后勤连','2026-07-10 18:00:00'),
('120mm坦克弹',200,'发','蓝方A旅','2026-07-10 18:30:00'),
('便携防空导弹',8,'枚','蓝方B旅','2026-07-11 08:30:00'),
('无人机',3,'架','蓝方侦察排','2026-07-11 09:00:00'),
('125mm穿甲弹',450,'发','红方1营','2026-07-11 10:00:00'),
('柴油',8.2,'吨','红方后勤连','2026-07-12 09:00:00'),
('155mm榴弹',120,'发','红方3营','2026-07-12 09:30:00');

INSERT INTO air_capability (side, capability_type, capability_score, aircraft_count, patrol_coverage, weapon_count, strike_range, recon_range, detection_accuracy, region) VALUES
('红方','occupation',85.5,24,320.0,NULL,NULL,NULL,NULL,'A区域'),
('红方','strike',78.0,NULL,NULL,48,1500.0,NULL,NULL,'A区域'),
('红方','recon',72.3,NULL,NULL,NULL,NULL,800.0,0.85,'A区域'),
('蓝方','occupation',65.0,18,250.0,NULL,NULL,NULL,NULL,'A区域'),
('蓝方','strike',82.5,NULL,NULL,55,1200.0,NULL,NULL,'A区域'),
('蓝方','recon',68.0,NULL,NULL,NULL,NULL,650.0,0.78,'A区域'),
('红方','occupation',90.0,30,380.0,NULL,NULL,NULL,NULL,'B区域'),
('红方','strike',85.0,NULL,NULL,60,1600.0,NULL,NULL,'B区域'),
('红方','recon',80.0,NULL,NULL,NULL,NULL,900.0,0.90,'B区域'),
('蓝方','occupation',55.0,12,180.0,NULL,NULL,NULL,NULL,'B区域'),
('蓝方','strike',70.0,NULL,NULL,40,1000.0,NULL,NULL,'B区域'),
('蓝方','recon',60.0,NULL,NULL,NULL,NULL,550.0,0.72,'B区域');

INSERT INTO air_overall (side, total_score, occupation_score, strike_score, recon_score, region) VALUES
('红方',78.6,85.5,78.0,72.3,'A区域'),
('蓝方',71.8,65.0,82.5,68.0,'A区域'),
('红方',85.0,90.0,85.0,80.0,'B区域'),
('蓝方',61.7,55.0,70.0,60.0,'B区域');

-- ── 补充 combat_result 射击次数数据（命中率 = 命中次数 / 射击次数） ──
UPDATE combat_result SET shot_count = 45 WHERE unit_name = '红方1营' AND battle_name = 'A区突击战';
UPDATE combat_result SET shot_count = 35 WHERE unit_name = '红方2营' AND battle_name = 'B区遭遇战';
UPDATE combat_result SET shot_count = 30 WHERE unit_name = '蓝方A旅' AND battle_name = 'A区防御战';
UPDATE combat_result SET shot_count = 55 WHERE unit_name = '红方1营' AND battle_name = 'C区歼灭战';
UPDATE combat_result SET shot_count = 25 WHERE unit_name = '蓝方B旅' AND battle_name = 'C区阻击战';
UPDATE combat_result SET shot_count = 50 WHERE unit_name = '红方3营' AND battle_name = 'D区火力战';

-- ── 单位存活率种子数据（存活率 = 存活数 / 投入数 × 100%） ──
INSERT INTO unit_survival (unit_name, engagement_name, initial_count, surviving_count, report_time) VALUES
('红方1营','A区突击战',30,22,'2026-07-10 12:00:00'),
('红方2营','B区遭遇战',25,18,'2026-07-10 12:30:00'),
('蓝方A旅','A区防御战',28,20,'2026-07-10 18:00:00'),
('红方1营','C区歼灭战',35,23,'2026-07-11 10:00:00'),
('蓝方B旅','C区阻击战',20,14,'2026-07-11 18:00:00'),
('红方3营','D区火力战',32,25,'2026-07-12 09:00:00'),
('蓝方C旅','A区防御战',22,15,'2026-07-10 18:00:00'),
('红方2营','D区火力战',28,21,'2026-07-12 09:00:00');

-- ── 突防率种子数据（突防率 = 成功次数 / 总次数 × 100%） ──
INSERT INTO penetration_record (unit_name, defense_system, total_attempts, successful_breaches, report_time) VALUES
('红方1营','A区域多层防空网',12,7,'2026-07-10 12:00:00'),
('红方2营','A区域多层防空网',8,4,'2026-07-10 12:30:00'),
('蓝方A旅','B区域机动防空群',10,6,'2026-07-10 18:00:00'),
('红方1营','C区域分布式防空',15,9,'2026-07-11 10:00:00'),
('蓝方B旅','C区域分布式防空',9,5,'2026-07-11 18:00:00'),
('红方3营','B区域机动防空群',14,8,'2026-07-12 09:00:00'),
('蓝方C旅','A区域多层防空网',11,7,'2026-07-10 18:00:00'),
('红方1营','B区域机动防空群',13,6,'2026-07-12 09:00:00');

-- ── 补充 resource_consume 补给效率数据 ──
UPDATE resource_consume SET requested_amount = 380, delivered_amount = 320 WHERE resource_type = '125mm穿甲弹' AND consumer = '红方1营' AND amount = 320;
UPDATE resource_consume SET requested_amount = 1600, delivered_amount = 1500 WHERE resource_type = '30mm机关炮弹' AND consumer = '红方2营' AND amount = 1500;
UPDATE resource_consume SET requested_amount = 100, delivered_amount = 85 WHERE resource_type = '155mm榴弹' AND consumer = '红方3营' AND amount = 85;
UPDATE resource_consume SET requested_amount = 14, delivered_amount = 12.5 WHERE resource_type = '柴油' AND consumer = '红方后勤连' AND amount = 12.5;
UPDATE resource_consume SET requested_amount = 240, delivered_amount = 200 WHERE resource_type = '120mm坦克弹' AND consumer = '蓝方A旅' AND amount = 200;
UPDATE resource_consume SET requested_amount = 10, delivered_amount = 8 WHERE resource_type = '便携防空导弹' AND consumer = '蓝方B旅' AND amount = 8;
UPDATE resource_consume SET requested_amount = 3, delivered_amount = 3 WHERE resource_type = '无人机' AND consumer = '蓝方侦察排' AND amount = 3;
UPDATE resource_consume SET requested_amount = 500, delivered_amount = 450 WHERE resource_type = '125mm穿甲弹' AND consumer = '红方1营' AND amount = 450;
UPDATE resource_consume SET requested_amount = 9, delivered_amount = 8.2 WHERE resource_type = '柴油' AND consumer = '红方后勤连' AND amount = 8.2;
UPDATE resource_consume SET requested_amount = 140, delivered_amount = 120 WHERE resource_type = '155mm榴弹' AND consumer = '红方3营' AND amount = 120;

-- ── 防护能力种子数据 ──
INSERT INTO protection_capability (unit_name, armor_score, ecm_score, camouflage_score, active_defense_score, report_time) VALUES
('红方1营',82.0,68.5,75.0,70.0,'2026-07-10 12:00:00'),
('红方2营',75.0,72.0,80.5,65.5,'2026-07-10 12:30:00'),
('红方3营',88.5,60.0,62.0,78.0,'2026-07-10 13:00:00'),
('蓝方A旅',90.0,85.0,72.0,82.0,'2026-07-10 18:00:00'),
('蓝方B旅',78.0,80.5,68.0,70.5,'2026-07-11 18:00:00'),
('蓝方C旅',85.0,75.0,65.5,75.0,'2026-07-11 18:00:00'),
('红方1营',80.0,70.0,78.0,72.5,'2026-07-11 10:00:00'),
('红方3营',86.0,62.5,65.0,76.0,'2026-07-12 09:00:00');

-- ── 维护能力种子数据 ──
INSERT INTO maintenance_record (unit_name, equipment_type, fault_count, repair_count, avg_repair_hours, report_time) VALUES
('红方1营','99A坦克',5,4,3.2,'2026-07-10 12:00:00'),
('红方2营','ZBD-04步战车',3,2,4.5,'2026-07-10 12:30:00'),
('红方3营','PLZ-05自行榴弹炮',4,3,2.8,'2026-07-10 13:00:00'),
('蓝方A旅','M1A2坦克',6,5,2.5,'2026-07-10 18:00:00'),
('蓝方B旅','M2步战车',4,3,3.8,'2026-07-11 18:00:00'),
('蓝方C旅','M109自行炮',3,2,4.0,'2026-07-11 18:00:00'),
('红方1营','04A步战车',2,2,1.5,'2026-07-11 10:00:00'),
('红方3营','PGZ-09自行高炮',3,3,2.0,'2026-07-12 09:00:00');

-- ── 任务达成率种子数据 ──
INSERT INTO mission_record (unit_name, mission_type, mission_name, total_missions, success_count, report_time) VALUES
('红方1营','突击','A区突破',8,6,'2026-07-10 12:00:00'),
('红方2营','遭遇','B区遭遇战',5,3,'2026-07-10 12:30:00'),
('蓝方A旅','防御','A区阵地防御',7,5,'2026-07-10 18:00:00'),
('红方1营','歼灭','C区包抄',10,7,'2026-07-11 10:00:00'),
('蓝方B旅','阻击','C区迟滞',6,4,'2026-07-11 18:00:00'),
('红方3营','火力','D区压制',9,6,'2026-07-12 09:00:00'),
('蓝方C旅','侦察','A区侦察',4,3,'2026-07-10 18:00:00'),
('红方2营','火力','D区协同',7,5,'2026-07-12 09:00:00');

-- ── 时间效能种子数据 ──
INSERT INTO mission_timing (unit_name, mission_type, planned_hours, actual_hours, reaction_minutes, report_time) VALUES
('红方1营','突击',4.0,5.2,12,'2026-07-10 12:00:00'),
('红方2营','遭遇',2.5,3.8,18,'2026-07-10 12:30:00'),
('蓝方A旅','防御',6.0,5.5,8,'2026-07-10 18:00:00'),
('红方1营','歼灭',8.0,9.5,15,'2026-07-11 10:00:00'),
('蓝方B旅','阻击',3.0,2.8,10,'2026-07-11 18:00:00'),
('红方3营','火力',5.0,6.2,14,'2026-07-12 09:00:00'),
('蓝方C旅','侦察',1.5,1.8,6,'2026-07-10 18:00:00'),
('红方2营','火力',4.5,5.0,20,'2026-07-12 09:00:00');
