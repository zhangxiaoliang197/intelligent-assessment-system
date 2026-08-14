-- ============================================================
-- 态势图可视化演示数据（可重复执行）
-- 生成约 18000 条近 180 天、可联表的演示记录，并为 19 个物理数据集配置 ACL。
-- ============================================================

CREATE DATABASE IF NOT EXISTS demo_business
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE demo_business;

CREATE TABLE IF NOT EXISTS t_mission (
  id BIGINT PRIMARY KEY AUTO_INCREMENT, mission_no VARCHAR(50) NOT NULL,
  mission_name VARCHAR(200), mission_type VARCHAR(50), target_name VARCHAR(100),
  unit_id VARCHAR(50), sorties INT DEFAULT 0, status VARCHAR(20),
  start_time DATETIME, end_time DATETIME
);
CREATE TABLE IF NOT EXISTS t_deployment (
  deployment_no VARCHAR(50) PRIMARY KEY, side_name VARCHAR(30), unit_id VARCHAR(50),
  force_type VARCHAR(50), region VARCHAR(100), personnel_count INT,
  equipment_count INT, readiness_status VARCHAR(30), update_time DATETIME
);
CREATE TABLE IF NOT EXISTS t_threat (
  id BIGINT PRIMARY KEY AUTO_INCREMENT, target_name VARCHAR(100), target_type VARCHAR(50),
  threat_level VARCHAR(20), location VARCHAR(200), status VARCHAR(20), detect_time DATETIME
);
CREATE TABLE IF NOT EXISTS t_supply (
  id BIGINT PRIMARY KEY AUTO_INCREMENT, plan_no VARCHAR(50), resource_type VARCHAR(50),
  resource_name VARCHAR(100), planned_count DECIMAL(12,2) DEFAULT 0,
  delivered_count DECIMAL(12,2) DEFAULT 0, progress DECIMAL(5,2),
  status VARCHAR(20), transport_ability VARCHAR(100)
);

DELIMITER $$
DROP PROCEDURE IF EXISTS demo_business.sp_add_situation_column$$
CREATE PROCEDURE demo_business.sp_add_situation_column(
  IN p_table VARCHAR(64), IN p_column VARCHAR(64), IN p_definition VARCHAR(255)
)
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'demo_business' AND table_name = p_table AND column_name = p_column
  ) THEN
    SET @ddl = CONCAT(
      'ALTER TABLE `demo_business`.`', p_table, '` ADD COLUMN `',
      p_column, '` ', p_definition
    );
    PREPARE statement FROM @ddl;
    EXECUTE statement;
    DEALLOCATE PREPARE statement;
  END IF;
END$$
DELIMITER ;

CALL demo_business.sp_add_situation_column('t_mission', 'region', 'VARCHAR(50) COMMENT ''任务区域''');
CALL demo_business.sp_add_situation_column('t_mission', 'side_name', 'VARCHAR(20) COMMENT ''任务方''');
CALL demo_business.sp_add_situation_column('t_mission', 'longitude', 'DECIMAL(10,6) COMMENT ''经度''');
CALL demo_business.sp_add_situation_column('t_mission', 'latitude', 'DECIMAL(10,6) COMMENT ''纬度''');
CALL demo_business.sp_add_situation_column('t_mission', 'completion_rate', 'DECIMAL(5,2) COMMENT ''完成率''');
CALL demo_business.sp_add_situation_column('t_mission', 'risk_score', 'DECIMAL(5,2) COMMENT ''风险评分''');

CALL demo_business.sp_add_situation_column('t_deployment', 'longitude', 'DECIMAL(10,6) COMMENT ''经度''');
CALL demo_business.sp_add_situation_column('t_deployment', 'latitude', 'DECIMAL(10,6) COMMENT ''纬度''');
CALL demo_business.sp_add_situation_column('t_deployment', 'combat_power', 'DECIMAL(8,2) COMMENT ''综合战力''');
CALL demo_business.sp_add_situation_column('t_deployment', 'mobility_score', 'DECIMAL(5,2) COMMENT ''机动评分''');

CALL demo_business.sp_add_situation_column('t_threat', 'region', 'VARCHAR(50) COMMENT ''威胁区域''');
CALL demo_business.sp_add_situation_column('t_threat', 'longitude', 'DECIMAL(10,6) COMMENT ''经度''');
CALL demo_business.sp_add_situation_column('t_threat', 'latitude', 'DECIMAL(10,6) COMMENT ''纬度''');
CALL demo_business.sp_add_situation_column('t_threat', 'confidence_score', 'DECIMAL(5,2) COMMENT ''情报置信度''');
CALL demo_business.sp_add_situation_column('t_threat', 'risk_score', 'DECIMAL(5,2) COMMENT ''威胁评分''');

CALL demo_business.sp_add_situation_column('t_supply', 'region', 'VARCHAR(50) COMMENT ''保障区域''');
CALL demo_business.sp_add_situation_column('t_supply', 'longitude', 'DECIMAL(10,6) COMMENT ''经度''');
CALL demo_business.sp_add_situation_column('t_supply', 'latitude', 'DECIMAL(10,6) COMMENT ''纬度''');
CALL demo_business.sp_add_situation_column('t_supply', 'planned_time', 'DATETIME COMMENT ''计划时间''');
CALL demo_business.sp_add_situation_column('t_supply', 'delivered_time', 'DATETIME COMMENT ''到达时间''');
CALL demo_business.sp_add_situation_column('t_supply', 'risk_level', 'VARCHAR(20) COMMENT ''保障风险''');
CALL demo_business.sp_add_situation_column('t_supply', 'support_score', 'DECIMAL(5,2) COMMENT ''保障评分''');

USE demo_business;

DROP TEMPORARY TABLE IF EXISTS tmp_situation_seq;
CREATE TEMPORARY TABLE tmp_situation_seq (n INT PRIMARY KEY);
INSERT INTO tmp_situation_seq (n)
SELECT ones.d + tens.d * 10 + hundreds.d * 100 + 1
FROM
  (SELECT 0 d UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
   UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) ones
CROSS JOIN
  (SELECT 0 d UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
   UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) tens
CROSS JOIN
  (SELECT 0 d UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
   UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) hundreds
WHERE ones.d + tens.d * 10 + hundreds.d * 100 < 1000;

DELETE FROM t_mission WHERE mission_no LIKE 'SIM-M-%';
INSERT INTO t_mission (
  mission_no, mission_name, mission_type, target_name, unit_id, sorties, status,
  start_time, end_time, region, side_name, longitude, latitude, completion_rate, risk_score
)
SELECT
  CONCAT('SIM-M-', LPAD(n, 4, '0')),
  CONCAT(ELT(MOD(n - 1, 6) + 1, '联合侦察', '要地防护', '火力压制', '机动增援', '空中巡逻', '补给护送'), '-', LPAD(n, 2, '0')),
  ELT(MOD(n - 1, 6) + 1, '侦察监视', '防空警戒', '火力打击', '地面突击', '空中巡逻', '保障运输'),
  ELT(MOD(n - 1, 8) + 1, '北部机场', '东部雷达站', '南部装甲群', '西部补给线', '中心指挥所', '前沿通信站', '机动发射阵地', '关键交通节点'),
  ELT(MOD(n - 1, 8) + 1, 'U-101', 'U-102', 'U-103', 'U-201', 'U-301', 'B-201', 'B-202', 'B-301'),
  4 + MOD(n * 7, 25),
  ELT(MOD(n - 1, 5) + 1, '已完成', '执行中', '待执行', '受阻', '已完成'),
  DATE_SUB(NOW(), INTERVAL (n * 12) HOUR),
  CASE WHEN MOD(n - 1, 5) IN (0, 4) THEN DATE_SUB(NOW(), INTERVAL (n * 12 - 3) HOUR) ELSE NULL END,
  ELT(MOD(n - 1, 6) + 1, 'A区域东部', 'A区域西部', 'B区域南部', 'B区域北部', 'C区域中心', 'D区域前沿'),
  IF(MOD(n, 4) = 0, '蓝方', '红方'),
  ROUND(116.10 + MOD(n * 13, 36) / 10, 6),
  ROUND(30.40 + MOD(n * 11, 34) / 10, 6),
  ELT(MOD(n - 1, 5) + 1, 100, 55 + MOD(n, 35), 0, 25 + MOD(n, 25), 100),
  ROUND(28 + MOD(n * 17, 69), 2)
FROM tmp_situation_seq;

DELETE FROM t_deployment WHERE deployment_no LIKE 'SIM-DEP-%';
INSERT INTO t_deployment (
  deployment_no, side_name, unit_id, force_type, region, personnel_count,
  equipment_count, readiness_status, update_time, longitude, latitude,
  combat_power, mobility_score
)
SELECT
  CONCAT('SIM-DEP-', LPAD(n, 4, '0')),
  IF(MOD(n, 4) = 0, '蓝方', '红方'),
  ELT(MOD(n - 1, 8) + 1, 'U-101', 'U-102', 'U-103', 'U-201', 'U-301', 'B-201', 'B-202', 'B-301'),
  ELT(MOD(n - 1, 6) + 1, '航空兵', '装甲兵', '防空兵', '侦察兵', '电子对抗', '保障兵'),
  ELT(MOD(n - 1, 6) + 1, 'A区域东部', 'A区域西部', 'B区域南部', 'B区域北部', 'C区域中心', 'D区域前沿'),
  360 + MOD(n * 137, 1250),
  8 + MOD(n * 11, 58),
  ELT(MOD(n - 1, 4) + 1, '一级战备', '二级战备', '机动中', '休整补充'),
  DATE_SUB(NOW(), INTERVAL (n * 18) HOUR),
  ROUND(116.00 + MOD(n * 17, 38) / 10, 6),
  ROUND(30.30 + MOD(n * 7, 36) / 10, 6),
  ROUND(52 + MOD(n * 19, 46), 2),
  ROUND(48 + MOD(n * 23, 50), 2)
FROM tmp_situation_seq;

-- ───────────────────────── 其余 15 类 Skill 证据表 ─────────────────────────
-- 每张表都使用 SIM-* 业务键，重复执行时先删演示记录，不影响用户已有数据。
CREATE TABLE IF NOT EXISTS t_resource_consume (
  consume_no VARCHAR(50) PRIMARY KEY, mission_no VARCHAR(50), unit_id VARCHAR(50),
  resource_type VARCHAR(50), resource_name VARCHAR(100), consume_count DECIMAL(12,2),
  measure_unit VARCHAR(20), region VARCHAR(50), consume_time DATETIME,
  longitude DECIMAL(10,6), latitude DECIMAL(10,6), cost_score DECIMAL(8,2)
);
CALL demo_business.sp_add_situation_column('t_resource_consume','consume_no','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_resource_consume','unit_id','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_resource_consume','measure_unit','VARCHAR(20)');
CALL demo_business.sp_add_situation_column('t_resource_consume','region','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_resource_consume','longitude','DECIMAL(10,6)');
CALL demo_business.sp_add_situation_column('t_resource_consume','latitude','DECIMAL(10,6)');
CALL demo_business.sp_add_situation_column('t_resource_consume','cost_score','DECIMAL(8,2)');
DELETE FROM t_resource_consume WHERE consume_no LIKE 'SIM-RC-%';
INSERT INTO t_resource_consume
  (consume_no,mission_no,unit_id,resource_type,resource_name,consume_count,measure_unit,region,consume_time,longitude,latitude,cost_score)
SELECT
  CONCAT('SIM-RC-', LPAD(n,4,'0')), CONCAT('SIM-M-',LPAD(MOD(n-1,1000)+1,4,'0')),
  CONCAT(IF(MOD(n,4)=0,'B-','U-'),100+MOD(n,24)),
  ELT(MOD(n-1,5)+1,'弹药','燃料','备件','物资','医疗'),
  ELT(MOD(n-1,8)+1,'精确制导弹药','航空燃油','发动机备件','野战食品','急救药品','通信器材','装甲备件','无人机电池'),
  ROUND(8+MOD(n*37,420),2), ELT(MOD(n-1,4)+1,'枚','吨','套','箱'),
  ELT(MOD(n-1,6)+1,'A区域东部','A区域西部','B区域南部','B区域北部','C区域中心','D区域前沿'),
  DATE_SUB(NOW(),INTERVAL n*9 HOUR), ROUND(116+MOD(n*11,38)/10,6),
  ROUND(30.2+MOD(n*17,38)/10,6), ROUND(20+MOD(n*19,79),2)
FROM tmp_situation_seq;

CREATE TABLE IF NOT EXISTS t_combat_result (
  result_no VARCHAR(50) PRIMARY KEY, mission_no VARCHAR(50), unit_id VARCHAR(50),
  weapon_type VARCHAR(50), target_type VARCHAR(50), target_name VARCHAR(100),
  hit_count INT, destroyed_count INT, success_rate DECIMAL(5,2), target_achieved VARCHAR(30),
  region VARCHAR(50), longitude DECIMAL(10,6), latitude DECIMAL(10,6), record_time DATETIME
);
CALL demo_business.sp_add_situation_column('t_combat_result','result_no','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_combat_result','success_rate','DECIMAL(5,2)');
CALL demo_business.sp_add_situation_column('t_combat_result','region','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_combat_result','longitude','DECIMAL(10,6)');
CALL demo_business.sp_add_situation_column('t_combat_result','latitude','DECIMAL(10,6)');
DELETE FROM t_combat_result WHERE result_no LIKE 'SIM-CR-%';
INSERT INTO t_combat_result
  (result_no,mission_no,unit_id,weapon_type,target_type,target_name,hit_count,destroyed_count,success_rate,target_achieved,region,longitude,latitude,record_time)
SELECT
  CONCAT('SIM-CR-',LPAD(n,4,'0')), CONCAT('SIM-M-',LPAD(MOD(n-1,1000)+1,4,'0')),
  CONCAT(IF(MOD(n,5)=0,'B-','U-'),100+MOD(n,24)),
  ELT(MOD(n-1,6)+1,'空地导弹','精确制导炸弹','反装甲导弹','无人机载荷','远程火箭','电子压制'),
  ELT(MOD(n-1,6)+1,'指挥设施','机场','装甲目标','雷达设施','后勤节点','通信节点'),
  CONCAT('SIM目标-',LPAD(n,3,'0')), 3+MOD(n*7,30), 1+MOD(n*5,15),
  ROUND(45+MOD(n*23,55),2), ELT(MOD(n-1,4)+1,'达成','部分达成','执行中','未达成'),
  ELT(MOD(n-1,6)+1,'A区域东部','A区域西部','B区域南部','B区域北部','C区域中心','D区域前沿'),
  ROUND(116.1+MOD(n*13,36)/10,6), ROUND(30.3+MOD(n*7,36)/10,6), DATE_SUB(NOW(),INTERVAL n*11 HOUR)
FROM tmp_situation_seq;

CREATE TABLE IF NOT EXISTS t_combat_loss (
  loss_no VARCHAR(50) PRIMARY KEY, mission_no VARCHAR(50), unit_id VARCHAR(50), side_name VARCHAR(20),
  equipment_type VARCHAR(50), loss_type VARCHAR(50), loss_count INT, casualty_count INT,
  region VARCHAR(50), longitude DECIMAL(10,6), latitude DECIMAL(10,6), impact_score DECIMAL(5,2), loss_time DATETIME
);
CALL demo_business.sp_add_situation_column('t_combat_loss','loss_no','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_combat_loss','side_name','VARCHAR(20)');
CALL demo_business.sp_add_situation_column('t_combat_loss','region','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_combat_loss','longitude','DECIMAL(10,6)');
CALL demo_business.sp_add_situation_column('t_combat_loss','latitude','DECIMAL(10,6)');
CALL demo_business.sp_add_situation_column('t_combat_loss','impact_score','DECIMAL(5,2)');
DELETE FROM t_combat_loss WHERE loss_no LIKE 'SIM-CL-%';
INSERT INTO t_combat_loss
  (loss_no,mission_no,unit_id,side_name,equipment_type,loss_type,loss_count,casualty_count,region,longitude,latitude,impact_score,loss_time)
SELECT CONCAT('SIM-CL-',LPAD(n,4,'0')),
  CONCAT('SIM-M-',LPAD(MOD(n-1,1000)+1,4,'0')), CONCAT(IF(MOD(n,4)=0,'B-','U-'),100+MOD(n,24)),
  IF(MOD(n,4)=0,'蓝方','红方'), ELT(MOD(n-1,6)+1,'战斗机','无人机','坦克','装甲车','雷达','保障车辆'),
  ELT(MOD(n-1,5)+1,'战斗损伤','机械故障','电子干扰','事故','自然损耗'), MOD(n*7,9), MOD(n*11,18),
  ELT(MOD(n-1,6)+1,'A区域东部','A区域西部','B区域南部','B区域北部','C区域中心','D区域前沿'),
  ROUND(116.1+MOD(n*17,37)/10,6), ROUND(30.2+MOD(n*13,38)/10,6), ROUND(15+MOD(n*29,84),2),
  DATE_SUB(NOW(),INTERVAL n*14 HOUR) FROM tmp_situation_seq WHERE n<=800;

CREATE TABLE IF NOT EXISTS t_command_order (
  order_no VARCHAR(50) PRIMARY KEY, mission_no VARCHAR(50), command_level VARCHAR(50), unit_id VARCHAR(50),
  order_type VARCHAR(50), content_summary VARCHAR(300), issue_time DATETIME, response_time DATETIME,
  execute_status VARCHAR(30), response_minutes INT, region VARCHAR(50), completion_rate DECIMAL(5,2)
);
CALL demo_business.sp_add_situation_column('t_command_order','mission_no','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_command_order','unit_id','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_command_order','order_type','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_command_order','content_summary','VARCHAR(300)');
CALL demo_business.sp_add_situation_column('t_command_order','response_minutes','INT');
CALL demo_business.sp_add_situation_column('t_command_order','region','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_command_order','completion_rate','DECIMAL(5,2)');
DELETE FROM t_command_order WHERE order_no LIKE 'SIM-ORD-%';
INSERT INTO t_command_order
  (order_no,mission_no,command_level,unit_id,order_type,content_summary,issue_time,response_time,execute_status,response_minutes,region,completion_rate)
SELECT CONCAT('SIM-ORD-',LPAD(n,4,'0')),
  CONCAT('SIM-M-',LPAD(MOD(n-1,1000)+1,4,'0')), ELT(MOD(n-1,4)+1,'战区级','集团军级','师级','旅级'),
  CONCAT(IF(MOD(n,5)=0,'B-','U-'),100+MOD(n,24)), ELT(MOD(n-1,5)+1,'任务启动','目标调整','增援命令','保障命令','撤收命令'),
  CONCAT('态势演示指令 ',n), DATE_SUB(NOW(),INTERVAL n*10 HOUR), DATE_SUB(NOW(),INTERVAL (n*10-MOD(n*7,55)) MINUTE),
  ELT(MOD(n-1,4)+1,'已执行','执行中','待确认','受阻'), MOD(n*7,55),
  ELT(MOD(n-1,6)+1,'A区域东部','A区域西部','B区域南部','B区域北部','C区域中心','D区域前沿'),
  ROUND(MOD(n*17,101),2) FROM tmp_situation_seq;

CREATE TABLE IF NOT EXISTS t_equipment (
  equipment_no VARCHAR(50) PRIMARY KEY, unit_id VARCHAR(50), side_name VARCHAR(20), equipment_type VARCHAR(50), model VARCHAR(50),
  total_count INT, available_count INT, faulty_count INT, online_count INT, readiness_rate DECIMAL(5,2),
  region VARCHAR(50), longitude DECIMAL(10,6), latitude DECIMAL(10,6), update_time DATETIME
);
CALL demo_business.sp_add_situation_column('t_equipment','equipment_no','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_equipment','side_name','VARCHAR(20)');
CALL demo_business.sp_add_situation_column('t_equipment','readiness_rate','DECIMAL(5,2)');
CALL demo_business.sp_add_situation_column('t_equipment','region','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_equipment','longitude','DECIMAL(10,6)');
CALL demo_business.sp_add_situation_column('t_equipment','latitude','DECIMAL(10,6)');
CALL demo_business.sp_add_situation_column('t_equipment','update_time','DATETIME');
DELETE FROM t_equipment WHERE equipment_no LIKE 'SIM-EQ-%';
INSERT INTO t_equipment
  (equipment_no,unit_id,side_name,equipment_type,model,total_count,available_count,faulty_count,online_count,readiness_rate,region,longitude,latitude,update_time)
SELECT CONCAT('SIM-EQ-',LPAD(n,4,'0')), CONCAT(IF(MOD(n,4)=0,'B-','U-'),100+MOD(n,24)), IF(MOD(n,4)=0,'蓝方','红方'),
  ELT(MOD(n-1,7)+1,'战斗机','无人机','坦克','装甲车','防空系统','雷达','保障车辆'),
  ELT(MOD(n-1,7)+1,'J-10A','CH-5','ZTZ-99A','ZBL-09','HQ-9','YLC-8B','SX-2300'),
  12+MOD(n*13,90), 8+MOD(n*11,70), MOD(n*7,12), 7+MOD(n*5,68), ROUND(55+MOD(n*19,45),2),
  ELT(MOD(n-1,6)+1,'A区域东部','A区域西部','B区域南部','B区域北部','C区域中心','D区域前沿'),
  ROUND(116+MOD(n*13,38)/10,6), ROUND(30.2+MOD(n*11,38)/10,6), DATE_SUB(NOW(),INTERVAL n*12 HOUR)
FROM tmp_situation_seq;

CREATE TABLE IF NOT EXISTS t_inventory (
  inventory_no VARCHAR(50) PRIMARY KEY, resource_type VARCHAR(50), resource_name VARCHAR(100), stock_count DECIMAL(12,2),
  reserved_count DECIMAL(12,2), inbound_count DECIMAL(12,2), measure_unit VARCHAR(20), alert_level VARCHAR(20),
  warehouse VARCHAR(100), region VARCHAR(50), longitude DECIMAL(10,6), latitude DECIMAL(10,6), support_days DECIMAL(8,2), update_time DATETIME
);
CALL demo_business.sp_add_situation_column('t_inventory','inventory_no','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_inventory','reserved_count','DECIMAL(12,2)');
CALL demo_business.sp_add_situation_column('t_inventory','inbound_count','DECIMAL(12,2)');
CALL demo_business.sp_add_situation_column('t_inventory','measure_unit','VARCHAR(20)');
CALL demo_business.sp_add_situation_column('t_inventory','region','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_inventory','longitude','DECIMAL(10,6)');
CALL demo_business.sp_add_situation_column('t_inventory','latitude','DECIMAL(10,6)');
CALL demo_business.sp_add_situation_column('t_inventory','support_days','DECIMAL(8,2)');
DELETE FROM t_inventory WHERE inventory_no LIKE 'SIM-INV-%';
INSERT INTO t_inventory
  (inventory_no,resource_type,resource_name,stock_count,reserved_count,inbound_count,measure_unit,alert_level,warehouse,region,longitude,latitude,support_days,update_time)
SELECT CONCAT('SIM-INV-',LPAD(n,4,'0')),
  ELT(MOD(n-1,5)+1,'弹药','燃料','备件','物资','医疗'), ELT(MOD(n-1,8)+1,'空空导弹','航空燃油','发动机备件','野战食品','急救药品','通信器材','装甲备件','无人机电池'),
  ROUND(100+MOD(n*97,4900),2), ROUND(MOD(n*31,500),2), ROUND(MOD(n*43,700),2),
  ELT(MOD(n-1,4)+1,'枚','吨','套','箱'), ELT(MOD(n-1,4)+1,'正常','关注','紧缺','充足'),
  CONCAT('仓库-',CHAR(65+MOD(n,12))), ELT(MOD(n-1,6)+1,'A区域东部','A区域西部','B区域南部','B区域北部','C区域中心','D区域前沿'),
  ROUND(116+MOD(n*19,38)/10,6), ROUND(30.2+MOD(n*7,38)/10,6), ROUND(3+MOD(n*17,57),2), DATE_SUB(NOW(),INTERVAL n*8 HOUR)
FROM tmp_situation_seq;

CREATE TABLE IF NOT EXISTS t_warning_event (
  warning_no VARCHAR(50) PRIMARY KEY, target_name VARCHAR(100), target_type VARCHAR(50), warning_level VARCHAR(20),
  advance_minutes INT, detection_source VARCHAR(50), handling_status VARCHAR(30), region VARCHAR(50),
  longitude DECIMAL(10,6), latitude DECIMAL(10,6), warning_time DATETIME, response_time DATETIME, risk_score DECIMAL(5,2)
);
CALL demo_business.sp_add_situation_column('t_warning_event','target_type','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_warning_event','region','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_warning_event','longitude','DECIMAL(10,6)');
CALL demo_business.sp_add_situation_column('t_warning_event','latitude','DECIMAL(10,6)');
CALL demo_business.sp_add_situation_column('t_warning_event','risk_score','DECIMAL(5,2)');
DELETE FROM t_warning_event WHERE warning_no LIKE 'SIM-WAR-%';
INSERT INTO t_warning_event
  (warning_no,target_name,target_type,warning_level,advance_minutes,detection_source,handling_status,region,longitude,latitude,warning_time,response_time,risk_score)
SELECT CONCAT('SIM-WAR-',LPAD(n,4,'0')), CONCAT('SIM预警目标-',LPAD(n,3,'0')),
  ELT(MOD(n-1,6)+1,'航空目标','导弹目标','装甲目标','雷达目标','通信节点','保障车队'),
  ELT(MOD(n-1,4)+1,'极高','高','中','低'), 8+MOD(n*7,53), ELT(MOD(n-1,5)+1,'预警机雷达','地面雷达','电子侦察','无人机','卫星'),
  ELT(MOD(n-1,4)+1,'已处置','已核验','已分发','待处置'), ELT(MOD(n-1,6)+1,'A区域东部','A区域西部','B区域南部','B区域北部','C区域中心','D区域前沿'),
  ROUND(116.1+MOD(n*23,37)/10,6), ROUND(30.3+MOD(n*17,36)/10,6), DATE_SUB(NOW(),INTERVAL n*7 HOUR),
  DATE_SUB(NOW(),INTERVAL (n*7-MOD(n*7,40)) MINUTE), ROUND(30+MOD(n*31,69),2) FROM tmp_situation_seq;

CREATE TABLE IF NOT EXISTS t_maintenance (
  maintenance_no VARCHAR(50) PRIMARY KEY, unit_id VARCHAR(50), equipment_type VARCHAR(50), model VARCHAR(50),
  fault_count INT, repaired_count INT, pending_count INT, spare_part_status VARCHAR(30), recovery_hours DECIMAL(8,2),
  readiness_after DECIMAL(5,2), region VARCHAR(50), record_time DATETIME
);
CALL demo_business.sp_add_situation_column('t_maintenance','readiness_after','DECIMAL(5,2)');
CALL demo_business.sp_add_situation_column('t_maintenance','region','VARCHAR(50)');
DELETE FROM t_maintenance WHERE maintenance_no LIKE 'SIM-MNT-%';
INSERT INTO t_maintenance
  (maintenance_no,unit_id,equipment_type,model,fault_count,repaired_count,pending_count,spare_part_status,recovery_hours,readiness_after,region,record_time)
SELECT CONCAT('SIM-MNT-',LPAD(n,4,'0')), CONCAT(IF(MOD(n,4)=0,'B-','U-'),100+MOD(n,24)),
  ELT(MOD(n-1,7)+1,'战斗机','无人机','坦克','装甲车','防空系统','雷达','保障车辆'),
  ELT(MOD(n-1,7)+1,'J-10A','CH-5','ZTZ-99A','ZBL-09','HQ-9','YLC-8B','SX-2300'),
  1+MOD(n*7,15), MOD(n*5,12), MOD(n*11,8), ELT(MOD(n-1,4)+1,'充足','一般','紧张','缺失'),
  ROUND(MOD(n*13,72),2), ROUND(55+MOD(n*17,45),2),
  ELT(MOD(n-1,6)+1,'A区域东部','A区域西部','B区域南部','B区域北部','C区域中心','D区域前沿'), DATE_SUB(NOW(),INTERVAL n*15 HOUR)
FROM tmp_situation_seq WHERE n<=800;

CREATE TABLE IF NOT EXISTS t_force (
  force_no VARCHAR(50) PRIMARY KEY, unit_id VARCHAR(50), unit_name VARCHAR(100), side_name VARCHAR(20), force_type VARCHAR(50),
  establishment INT, present_count INT, deployable_count INT, readiness_rate DECIMAL(5,2), region VARCHAR(50),
  longitude DECIMAL(10,6), latitude DECIMAL(10,6), update_time DATETIME
);
CALL demo_business.sp_add_situation_column('t_force','force_no','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_force','side_name','VARCHAR(20)');
CALL demo_business.sp_add_situation_column('t_force','readiness_rate','DECIMAL(5,2)');
CALL demo_business.sp_add_situation_column('t_force','region','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_force','longitude','DECIMAL(10,6)');
CALL demo_business.sp_add_situation_column('t_force','latitude','DECIMAL(10,6)');
CALL demo_business.sp_add_situation_column('t_force','update_time','DATETIME');
DELETE FROM t_force WHERE force_no LIKE 'SIM-FOR-%';
INSERT INTO t_force
  (force_no,unit_id,unit_name,side_name,force_type,establishment,present_count,deployable_count,readiness_rate,region,longitude,latitude,update_time)
SELECT CONCAT('SIM-FOR-',LPAD(n,4,'0')), CONCAT(IF(MOD(n,4)=0,'B-','U-'),100+MOD(n,80)),
  CONCAT(ELT(MOD(n-1,6)+1,'航空兵','装甲','防空','侦察','电子对抗','保障'),'单位-',LPAD(n,3,'0')),
  IF(MOD(n,4)=0,'蓝方','红方'), ELT(MOD(n-1,6)+1,'空军','陆军','防空','侦察','电子对抗','保障'),
  400+MOD(n*137,1800), 350+MOD(n*113,1500), 280+MOD(n*97,1300), ROUND(58+MOD(n*23,42),2),
  ELT(MOD(n-1,6)+1,'A区域东部','A区域西部','B区域南部','B区域北部','C区域中心','D区域前沿'),
  ROUND(116+MOD(n*13,38)/10,6), ROUND(30.2+MOD(n*19,38)/10,6), DATE_SUB(NOW(),INTERVAL n*18 HOUR)
FROM tmp_situation_seq;

CREATE TABLE IF NOT EXISTS t_recon_intelligence (
  recon_no VARCHAR(50) PRIMARY KEY, mission_no VARCHAR(50), unit_id VARCHAR(50), target_name VARCHAR(100), target_type VARCHAR(50),
  intelligence_source VARCHAR(50), coverage_rate DECIMAL(5,2), identification_accuracy DECIMAL(5,2), confidence_level VARCHAR(20),
  region VARCHAR(50), longitude DECIMAL(10,6), latitude DECIMAL(10,6), discovered_time DATETIME
);
CALL demo_business.sp_add_situation_column('t_recon_intelligence','target_type','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_recon_intelligence','region','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_recon_intelligence','longitude','DECIMAL(10,6)');
CALL demo_business.sp_add_situation_column('t_recon_intelligence','latitude','DECIMAL(10,6)');
DELETE FROM t_recon_intelligence WHERE recon_no LIKE 'SIM-REC-%';
INSERT INTO t_recon_intelligence
  (recon_no,mission_no,unit_id,target_name,target_type,intelligence_source,coverage_rate,identification_accuracy,confidence_level,region,longitude,latitude,discovered_time)
SELECT CONCAT('SIM-REC-',LPAD(n,4,'0')), CONCAT('SIM-M-',LPAD(MOD(n-1,1000)+1,4,'0')),
  CONCAT('U-',100+MOD(n,24)), CONCAT('SIM侦察目标-',LPAD(n,3,'0')), ELT(MOD(n-1,6)+1,'雷达','机场','装甲群','导弹阵地','通信节点','补给节点'),
  ELT(MOD(n-1,5)+1,'无人机光电','预警机雷达','卫星图像','电子侦察','地面雷达'),
  ROUND(55+MOD(n*17,45),2), ROUND(60+MOD(n*19,40),2), ELT(MOD(n-1,3)+1,'高','中','待核验'),
  ELT(MOD(n-1,6)+1,'A区域东部','A区域西部','B区域南部','B区域北部','C区域中心','D区域前沿'),
  ROUND(116.1+MOD(n*11,37)/10,6), ROUND(30.3+MOD(n*23,36)/10,6), DATE_SUB(NOW(),INTERVAL n*9 HOUR)
FROM tmp_situation_seq;

CREATE TABLE IF NOT EXISTS t_defense (
  defense_no VARCHAR(50) PRIMARY KEY, unit_id VARCHAR(50), side_name VARCHAR(20), region VARCHAR(50), defense_type VARCHAR(50),
  coverage_km DECIMAL(10,2), protection_level VARCHAR(30), interceptor_count INT, available_count INT,
  longitude DECIMAL(10,6), latitude DECIMAL(10,6), defense_score DECIMAL(5,2), status VARCHAR(30), update_time DATETIME
);
CALL demo_business.sp_add_situation_column('t_defense','side_name','VARCHAR(20)');
CALL demo_business.sp_add_situation_column('t_defense','longitude','DECIMAL(10,6)');
CALL demo_business.sp_add_situation_column('t_defense','latitude','DECIMAL(10,6)');
CALL demo_business.sp_add_situation_column('t_defense','defense_score','DECIMAL(5,2)');
CALL demo_business.sp_add_situation_column('t_defense','update_time','DATETIME');
DELETE FROM t_defense WHERE defense_no LIKE 'SIM-DEF-%';
INSERT INTO t_defense
  (defense_no,unit_id,side_name,region,defense_type,coverage_km,protection_level,interceptor_count,available_count,longitude,latitude,defense_score,status,update_time)
SELECT CONCAT('SIM-DEF-',LPAD(n,4,'0')), CONCAT(IF(MOD(n,4)=0,'B-','U-'),100+MOD(n,24)), IF(MOD(n,4)=0,'蓝方','红方'),
  ELT(MOD(n-1,6)+1,'A区域东部','A区域西部','B区域南部','B区域北部','C区域中心','D区域前沿'),
  ELT(MOD(n-1,5)+1,'远程防空','中程防空','野战防护','要地防护','电子防护'), ROUND(20+MOD(n*17,230),2),
  ELT(MOD(n-1,3)+1,'一级','二级','三级'), 20+MOD(n*13,90), 15+MOD(n*11,80),
  ROUND(116+MOD(n*17,38)/10,6), ROUND(30.2+MOD(n*13,38)/10,6), ROUND(50+MOD(n*29,50),2),
  ELT(MOD(n-1,4)+1,'战备','机动中','维护','加强'), DATE_SUB(NOW(),INTERVAL n*16 HOUR)
FROM tmp_situation_seq WHERE n<=750;

CREATE TABLE IF NOT EXISTS t_unit_master (
  unit_id VARCHAR(50) PRIMARY KEY, unit_name VARCHAR(100), parent_unit VARCHAR(100), side_name VARCHAR(20), force_type VARCHAR(50),
  region VARCHAR(50), establishment INT, longitude DECIMAL(10,6), latitude DECIMAL(10,6), command_score DECIMAL(5,2), status VARCHAR(30)
);
CALL demo_business.sp_add_situation_column('t_unit_master','side_name','VARCHAR(20)');
CALL demo_business.sp_add_situation_column('t_unit_master','longitude','DECIMAL(10,6)');
CALL demo_business.sp_add_situation_column('t_unit_master','latitude','DECIMAL(10,6)');
CALL demo_business.sp_add_situation_column('t_unit_master','command_score','DECIMAL(5,2)');
DELETE FROM t_unit_master WHERE unit_id LIKE 'SIM-U-%';
INSERT INTO t_unit_master
  (unit_id,unit_name,parent_unit,side_name,force_type,region,establishment,longitude,latitude,command_score,status)
SELECT CONCAT('SIM-U-',LPAD(n,4,'0')), CONCAT('演示',ELT(MOD(n-1,6)+1,'航空兵旅','装甲旅','防空旅','侦察大队','电子对抗团','保障团'),'-',n),
  ELT(MOD(n-1,4)+1,'战区指挥部','空军指挥部','陆军指挥部','联合保障部'), IF(MOD(n,4)=0,'蓝方','红方'),
  ELT(MOD(n-1,6)+1,'空军','陆军','防空','侦察','电子对抗','保障'), ELT(MOD(n-1,6)+1,'A区域东部','A区域西部','B区域南部','B区域北部','C区域中心','D区域前沿'),
  400+MOD(n*127,1800), ROUND(116+MOD(n*19,38)/10,6), ROUND(30.2+MOD(n*11,38)/10,6), ROUND(55+MOD(n*17,45),2),
  ELT(MOD(n-1,3)+1,'现役','机动','休整') FROM tmp_situation_seq WHERE n<=600;

CREATE TABLE IF NOT EXISTS t_weapon (
  weapon_no VARCHAR(50) PRIMARY KEY, weapon_name VARCHAR(100), weapon_type VARCHAR(50), model VARCHAR(50), unit_id VARCHAR(50),
  side_name VARCHAR(20), total_count INT, available_count INT, range_km DECIMAL(10,2), accuracy_rate DECIMAL(5,2),
  readiness_rate DECIMAL(5,2), region VARCHAR(50), status VARCHAR(30), update_time DATETIME
);
CALL demo_business.sp_add_situation_column('t_weapon','weapon_no','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_weapon','side_name','VARCHAR(20)');
CALL demo_business.sp_add_situation_column('t_weapon','available_count','INT');
CALL demo_business.sp_add_situation_column('t_weapon','accuracy_rate','DECIMAL(5,2)');
CALL demo_business.sp_add_situation_column('t_weapon','readiness_rate','DECIMAL(5,2)');
CALL demo_business.sp_add_situation_column('t_weapon','region','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_weapon','update_time','DATETIME');
DELETE FROM t_weapon WHERE weapon_no LIKE 'SIM-WPN-%';
INSERT INTO t_weapon
  (weapon_no,weapon_name,weapon_type,model,unit_id,side_name,total_count,available_count,range_km,accuracy_rate,readiness_rate,region,status,update_time)
SELECT CONCAT('SIM-WPN-',LPAD(n,4,'0')), CONCAT('演示武器-',LPAD(n,3,'0')),
  ELT(MOD(n-1,7)+1,'战斗机','直升机','无人机','防空武器','火箭炮','反装甲武器','电子战装备'),
  ELT(MOD(n-1,7)+1,'J-10A','WZ-10','CH-5','HQ-9','PHL-16','HJ-12','EW-2026'), CONCAT(IF(MOD(n,4)=0,'B-','U-'),100+MOD(n,24)), IF(MOD(n,4)=0,'蓝方','红方'),
  6+MOD(n*11,70), 4+MOD(n*7,60), ROUND(40+MOD(n*31,2960),2), ROUND(55+MOD(n*23,45),2), ROUND(50+MOD(n*19,50),2),
  ELT(MOD(n-1,6)+1,'A区域东部','A区域西部','B区域南部','B区域北部','C区域中心','D区域前沿'),
  ELT(MOD(n-1,4)+1,'可用','部分可用','维护','部署中'), DATE_SUB(NOW(),INTERVAL n*17 HOUR) FROM tmp_situation_seq WHERE n<=800;

CREATE TABLE IF NOT EXISTS t_air_capability (
  capability_no VARCHAR(50) PRIMARY KEY, unit_id VARCHAR(50), side_name VARCHAR(20), capability_type VARCHAR(50), score DECIMAL(5,2),
  weight_value DECIMAL(5,2), sorties_available INT, mission_success_rate DECIMAL(5,2), region VARCHAR(50), eval_date DATE
);
CALL demo_business.sp_add_situation_column('t_air_capability','capability_no','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_air_capability','side_name','VARCHAR(20)');
CALL demo_business.sp_add_situation_column('t_air_capability','weight_value','DECIMAL(5,2)');
CALL demo_business.sp_add_situation_column('t_air_capability','sorties_available','INT');
CALL demo_business.sp_add_situation_column('t_air_capability','mission_success_rate','DECIMAL(5,2)');
CALL demo_business.sp_add_situation_column('t_air_capability','region','VARCHAR(50)');
DELETE FROM t_air_capability WHERE capability_no LIKE 'SIM-AC-%';
INSERT INTO t_air_capability
  (capability_no,unit_id,side_name,capability_type,score,weight_value,sorties_available,mission_success_rate,region,eval_date)
SELECT CONCAT('SIM-AC-',LPAD(n,4,'0')), CONCAT(IF(MOD(n,4)=0,'B-','U-'),100+MOD(n,24)), IF(MOD(n,4)=0,'蓝方','红方'),
  ELT(MOD(n-1,6)+1,'制空能力','打击能力','侦察能力','预警能力','电子对抗','持续保障'), ROUND(50+MOD(n*23,50),2),
  ROUND(0.1+MOD(n*7,20)/100,2), 5+MOD(n*11,48), ROUND(55+MOD(n*17,45),2),
  ELT(MOD(n-1,6)+1,'A区域东部','A区域西部','B区域南部','B区域北部','C区域中心','D区域前沿'), DATE_SUB(CURDATE(),INTERVAL MOD(n,180) DAY)
FROM tmp_situation_seq;

CREATE TABLE IF NOT EXISTS t_air_overall (
  eval_no VARCHAR(50) PRIMARY KEY, side_name VARCHAR(20), unit_id VARCHAR(50), region VARCHAR(50), overall_score DECIMAL(5,2),
  air_control_level VARCHAR(30), available_sorties INT, threat_pressure DECIMAL(5,2), longitude DECIMAL(10,6), latitude DECIMAL(10,6), eval_date DATE
);
CALL demo_business.sp_add_situation_column('t_air_overall','region','VARCHAR(50)');
CALL demo_business.sp_add_situation_column('t_air_overall','available_sorties','INT');
CALL demo_business.sp_add_situation_column('t_air_overall','threat_pressure','DECIMAL(5,2)');
CALL demo_business.sp_add_situation_column('t_air_overall','longitude','DECIMAL(10,6)');
CALL demo_business.sp_add_situation_column('t_air_overall','latitude','DECIMAL(10,6)');
DELETE FROM t_air_overall WHERE eval_no LIKE 'SIM-AIR-%';
INSERT INTO t_air_overall
  (eval_no,side_name,unit_id,region,overall_score,air_control_level,available_sorties,threat_pressure,longitude,latitude,eval_date)
SELECT CONCAT('SIM-AIR-',LPAD(n,4,'0')), IF(MOD(n,4)=0,'蓝方','红方'), CONCAT(IF(MOD(n,4)=0,'B-','U-'),100+MOD(n,24)),
  ELT(MOD(n-1,6)+1,'A区域东部','A区域西部','B区域南部','B区域北部','C区域中心','D区域前沿'), ROUND(48+MOD(n*29,52),2),
  ELT(MOD(n-1,4)+1,'区域优势','局部优势','局部均势','局部劣势'), 8+MOD(n*13,60), ROUND(25+MOD(n*31,74),2),
  ROUND(116+MOD(n*7,38)/10,6), ROUND(30.2+MOD(n*19,38)/10,6), DATE_SUB(CURDATE(),INTERVAL MOD(n,180) DAY)
FROM tmp_situation_seq WHERE n<=750;

DELETE FROM t_threat WHERE target_name LIKE 'SIM-%';
INSERT INTO t_threat (
  target_name, target_type, threat_level, location, status, detect_time,
  region, longitude, latitude, confidence_score, risk_score
)
SELECT
  CONCAT('SIM-', ELT(MOD(n - 1, 7) + 1, '机动雷达', '装甲纵队', '战术导弹', '无人机群', '前沿机场', '通信节点', '补给车队'), '-', LPAD(n, 4, '0')),
  ELT(MOD(n - 1, 7) + 1, '雷达设施', '装甲目标', '导弹阵地', '空中目标', '机场', '指挥通信', '后勤目标'),
  ELT(MOD(n - 1, 5) + 1, '高', '中', '低', '极高', '中'),
  CONCAT('经度', ROUND(116.20 + MOD(n * 19, 35) / 10, 4), ' 纬度', ROUND(30.50 + MOD(n * 13, 32) / 10, 4)),
  ELT(MOD(n - 1, 5) + 1, '活跃', '移动中', '待确认', '静默', '已跟踪'),
  DATE_SUB(NOW(), INTERVAL (n * 10) HOUR),
  ELT(MOD(n - 1, 6) + 1, 'A区域东部', 'A区域西部', 'B区域南部', 'B区域北部', 'C区域中心', 'D区域前沿'),
  ROUND(116.20 + MOD(n * 19, 35) / 10, 6),
  ROUND(30.50 + MOD(n * 13, 32) / 10, 6),
  ROUND(62 + MOD(n * 29, 37), 2),
  ROUND(35 + MOD(n * 31, 64), 2)
FROM tmp_situation_seq;

DELETE FROM t_supply WHERE plan_no LIKE 'SIM-P-%';
INSERT INTO t_supply (
  plan_no, resource_type, resource_name, planned_count, delivered_count,
  progress, status, transport_ability, region, longitude, latitude,
  planned_time, delivered_time, risk_level, support_score
)
SELECT
  CONCAT('SIM-P-', LPAD(n, 4, '0')),
  ELT(MOD(n - 1, 5) + 1, '弹药', '燃料', '备件', '食品', '医疗'),
  ELT(MOD(n - 1, 7) + 1, '精确制导弹药', '航空燃油', '发动机备件', '野战食品', '急救药品', '通信器材', '装甲车辆备件'),
  80 + MOD(n * 47, 620),
  ROUND((80 + MOD(n * 47, 620)) * (45 + MOD(n * 13, 56)) / 100, 2),
  45 + MOD(n * 13, 56),
  ELT(MOD(n - 1, 4) + 1, '进行中', '已完成', '延迟', '待装运'),
  ELT(MOD(n - 1, 4) + 1, '空运 40 吨/日', '铁路 220 吨/日', '公路 60 吨/日', '综合运输 100 吨/日'),
  ELT(MOD(n - 1, 6) + 1, 'A区域东部', 'A区域西部', 'B区域南部', 'B区域北部', 'C区域中心', 'D区域前沿'),
  ROUND(116.00 + MOD(n * 11, 38) / 10, 6),
  ROUND(30.20 + MOD(n * 17, 38) / 10, 6),
  DATE_SUB(NOW(), INTERVAL (n * 16) HOUR),
  CASE WHEN MOD(n - 1, 4) = 1 THEN DATE_SUB(NOW(), INTERVAL (n * 16 - 5) HOUR) ELSE NULL END,
  ELT(MOD(n - 1, 4) + 1, '中', '低', '高', '中'),
  ROUND(45 + MOD(n * 17, 54), 2)
FROM tmp_situation_seq;

DROP PROCEDURE demo_business.sp_add_situation_column;

-- 注册缺失的数据集；已有数据集只更新 ACL、字段白名单和记录数。
SET @demo_db_id = (
  SELECT id FROM assessment.ass_database_config
  WHERE db_name = 'demo_business' ORDER BY create_time LIMIT 1
);

INSERT INTO assessment.ass_dataset
  (id, name, description, database_id, table_name, sql_text, records, create_time, update_time)
SELECT 'ds_sit_deployment', '兵力部署态势表', '区域、对抗方、兵种、战力与战备状态', @demo_db_id,
       't_deployment', '', (SELECT COUNT(*) FROM demo_business.t_deployment), NOW(), NOW()
WHERE NOT EXISTS (SELECT 1 FROM assessment.ass_dataset WHERE table_name = 't_deployment');

INSERT INTO assessment.ass_dataset
  (id, name, description, database_id, table_name, sql_text, records, create_time, update_time)
SELECT 'ds_sit_mission', '作战任务记录表', '近30天任务、状态、区域、完成率和风险评分', @demo_db_id,
       't_mission', '', (SELECT COUNT(*) FROM demo_business.t_mission), NOW(), NOW()
WHERE NOT EXISTS (SELECT 1 FROM assessment.ass_dataset WHERE table_name = 't_mission');

INSERT INTO assessment.ass_dataset
  (id, name, description, database_id, table_name, sql_text, records, create_time, update_time)
SELECT 'ds_sit_threat', '威胁目标登记表', '威胁等级、活动状态、区域、坐标与置信度', @demo_db_id,
       't_threat', '', (SELECT COUNT(*) FROM demo_business.t_threat), NOW(), NOW()
WHERE NOT EXISTS (SELECT 1 FROM assessment.ass_dataset WHERE table_name = 't_threat');

INSERT INTO assessment.ass_dataset
  (id, name, description, database_id, table_name, sql_text, records, create_time, update_time)
SELECT 'ds_sit_supply', '补给保障进度表', '保障区域、到货进度、风险与保障评分', @demo_db_id,
       't_supply', '', (SELECT COUNT(*) FROM demo_business.t_supply), NOW(), NOW()
WHERE NOT EXISTS (SELECT 1 FROM assessment.ass_dataset WHERE table_name = 't_supply');

-- 统一注册全部物理数据集。通过临时目录表生成，便于以后继续扩展。
DROP TEMPORARY TABLE IF EXISTS tmp_situation_catalog;
CREATE TEMPORARY TABLE tmp_situation_catalog (
  table_name VARCHAR(64) PRIMARY KEY, dataset_name VARCHAR(100), description_text VARCHAR(300), allowed_columns_text TEXT
);
INSERT INTO tmp_situation_catalog VALUES
('t_deployment','兵力部署态势','区域、对抗方、兵种、战力与战备状态','deployment_no,side_name,unit_id,force_type,region,personnel_count,equipment_count,readiness_status,update_time,longitude,latitude,combat_power,mobility_score'),
('t_mission','作战任务记录','任务、状态、区域、完成率和风险评分','mission_no,mission_name,mission_type,target_name,unit_id,sorties,status,start_time,end_time,region,side_name,longitude,latitude,completion_rate,risk_score'),
('t_threat','威胁目标登记','威胁等级、活动状态、区域、坐标与置信度','target_name,target_type,threat_level,location,status,detect_time,region,longitude,latitude,confidence_score,risk_score'),
('t_supply','补给保障进度','到货进度、风险、路线与保障评分','plan_no,resource_type,resource_name,planned_count,delivered_count,progress,status,transport_ability,region,longitude,latitude,planned_time,delivered_time,risk_level,support_score'),
('t_resource_consume','任务资源消耗','任务级弹药、燃料、备件和物资消耗','consume_no,mission_no,unit_id,resource_type,resource_name,consume_count,measure_unit,region,consume_time,longitude,latitude,cost_score'),
('t_combat_result','作战效果记录','命中、毁伤、任务达成率和空间效果','result_no,mission_no,unit_id,weapon_type,target_type,target_name,hit_count,destroyed_count,success_rate,target_achieved,region,longitude,latitude,record_time'),
('t_combat_loss','战损事件记录','装备损失、人员伤亡、区域和战备影响','loss_no,mission_no,unit_id,side_name,equipment_type,loss_type,loss_count,casualty_count,region,longitude,latitude,impact_score,loss_time'),
('t_command_order','指挥指令响应','指令层级、响应时延和执行完成率','order_no,mission_no,command_level,unit_id,order_type,content_summary,issue_time,response_time,execute_status,response_minutes,region,completion_rate'),
('t_equipment','装备健康状态','装备数量、完好、故障、在位和战备率','equipment_no,unit_id,side_name,equipment_type,model,total_count,available_count,faulty_count,online_count,readiness_rate,region,longitude,latitude,update_time'),
('t_inventory','保障库存台账','现有、预留、在途库存和可支撑天数','inventory_no,resource_type,resource_name,stock_count,reserved_count,inbound_count,measure_unit,alert_level,warehouse,region,longitude,latitude,support_days,update_time'),
('t_warning_event','威胁预警事件','预警等级、提前量、处置状态和风险评分','warning_no,target_name,target_type,warning_level,advance_minutes,detection_source,handling_status,region,longitude,latitude,warning_time,response_time,risk_score'),
('t_maintenance','装备维修保障','故障、修复、备件、恢复时长和恢复后完好率','maintenance_no,unit_id,equipment_type,model,fault_count,repaired_count,pending_count,spare_part_status,recovery_hours,readiness_after,region,record_time'),
('t_force','兵力实力台账','编制、实有、可部署、战备率和空间分布','force_no,unit_id,unit_name,side_name,force_type,establishment,present_count,deployable_count,readiness_rate,region,longitude,latitude,update_time'),
('t_recon_intelligence','侦察情报记录','侦察覆盖、识别准确率、可信度和目标位置','recon_no,mission_no,unit_id,target_name,target_type,intelligence_source,coverage_rate,identification_accuracy,confidence_level,region,longitude,latitude,discovered_time'),
('t_defense','防御配置态势','防护类型、覆盖半径、可用拦截数量和防御评分','defense_no,unit_id,side_name,region,defense_type,coverage_km,protection_level,interceptor_count,available_count,longitude,latitude,defense_score,status,update_time'),
('t_unit_master','单位主数据','单位隶属、军兵种、区域、编制和指挥评分','unit_id,unit_name,parent_unit,side_name,force_type,region,establishment,longitude,latitude,command_score,status'),
('t_weapon','武器效能台账','武器型号、数量、射程、精度和战备率','weapon_no,weapon_name,weapon_type,model,unit_id,side_name,total_count,available_count,range_km,accuracy_rate,readiness_rate,region,status,update_time'),
('t_air_capability','空中能力分项','制空、打击、侦察、预警和保障能力','capability_no,unit_id,side_name,capability_type,score,weight_value,sorties_available,mission_success_rate,region,eval_date'),
('t_air_overall','制空能力综合','制空等级、可用架次、威胁压力和空间分布','eval_no,side_name,unit_id,region,overall_score,air_control_level,available_sorties,threat_pressure,longitude,latitude,eval_date');

INSERT INTO assessment.ass_dataset
  (id,name,description,database_id,table_name,sql_text,allowed_user_ids,allowed_team_ids,allowed_columns,sensitive_columns,schema_version,records,create_time,update_time)
SELECT CONCAT('ds_sit_',SUBSTRING(MD5(c.table_name),1,16)), c.dataset_name, c.description_text,
  @demo_db_id,c.table_name,'','local-user','',c.allowed_columns_text,'',3,0,NOW(),NOW()
FROM tmp_situation_catalog c
WHERE NOT EXISTS (SELECT 1 FROM assessment.ass_dataset d WHERE d.table_name=c.table_name AND d.database_id=@demo_db_id);

UPDATE assessment.ass_dataset d JOIN tmp_situation_catalog c ON c.table_name=d.table_name
SET d.allowed_user_ids='local-user', d.allowed_team_ids='', d.allowed_columns=c.allowed_columns_text,
    d.sensitive_columns='', d.schema_version=3, d.update_time=NOW()
WHERE d.database_id=@demo_db_id;

-- records 使用动态 SQL 刷新，避免维护 19 份重复 UPDATE。
DELIMITER $$
DROP PROCEDURE IF EXISTS demo_business.sp_refresh_situation_records$$
CREATE PROCEDURE demo_business.sp_refresh_situation_records()
BEGIN
  DECLARE done INT DEFAULT 0;
  DECLARE current_table VARCHAR(64);
  DECLARE catalog_cursor CURSOR FOR SELECT table_name FROM tmp_situation_catalog;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET done=1;
  OPEN catalog_cursor;
  refresh_loop: LOOP
    FETCH catalog_cursor INTO current_table;
    IF done=1 THEN LEAVE refresh_loop; END IF;
    SET @count_sql=CONCAT('SELECT COUNT(*) INTO @row_count FROM demo_business.`',current_table,'`');
    PREPARE count_statement FROM @count_sql; EXECUTE count_statement; DEALLOCATE PREPARE count_statement;
    UPDATE assessment.ass_dataset SET records=@row_count,update_time=NOW()
      WHERE table_name=current_table AND database_id=@demo_db_id;
  END LOOP;
  CLOSE catalog_cursor;
END$$
DELIMITER ;
CALL demo_business.sp_refresh_situation_records();
DROP PROCEDURE demo_business.sp_refresh_situation_records;

UPDATE assessment.ass_dataset SET
  allowed_user_ids = 'local-user', allowed_team_ids = '', sensitive_columns = '',
  allowed_columns = 'deployment_no,side_name,unit_id,force_type,region,personnel_count,equipment_count,readiness_status,update_time,longitude,latitude,combat_power,mobility_score',
  records = (SELECT COUNT(*) FROM demo_business.t_deployment), schema_version = 3, update_time = NOW()
WHERE table_name = 't_deployment' AND database_id = @demo_db_id;

UPDATE assessment.ass_dataset SET
  allowed_user_ids = 'local-user', allowed_team_ids = '', sensitive_columns = '',
  allowed_columns = 'mission_no,mission_name,mission_type,target_name,unit_id,sorties,status,start_time,end_time,region,side_name,longitude,latitude,completion_rate,risk_score',
  records = (SELECT COUNT(*) FROM demo_business.t_mission), schema_version = 3, update_time = NOW()
WHERE table_name = 't_mission' AND database_id = @demo_db_id;

UPDATE assessment.ass_dataset SET
  allowed_user_ids = 'local-user', allowed_team_ids = '', sensitive_columns = '',
  allowed_columns = 'target_name,target_type,threat_level,location,status,detect_time,region,longitude,latitude,confidence_score,risk_score',
  records = (SELECT COUNT(*) FROM demo_business.t_threat), schema_version = 3, update_time = NOW()
WHERE table_name = 't_threat' AND database_id = @demo_db_id;

UPDATE assessment.ass_dataset SET
  allowed_user_ids = 'local-user', allowed_team_ids = '', sensitive_columns = '',
  allowed_columns = 'plan_no,resource_type,resource_name,planned_count,delivered_count,progress,status,transport_ability,region,longitude,latitude,planned_time,delivered_time,risk_level,support_score',
  records = (SELECT COUNT(*) FROM demo_business.t_supply), schema_version = 3, update_time = NOW()
WHERE table_name = 't_supply' AND database_id = @demo_db_id;

SELECT 't_deployment' AS table_name, COUNT(*) AS records FROM t_deployment
UNION ALL SELECT 't_mission', COUNT(*) FROM t_mission
UNION ALL SELECT 't_threat', COUNT(*) FROM t_threat
UNION ALL SELECT 't_supply', COUNT(*) FROM t_supply
UNION ALL SELECT 't_resource_consume',COUNT(*) FROM t_resource_consume
UNION ALL SELECT 't_combat_result',COUNT(*) FROM t_combat_result
UNION ALL SELECT 't_combat_loss',COUNT(*) FROM t_combat_loss
UNION ALL SELECT 't_command_order',COUNT(*) FROM t_command_order
UNION ALL SELECT 't_equipment',COUNT(*) FROM t_equipment
UNION ALL SELECT 't_inventory',COUNT(*) FROM t_inventory
UNION ALL SELECT 't_warning_event',COUNT(*) FROM t_warning_event
UNION ALL SELECT 't_maintenance',COUNT(*) FROM t_maintenance
UNION ALL SELECT 't_force',COUNT(*) FROM t_force
UNION ALL SELECT 't_recon_intelligence',COUNT(*) FROM t_recon_intelligence
UNION ALL SELECT 't_defense',COUNT(*) FROM t_defense
UNION ALL SELECT 't_unit_master',COUNT(*) FROM t_unit_master
UNION ALL SELECT 't_weapon',COUNT(*) FROM t_weapon
UNION ALL SELECT 't_air_capability',COUNT(*) FROM t_air_capability
UNION ALL SELECT 't_air_overall',COUNT(*) FROM t_air_overall;
