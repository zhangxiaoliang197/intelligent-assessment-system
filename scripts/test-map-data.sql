-- ============================================================
-- 地图标注能力测试数据
-- 用途：评估分析中验证 AI 理解数据并生成 map_annotations 的能力
-- 用法：mysql -u root -p < scripts/test-map-data.sql
-- ============================================================

CREATE DATABASE IF NOT EXISTS `test_data`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `test_data`;

-- ============================================================
-- 1. 雷达信息表（对应 map_marker.md 标点 + map_area.md 圆形范围）
-- ============================================================
DROP TABLE IF EXISTS `test_radar`;

CREATE TABLE `test_radar` (
    `id`           INT           NOT NULL AUTO_INCREMENT,
    `name`         VARCHAR(50)   NOT NULL COMMENT '雷达名称',
    `lng`          DOUBLE        NOT NULL COMMENT '经度',
    `lat`          DOUBLE        NOT NULL COMMENT '纬度',
    `radius_km`    DOUBLE        NOT NULL COMMENT '覆盖半径（公里）',
    `radar_type`   VARCHAR(20)   NOT NULL COMMENT '雷达类型：预警雷达/火控雷达/搜索雷达/警戒雷达',
    `status`       VARCHAR(10)   NOT NULL DEFAULT '运行' COMMENT '状态：运行/维护/关机',
    `install_date` DATE          DEFAULT NULL COMMENT '安装日期',
    `description`  VARCHAR(200)  DEFAULT NULL COMMENT '描述',
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='雷达信息测试表';

INSERT INTO `test_radar` (`name`, `lng`, `lat`, `radius_km`, `radar_type`, `status`, `install_date`, `description`) VALUES
('东部预警雷达站',   121.50, 31.20, 350, '预警雷达', '运行', '2024-03-15', '覆盖东海区域，对海空目标预警'),
('南部搜索雷达站',   113.50, 22.80, 280, '搜索雷达', '运行', '2024-06-01', '覆盖南海北部，搜索低空小型目标'),
('西部警戒雷达站',   103.80, 36.50, 400, '警戒雷达', '运行', '2024-01-20', '覆盖西部边境，大面积空域警戒'),
('北部防空雷达站',   126.60, 45.70, 300, '火控雷达', '运行', '2024-04-10', '覆盖东北方向，防空火力引导'),
('中部指挥雷达站',   114.30, 34.80, 500, '预警雷达', '运行', '2024-02-28', '覆盖中部战区，综合指挥调度'),
('舟山群岛雷达站',   122.10, 29.90, 200, '搜索雷达', '运行', '2024-07-05', '覆盖舟山至东海方向，海岛搜索'),
('青藏高原雷达站',   91.00, 29.60, 450, '警戒雷达', '运行', '2024-05-12', '高原边境警戒，覆盖西部高海拔空域'),
('渤海湾雷达站',     119.20, 38.90, 250, '预警雷达', '运行', '2024-03-28', '覆盖渤海湾及黄海北部');


-- ============================================================
-- 2. 飞机轨迹信息表（对应 map_route.md 连线 + map_marker.md 标点）
-- ============================================================
DROP TABLE IF EXISTS `test_aircraft_trajectory`;

CREATE TABLE `test_aircraft_trajectory` (
    `id`             INT           NOT NULL AUTO_INCREMENT,
    `aircraft_id`    VARCHAR(10)   NOT NULL COMMENT '飞机编号',
    `aircraft_name`  VARCHAR(30)   NOT NULL COMMENT '飞机名称/呼号',
    `aircraft_type`  VARCHAR(20)   NOT NULL COMMENT '机型：歼-20/歼-16/运-20/空警-500/轰-6K/歼-10',
    `seq`            INT           NOT NULL COMMENT '轨迹序号（从1开始）',
    `lng`            DOUBLE        NOT NULL COMMENT '经度',
    `lat`            DOUBLE        NOT NULL COMMENT '纬度',
    `altitude`       INT           DEFAULT NULL COMMENT '飞行高度（米）',
    `speed`          DOUBLE        DEFAULT NULL COMMENT '飞行速度（公里/小时）',
    `heading`        INT           DEFAULT NULL COMMENT '航向角（度，0=北，90=东）',
    `record_time`    DATETIME      NOT NULL COMMENT '记录时间',
    `fuel_remaining` DOUBLE        DEFAULT NULL COMMENT '剩余燃油百分比',
    `status`         VARCHAR(20)   DEFAULT '巡航' COMMENT '飞行状态：起飞/爬升/巡航/机动/降落',
    `mission_type`   VARCHAR(30)   NOT NULL DEFAULT '训练' COMMENT '任务类型：预警巡逻/战略运输/制空巡航/边境警戒/物资投送/远程打击/空中拦截',
    `coverage_radius_km` DOUBLE    DEFAULT NULL COMMENT '任务覆盖范围（公里），NULL 表示无覆盖范围',
    `distance_km`    DOUBLE        NOT NULL DEFAULT 0 COMMENT '累计飞行距离（公里），从起飞点累加',
    `payload_kg`     DOUBLE        DEFAULT NULL COMMENT '载重（公斤），运输/轰炸机有载重，战斗机为 NULL',
    `flight_duration_min` INT      NOT NULL DEFAULT 0 COMMENT '从起飞到该轨迹点的累计飞行时长（分钟）',
    `fuel_burn_rate` DOUBLE        DEFAULT NULL COMMENT '油耗率（%每小时），用于续航与油耗效率分析',
    PRIMARY KEY (`id`),
    INDEX `idx_aircraft` (`aircraft_id`),
    INDEX `idx_record_time` (`record_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='飞机轨迹测试表';

-- ════════════════════════════════════════════════════════════
-- 5条航线覆盖全国六大区域（东北、华北、华东、西北、西南、华南）
-- 所有坐标均基于真实城市/机场经纬度，确保在陆地上
-- ════════════════════════════════════════════════════════════

-- 航线1：空警-500 哈尔滨→广州（东北→华南，10个轨迹点）
-- 途经：长春→沈阳→锦州→天津→济南→郑州→武汉→长沙→广州
INSERT INTO `test_aircraft_trajectory` (`aircraft_id`, `aircraft_name`, `aircraft_type`, `seq`, `lng`, `lat`, `altitude`, `speed`, `heading`, `record_time`, `fuel_remaining`, `status`, `mission_type`, `coverage_radius_km`) VALUES
('KJ500-01', '空警-01', '空警-500',  1, 126.64, 45.75,    0,    0, 200, '2025-08-10 07:00:00', 100, '起飞', '预警巡逻', 450),
('KJ500-01', '空警-01', '空警-500',  2, 125.32, 43.90, 3500,  380, 210, '2025-08-10 07:25:00',  96, '爬升', '预警巡逻', 450),
('KJ500-01', '空警-01', '空警-500',  3, 123.43, 41.80, 7000,  520, 215, '2025-08-10 07:55:00',  89, '爬升', '预警巡逻', 450),
('KJ500-01', '空警-01', '空警-500',  4, 121.50, 41.00, 8000,  600, 235, '2025-08-10 08:20:00',  82, '巡航', '预警巡逻', 450),
('KJ500-01', '空警-01', '空警-500',  5, 117.20, 39.13, 8000,  620, 230, '2025-08-10 09:00:00',  72, '巡航', '预警巡逻', 450),
('KJ500-01', '空警-01', '空警-500',  6, 117.00, 36.67, 8000,  620, 205, '2025-08-10 09:35:00',  63, '巡航', '预警巡逻', 450),
('KJ500-01', '空警-01', '空警-500',  7, 113.65, 34.76, 8000,  610, 215, '2025-08-10 10:15:00',  52, '巡航', '预警巡逻', 450),
('KJ500-01', '空警-01', '空警-500',  8, 114.30, 30.59, 8000,  600, 188, '2025-08-10 11:05:00',  39, '巡航', '预警巡逻', 450),
('KJ500-01', '空警-01', '空警-500',  9, 112.97, 28.20, 5500,  500, 200, '2025-08-10 11:45:00',  29, '下降', '预警巡逻', 450),
('KJ500-01', '空警-01', '空警-500', 10, 113.27, 23.13,    0,    0, 190, '2025-08-10 12:30:00',  15, '降落', '预警巡逻', 450);

-- 航线2：运-20 上海→乌鲁木齐（华东→西北，10个轨迹点）
-- 途经：南京→合肥→郑州→西安→兰州→酒泉→哈密→吐鲁番→乌鲁木齐
INSERT INTO `test_aircraft_trajectory` (`aircraft_id`, `aircraft_name`, `aircraft_type`, `seq`, `lng`, `lat`, `altitude`, `speed`, `heading`, `record_time`, `fuel_remaining`, `status`, `mission_type`, `coverage_radius_km`) VALUES
('Y20-001', '鲲鹏-01', '运-20',  1, 121.47, 31.23,    0,    0, 290, '2025-08-10 08:00:00', 100, '起飞', '战略运输', NULL),
('Y20-001', '鲲鹏-01', '运-20',  2, 118.78, 32.06, 3500,  400, 300, '2025-08-10 08:25:00',  94, '爬升', '战略运输', NULL),
('Y20-001', '鲲鹏-01', '运-20',  3, 117.28, 31.86, 7000,  550, 295, '2025-08-10 08:45:00',  87, '爬升', '战略运输', NULL),
('Y20-001', '鲲鹏-01', '运-20',  4, 113.65, 34.76, 9000,  700, 310, '2025-08-10 09:25:00',  74, '巡航', '战略运输', NULL),
('Y20-001', '鲲鹏-01', '运-20',  5, 108.95, 34.27, 9000,  720, 300, '2025-08-10 10:05:00',  60, '巡航', '战略运输', NULL),
('Y20-001', '鲲鹏-01', '运-20',  6, 103.83, 36.06, 9000,  730, 305, '2025-08-10 10:55:00',  46, '巡航', '战略运输', NULL),
('Y20-001', '鲲鹏-01', '运-20',  7,  98.50, 39.70, 9000,  720, 320, '2025-08-10 11:45:00',  33, '巡航', '战略运输', NULL),
('Y20-001', '鲲鹏-01', '运-20',  8,  93.50, 42.80, 9000,  710, 325, '2025-08-10 12:25:00',  22, '巡航', '战略运输', NULL),
('Y20-001', '鲲鹏-01', '运-20',  9,  89.20, 42.90, 5500,  550, 310, '2025-08-10 13:00:00',  15, '下降', '战略运输', NULL),
('Y20-001', '鲲鹏-01', '运-20', 10,  87.62, 43.82,    0,    0, 290, '2025-08-10 13:30:00',  12, '降落', '战略运输', NULL);

-- 航线3：歼-20 北京→昆明（华北→西南，8个轨迹点）
-- 途经：保定→太原→西安→汉中→成都→宜宾→昆明
INSERT INTO `test_aircraft_trajectory` (`aircraft_id`, `aircraft_name`, `aircraft_type`, `seq`, `lng`, `lat`, `altitude`, `speed`, `heading`, `record_time`, `fuel_remaining`, `status`, `mission_type`, `coverage_radius_km`) VALUES
('J20-001', '威龙-01', '歼-20',  1, 116.40, 39.90,    0,    0, 220, '2025-08-10 09:00:00', 100, '起飞', '制空巡航', 200),
('J20-001', '威龙-01', '歼-20',  2, 115.50, 38.80, 5000,  650, 225, '2025-08-10 09:12:00',  95, '爬升', '制空巡航', 200),
('J20-001', '威龙-01', '歼-20',  3, 112.55, 37.87, 9000,  900, 240, '2025-08-10 09:30:00',  86, '爬升', '制空巡航', 200),
('J20-001', '威龙-01', '歼-20',  4, 108.95, 34.27, 10000, 1100, 235, '2025-08-10 10:00:00',  71, '巡航', '制空巡航', 200),
('J20-001', '威龙-01', '歼-20',  5, 107.00, 33.00, 10000, 1100, 215, '2025-08-10 10:20:00',  60, '巡航', '制空巡航', 200),
('J20-001', '威龙-01', '歼-20',  6, 104.07, 30.67, 10000, 1050, 210, '2025-08-10 10:50:00',  47, '巡航', '制空巡航', 200),
('J20-001', '威龙-01', '歼-20',  7, 104.60, 28.80, 6000,  800, 200, '2025-08-10 11:15:00',  36, '下降', '制空巡航', 200),
('J20-001', '威龙-01', '歼-20',  8, 102.72, 25.04,    0,    0, 195, '2025-08-10 11:55:00',  24, '降落', '制空巡航', 200);

-- 航线4：歼-16 拉萨→福州（西南高原→东南沿海，9个轨迹点）
-- 途经：林芝→昌都→成都→重庆→恩施→长沙→南昌→福州
INSERT INTO `test_aircraft_trajectory` (`aircraft_id`, `aircraft_name`, `aircraft_type`, `seq`, `lng`, `lat`, `altitude`, `speed`, `heading`, `record_time`, `fuel_remaining`, `status`, `mission_type`, `coverage_radius_km`) VALUES
('J16-001', '潜龙-01', '歼-16',  1,  91.13, 29.65,    0,    0,  90, '2025-08-10 07:00:00', 100, '起飞', '边境警戒', 300),
('J16-001', '潜龙-01', '歼-16',  2,  94.36, 29.65, 4000,  550,  95, '2025-08-10 07:25:00',  94, '爬升', '边境警戒', 300),
('J16-001', '潜龙-01', '歼-16',  3,  97.20, 31.20, 7000,  700, 100, '2025-08-10 07:50:00',  85, '爬升', '边境警戒', 300),
('J16-001', '潜龙-01', '歼-16',  4, 104.07, 30.67, 9000,  900, 105, '2025-08-10 08:40:00',  68, '巡航', '边境警戒', 300),
('J16-001', '潜龙-01', '歼-16',  5, 106.55, 29.57, 9000,  880, 120, '2025-08-10 09:05:00',  58, '巡航', '边境警戒', 300),
('J16-001', '潜龙-01', '歼-16',  6, 109.50, 30.30, 9000,  860, 125, '2025-08-10 09:30:00',  49, '巡航', '边境警戒', 300),
('J16-001', '潜龙-01', '歼-16',  7, 112.97, 28.20, 9000,  850, 130, '2025-08-10 10:00:00',  38, '巡航', '边境警戒', 300),
('J16-001', '潜龙-01', '歼-16',  8, 115.86, 28.68, 6000,  700, 120, '2025-08-10 10:30:00',  27, '下降', '边境警戒', 300),
('J16-001', '潜龙-01', '歼-16',  9, 119.30, 26.08,    0,    0, 110, '2025-08-10 11:15:00',  15, '降落', '边境警戒', 300);

-- 航线5：运-20 呼和浩特→南宁（华北→华南中线，8个轨迹点）
-- 途经：太原→郑州→南阳→武汉→长沙→桂林→南宁
INSERT INTO `test_aircraft_trajectory` (`aircraft_id`, `aircraft_name`, `aircraft_type`, `seq`, `lng`, `lat`, `altitude`, `speed`, `heading`, `record_time`, `fuel_remaining`, `status`, `mission_type`, `coverage_radius_km`) VALUES
('Y20-002', '鲲鹏-02', '运-20',  1, 111.75, 40.84,    0,    0, 180, '2025-08-10 08:30:00', 100, '起飞', '物资投送', NULL),
('Y20-002', '鲲鹏-02', '运-20',  2, 112.55, 37.87, 4000,  420, 190, '2025-08-10 08:55:00',  94, '爬升', '物资投送', NULL),
('Y20-002', '鲲鹏-02', '运-20',  3, 113.65, 34.76, 7000,  580, 195, '2025-08-10 09:25:00',  84, '爬升', '物资投送', NULL),
('Y20-002', '鲲鹏-02', '运-20',  4, 112.50, 33.00, 9000,  700, 205, '2025-08-10 09:45:00',  76, '巡航', '物资投送', NULL),
('Y20-002', '鲲鹏-02', '运-20',  5, 114.30, 30.59, 9000,  720, 195, '2025-08-10 10:15:00',  65, '巡航', '物资投送', NULL),
('Y20-002', '鲲鹏-02', '运-20',  6, 112.97, 28.20, 9000,  710, 190, '2025-08-10 10:50:00',  53, '巡航', '物资投送', NULL),
('Y20-002', '鲲鹏-02', '运-20',  7, 110.28, 25.28, 5500,  550, 195, '2025-08-10 11:25:00',  41, '下降', '物资投送', NULL),
('Y20-002', '鲲鹏-02', '运-20',  8, 108.32, 22.82,    0,    0, 190, '2025-08-10 12:00:00',  28, '降落', '物资投送', NULL);

-- 航线6：轰-6K 沈阳→兰州（东北→西北，远程打击，8个轨迹点）
-- 途经：锦州→北京→石家庄→郑州→西安→宝鸡→兰州
INSERT INTO `test_aircraft_trajectory` (`aircraft_id`, `aircraft_name`, `aircraft_type`, `seq`, `lng`, `lat`, `altitude`, `speed`, `heading`, `record_time`, `fuel_remaining`, `status`, `mission_type`, `coverage_radius_km`, `distance_km`, `payload_kg`, `flight_duration_min`, `fuel_burn_rate`) VALUES
('H6K-001', '战神-01', '轰-6K',  1, 123.43, 41.80,    0,    0, 240, '2025-08-11 07:30:00', 100, '起飞', '远程打击', 500,    0, 15000,   0, 20.0),
('H6K-001', '战神-01', '轰-6K',  2, 121.13, 41.10, 4000,  500, 245, '2025-08-11 08:00:00',  88, '爬升', '远程打击', 500,  260, 15000,  30, 20.0),
('H6K-001', '战神-01', '轰-6K',  3, 116.40, 39.90, 8000,  800, 230, '2025-08-11 08:35:00',  78, '爬升', '远程打击', 500,  620, 15000,  65, 20.0),
('H6K-001', '战神-01', '轰-6K',  4, 114.51, 38.04, 10000, 900, 220, '2025-08-11 09:10:00',  68, '巡航', '远程打击', 500,  900, 15000, 100, 20.0),
('H6K-001', '战神-01', '轰-6K',  5, 113.65, 34.76, 10000, 920, 215, '2025-08-11 09:45:00',  55, '巡航', '远程打击', 500, 1180, 15000, 135, 20.0),
('H6K-001', '战神-01', '轰-6K',  6, 108.95, 34.27, 10000, 900, 250, '2025-08-11 10:20:00',  43, '巡航', '远程打击', 500, 1500, 15000, 170, 20.0),
('H6K-001', '战神-01', '轰-6K',  7, 107.14, 34.36, 6000,  750, 270, '2025-08-11 10:45:00',  30, '下降', '远程打击', 500, 1700, 15000, 195, 20.0),
('H6K-001', '战神-01', '轰-6K',  8, 103.83, 36.06,    0,    0, 260, '2025-08-11 11:15:00',  18, '降落', '远程打击', 500, 1950, 15000, 225, 20.0);

-- 航线7：歼-10 福州→杭州（东南沿海，空中拦截，8个轨迹点）
-- 途经：宁德→温州→台州→宁波→舟山→杭州湾→杭州
INSERT INTO `test_aircraft_trajectory` (`aircraft_id`, `aircraft_name`, `aircraft_type`, `seq`, `lng`, `lat`, `altitude`, `speed`, `heading`, `record_time`, `fuel_remaining`, `status`, `mission_type`, `coverage_radius_km`, `distance_km`, `payload_kg`, `flight_duration_min`, `fuel_burn_rate`) VALUES
('J10-001', '猎鹰-01', '歼-10',  1, 119.30, 26.08,    0,    0,  40, '2025-08-11 08:00:00', 100, '起飞', '空中拦截', 150,    0, NULL,   0, 25.0),
('J10-001', '猎鹰-01', '歼-10',  2, 119.55, 26.66, 4000,  600,  45, '2025-08-11 08:15:00',  95, '爬升', '空中拦截', 150,  100, NULL,  15, 25.0),
('J10-001', '猎鹰-01', '歼-10',  3, 120.70, 28.00, 8000,  900,  50, '2025-08-11 08:35:00',  88, '爬升', '空中拦截', 150,  250, NULL,  35, 25.0),
('J10-001', '猎鹰-01', '歼-10',  4, 121.42, 28.66, 9000, 1000,  55, '2025-08-11 08:50:00',  82, '巡航', '空中拦截', 150,  360, NULL,  50, 25.0),
('J10-001', '猎鹰-01', '歼-10',  5, 121.55, 29.87, 9000, 1050,  60, '2025-08-11 09:10:00',  72, '巡航', '空中拦截', 150,  520, NULL,  70, 25.0),
('J10-001', '猎鹰-01', '歼-10',  6, 122.10, 29.90, 9000, 1000,  65, '2025-08-11 09:25:00',  65, '巡航', '空中拦截', 150,  620, NULL,  85, 25.0),
('J10-001', '猎鹰-01', '歼-10',  7, 121.20, 30.40, 6000,  800,  70, '2025-08-11 09:40:00',  55, '下降', '空中拦截', 150,  720, NULL, 100, 25.0),
('J10-001', '猎鹰-01', '歼-10',  8, 120.15, 30.27,    0,    0,  60, '2025-08-11 10:00:00',  45, '降落', '空中拦截', 150,  850, NULL, 120, 25.0);

-- 为既有 5 架飞机回填新字段（累计航程 / 载重 / 飞行时长 / 油耗率）
UPDATE `test_aircraft_trajectory` SET `distance_km` = ROUND((`seq` - 1) * 311, 0) WHERE `aircraft_id` = 'KJ500-01';
UPDATE `test_aircraft_trajectory` SET `distance_km` = ROUND((`seq` - 1) * 355, 0) WHERE `aircraft_id` = 'Y20-001';
UPDATE `test_aircraft_trajectory` SET `distance_km` = ROUND((`seq` - 1) * 300, 0) WHERE `aircraft_id` = 'J20-001';
UPDATE `test_aircraft_trajectory` SET `distance_km` = ROUND((`seq` - 1) * 287, 0) WHERE `aircraft_id` = 'J16-001';
UPDATE `test_aircraft_trajectory` SET `distance_km` = ROUND((`seq` - 1) * 285, 0) WHERE `aircraft_id` = 'Y20-002';

UPDATE `test_aircraft_trajectory` SET `payload_kg` = 45000 WHERE `aircraft_id` = 'Y20-001';
UPDATE `test_aircraft_trajectory` SET `payload_kg` = 38000 WHERE `aircraft_id` = 'Y20-002';

UPDATE `test_aircraft_trajectory` SET `fuel_burn_rate` = 15.5 WHERE `aircraft_id` = 'KJ500-01';
UPDATE `test_aircraft_trajectory` SET `fuel_burn_rate` = 16.0 WHERE `aircraft_id` = 'Y20-001';
UPDATE `test_aircraft_trajectory` SET `fuel_burn_rate` = 26.0 WHERE `aircraft_id` = 'J20-001';
UPDATE `test_aircraft_trajectory` SET `fuel_burn_rate` = 20.0 WHERE `aircraft_id` = 'J16-001';
UPDATE `test_aircraft_trajectory` SET `fuel_burn_rate` = 20.6 WHERE `aircraft_id` = 'Y20-002';

UPDATE `test_aircraft_trajectory` t
JOIN (SELECT `aircraft_id`, MIN(`record_time`) AS `mt` FROM `test_aircraft_trajectory` GROUP BY `aircraft_id`) m
  ON t.`aircraft_id` = m.`aircraft_id`
SET t.`flight_duration_min` = TIMESTAMPDIFF(MINUTE, m.`mt`, t.`record_time`);


-- ============================================================
-- 3. 注册到数据集管理（ass_dataset + ass_field_annotation）
-- 用途：让评估分析系统能发现并使用这些表
-- ============================================================

-- 3.1 雷达信息数据集
DELETE FROM `assessment`.`ass_field_annotation` WHERE `dataset_id` = 'test_map_radar';
DELETE FROM `assessment`.`ass_dataset` WHERE `id` = 'test_map_radar';

INSERT INTO `assessment`.`ass_dataset` (`id`, `name`, `description`, `database_id`, `table_name`, `sql_text`, `records`, `allowed_columns`, `create_time`, `update_time`)
VALUES (
    'test_map_radar',
    '雷达站信息数据集',
    '记录8个雷达站的地理位置（经纬度）、覆盖半径、雷达类型和运行状态。可用于地图标点（marker）、圆形覆盖范围（circle area）等地图标注场景。',
    'test_db_001',
    'test_radar',
    'SELECT * FROM test_radar',
    8,
    'id, name, lng, lat, radius_km, radar_type, status, install_date, description',
    NOW(),
    NOW()
);

INSERT INTO `assessment`.`ass_field_annotation` (`id`, `dataset_id`, `table_name`, `column_name`, `column_type`, `is_primary_key`, `is_nullable`, `column_comment`, `annotation`, `business_meaning`, `data_category`, `create_time`, `update_time`) VALUES
('test_fa_radar_01', 'test_map_radar', 'test_radar', 'id',          'INT',         1, 0, '雷达记录唯一标识',         '主键，自增ID',                              '唯一标识',     '主键字段',  NOW(), NOW()),
('test_fa_radar_02', 'test_map_radar', 'test_radar', 'name',        'VARCHAR(50)', 0, 0, '雷达站名称',                '雷达站的名称，如"东部预警雷达站"，可作为地图标点的显示名称', '标识名称',     '维度字段',  NOW(), NOW()),
('test_fa_radar_03', 'test_map_radar', 'test_radar', 'lng',         'DOUBLE',      0, 0, '经度（地图坐标横轴）',       '雷达站所在经度，WGS84坐标系，范围-180~180。标注地图点位时使用此字段作为横坐标。', '地理位置-经度', '坐标字段',  NOW(), NOW()),
('test_fa_radar_04', 'test_map_radar', 'test_radar', 'lat',         'DOUBLE',      0, 0, '纬度（地图坐标纵轴）',       '雷达站所在纬度，WGS84坐标系，范围-90~90。标注地图点位时使用此字段作为纵坐标。', '地理位置-纬度', '坐标字段',  NOW(), NOW()),
('test_fa_radar_05', 'test_map_radar', 'test_radar', 'radius_km',   'DOUBLE',      0, 0, '覆盖半径（公里）',           '雷达探测覆盖半径，单位公里。用于绘制圆形影响范围（circle area），配合center坐标使用。', '覆盖范围',     '数值指标',  NOW(), NOW()),
('test_fa_radar_06', 'test_map_radar', 'test_radar', 'radar_type',  'VARCHAR(20)', 0, 0, '雷达类型',                  '雷达分类：预警雷达/火控雷达/搜索雷达/警戒雷达。可用于分类筛选和分组统计。', '分类维度',     '维度字段',  NOW(), NOW()),
('test_fa_radar_07', 'test_map_radar', 'test_radar', 'status',      'VARCHAR(10)', 0, 0, '运行状态',                  '雷达当前状态：运行/维护/关机。可用于统计在线率和可用性。',     '状态标识',     '维度字段',  NOW(), NOW()),
('test_fa_radar_08', 'test_map_radar', 'test_radar', 'install_date','DATE',        0, 1, '安装日期',                  '雷达站建成/安装的日期。可用于时间维度分析。',               '时间维度',     '维度字段',  NOW(), NOW()),
('test_fa_radar_09', 'test_map_radar', 'test_radar', 'description', 'VARCHAR(200)',0, 1, '描述信息',                  '雷达站的补充描述，如覆盖方向和功能说明。',                 '辅助说明',     '描述字段',  NOW(), NOW());


-- 3.2 飞机轨迹数据集
DELETE FROM `assessment`.`ass_field_annotation` WHERE `dataset_id` = 'test_map_trajectory';
DELETE FROM `assessment`.`ass_dataset` WHERE `id` = 'test_map_trajectory';

INSERT INTO `assessment`.`ass_dataset` (`id`, `name`, `description`, `database_id`, `table_name`, `sql_text`, `records`, `allowed_columns`, `create_time`, `update_time`)
VALUES (
    'test_map_trajectory',
    '飞机飞行轨迹数据集',
    '记录7架飞机（空警-500、运-20×2、歼-20、歼-16、轰-6K、歼-10）共61条飞行轨迹点位信息。航线覆盖全国六大区域：哈尔滨→广州（东北→华南）、上海→乌鲁木齐（华东→西北）、北京→昆明（华北→西南）、拉萨→福州（高原→东南沿海）、呼和浩特→南宁（华北→华南中线）、沈阳→兰州（东北→西北）、福州→杭州（东南沿海）。所有坐标基于真实城市经纬度，均在陆地上。每个点位包含经纬度坐标、高度、速度、航向、飞行状态、任务类型（预警巡逻/战略运输/制空巡航/边境警戒/物资投送/远程打击/空中拦截）、任务覆盖范围（公里，运输类为空）、累计飞行距离、载重、飞行时长、油耗率等属性。可用于地图路线连线（route）、轨迹回放、点位属性标注（marker）、飞行性能/航程载重/续航燃油/任务分布等多维指标分析等场景。',
    'test_db_001',
    'test_aircraft_trajectory',
    'SELECT * FROM test_aircraft_trajectory',
    61,
    'id, aircraft_id, aircraft_name, aircraft_type, seq, lng, lat, altitude, speed, heading, record_time, fuel_remaining, status, mission_type, coverage_radius_km, distance_km, payload_kg, flight_duration_min, fuel_burn_rate',
    NOW(),
    NOW()
);

INSERT INTO `assessment`.`ass_field_annotation` (`id`, `dataset_id`, `table_name`, `column_name`, `column_type`, `is_primary_key`, `is_nullable`, `column_comment`, `annotation`, `business_meaning`, `data_category`, `create_time`, `update_time`) VALUES
('test_fa_traj_01', 'test_map_trajectory', 'test_aircraft_trajectory', 'id',             'INT',          1, 0, '轨迹记录唯一标识',         '主键，自增ID',                                   '唯一标识',     '主键字段',  NOW(), NOW()),
('test_fa_traj_02', 'test_map_trajectory', 'test_aircraft_trajectory', 'aircraft_id',    'VARCHAR(10)',  0, 0, '飞机编号',                  '飞机唯一编号，如J20-001。用于按飞机分组查询轨迹，每条路线按此字段聚合。', '实体标识',     '维度字段',  NOW(), NOW()),
('test_fa_traj_03', 'test_map_trajectory', 'test_aircraft_trajectory', 'aircraft_name',  'VARCHAR(30)',  0, 0, '飞机呼号/名称',             '飞机呼号名称，如"威龙-01"。可作为地图路线名称或标记点名称。', '标识名称',     '维度字段',  NOW(), NOW()),
('test_fa_traj_04', 'test_map_trajectory', 'test_aircraft_trajectory', 'aircraft_type',  'VARCHAR(20)',  0, 0, '飞机机型',                  '机型分类：歼-20/歼-16/运-20/空警-500。可用于按机型筛选和分组。', '分类维度',     '维度字段',  NOW(), NOW()),
('test_fa_traj_05', 'test_map_trajectory', 'test_aircraft_trajectory', 'seq',            'INT',          0, 0, '轨迹点序号（从1开始）',      '轨迹点的顺序号，从小到大排列。绘制路线时按seq排序连接各点形成折线。', '排序字段',     '维度字段',  NOW(), NOW()),
('test_fa_traj_06', 'test_map_trajectory', 'test_aircraft_trajectory', 'lng',            'DOUBLE',       0, 0, '经度（地图坐标横轴）',       '轨迹点经度，WGS84坐标系。标注地图点位和绘制飞行路线时使用。', '地理位置-经度', '坐标字段',  NOW(), NOW()),
('test_fa_traj_07', 'test_map_trajectory', 'test_aircraft_trajectory', 'lat',            'DOUBLE',       0, 0, '纬度（地图坐标纵轴）',       '轨迹点纬度，WGS84坐标系。标注地图点位和绘制飞行路线时使用。', '地理位置-纬度', '坐标字段',  NOW(), NOW()),
('test_fa_traj_08', 'test_map_trajectory', 'test_aircraft_trajectory', 'altitude',       'INT',          0, 1, '飞行高度（米）',             '飞机在该轨迹点的飞行高度，单位米。可用于分析飞行剖面。',     '飞行参数',     '数值指标',  NOW(), NOW()),
('test_fa_traj_09', 'test_map_trajectory', 'test_aircraft_trajectory', 'speed',          'DOUBLE',       0, 1, '飞行速度（公里/小时）',      '飞机在该轨迹点的飞行速度，单位km/h。可在标记点弹窗中展示。',   '飞行参数',     '数值指标',  NOW(), NOW()),
('test_fa_traj_10', 'test_map_trajectory', 'test_aircraft_trajectory', 'heading',        'INT',          0, 1, '航向角（度，0=北，90=东）',  '飞机航向角，0度为正北，顺时针增加。可用于分析飞行方向。',     '飞行参数',     '数值指标',  NOW(), NOW()),
('test_fa_traj_11', 'test_map_trajectory', 'test_aircraft_trajectory', 'record_time',    'DATETIME',     0, 0, '记录时间',                  '轨迹点的记录时间。用于时间序列分析和轨迹按时间回放。',       '时间维度',     '维度字段',  NOW(), NOW()),
('test_fa_traj_12', 'test_map_trajectory', 'test_aircraft_trajectory', 'fuel_remaining', 'DOUBLE',       0, 1, '剩余燃油百分比',             '飞机剩余燃油百分比。可用于续航能力分析。',                 '状态参数',     '数值指标',  NOW(), NOW()),
('test_fa_traj_13', 'test_map_trajectory', 'test_aircraft_trajectory', 'status',         'VARCHAR(20)',  0, 0, '飞行状态',                  '当前飞行阶段：起飞/爬升/巡航/机动/下降/降落。可按状态筛选或统计。', '状态标识',     '维度字段',  NOW(), NOW()),
('test_fa_traj_14', 'test_map_trajectory', 'test_aircraft_trajectory', 'mission_type',   'VARCHAR(30)',  0, 0, '任务类型',                  '飞机本次执行的任务类型：预警巡逻/战略运输/制空巡航/边境警戒/物资投送/远程打击/空中拦截。可用于任务分类筛选与分组统计。', '任务分类',     '维度字段',  NOW(), NOW()),
('test_fa_traj_15', 'test_map_trajectory', 'test_aircraft_trajectory', 'coverage_radius_km', 'DOUBLE',   0, 1, '任务覆盖范围（公里）',       '任务对应的覆盖范围半径，单位公里。运输类任务无覆盖范围为 NULL。可用于覆盖能力分析。', '覆盖范围',     '数值指标',  NOW(), NOW()),
('test_fa_traj_16', 'test_map_trajectory', 'test_aircraft_trajectory', 'distance_km',    'DOUBLE',       0, 0, '累计飞行距离（公里）',       '从起飞点累加的飞行距离，单位公里。可用于航程、续航与飞行效率分析。', '飞行参数',     '数值指标',  NOW(), NOW()),
('test_fa_traj_17', 'test_map_trajectory', 'test_aircraft_trajectory', 'payload_kg',     'DOUBLE',       0, 1, '载重（公斤）',               '飞机载重，单位公斤。运输/轰炸机有载重，战斗机为 NULL。可用于运输能力与载荷分析。', '载荷参数',     '数值指标',  NOW(), NOW()),
('test_fa_traj_18', 'test_map_trajectory', 'test_aircraft_trajectory', 'flight_duration_min', 'INT',    0, 0, '累计飞行时长（分钟）',       '从起飞到该轨迹点的累计飞行时长，单位分钟。可用于巡航时长与飞行效率分析。', '飞行参数',     '数值指标',  NOW(), NOW()),
('test_fa_traj_19', 'test_map_trajectory', 'test_aircraft_trajectory', 'fuel_burn_rate', 'DOUBLE',       0, 1, '油耗率（%每小时）',          '单位小时燃油消耗百分比。可用于续航能力与油耗效率分析。', '续航参数',     '数值指标',  NOW(), NOW());


-- 3.3 飞机轨迹指标（绑定到 test_map_trajectory 数据集）
DELETE FROM `assessment`.`ass_indicator` WHERE `dataset_id` = 'test_map_trajectory';

INSERT INTO `assessment`.`ass_indicator`
  (`id`, `name`, `category`, `formula`, `description`, `weight`, `dataset_id`, `field_mapping`, `calculation_method`, `create_time`, `update_time`)
VALUES
  -- 任务覆盖
  ('ind_traj_coverage_max',     '最大任务覆盖范围', '任务', 'MAX(coverage_radius_km)',
   '各架飞机任务覆盖范围的最大值，单位公里。运输类无覆盖范围任务不计入。', 1.0, 'test_map_trajectory',
   '{"metricField": "coverage_radius_km"}', 'MAX(coverage_radius_km)', NOW(), NOW()),
  ('ind_traj_coverage_avg',     '平均任务覆盖范围', '任务', 'AVG(coverage_radius_km)',
   '具备覆盖范围任务的平均覆盖半径，单位公里。', 1.0, 'test_map_trajectory',
   '{"metricField": "coverage_radius_km"}', 'AVG(coverage_radius_km)', NOW(), NOW()),
  ('ind_traj_covered_aircraft', '具备覆盖范围飞机数', '任务', 'COUNT(DISTINCT CASE WHEN coverage_radius_km IS NOT NULL THEN aircraft_id END)',
   '覆盖范围非空（具备任务覆盖范围）的飞机架次数。', 1.0, 'test_map_trajectory',
   '{"metricField": "coverage_radius_km", "groupField": "aircraft_id"}', 'COUNT(DISTINCT CASE WHEN coverage_radius_km IS NOT NULL THEN aircraft_id END)', NOW(), NOW()),
  -- 飞行性能
  ('ind_traj_alt_max',          '最大飞行高度', '飞行性能', 'MAX(altitude)',
   '所有轨迹点中的最大飞行高度，单位米。', 1.0, 'test_map_trajectory',
   '{"metricField": "altitude"}', 'MAX(altitude)', NOW(), NOW()),
  ('ind_traj_alt_avg',          '平均飞行高度', '飞行性能', 'AVG(altitude)',
   '所有轨迹点的平均飞行高度，单位米。', 1.0, 'test_map_trajectory',
   '{"metricField": "altitude"}', 'AVG(altitude)', NOW(), NOW()),
  ('ind_traj_speed_max',        '最大飞行速度', '飞行性能', 'MAX(speed)',
   '所有轨迹点中的最大飞行速度，单位公里/小时。', 1.0, 'test_map_trajectory',
   '{"metricField": "speed"}', 'MAX(speed)', NOW(), NOW()),
  ('ind_traj_speed_avg',        '平均飞行速度', '飞行性能', 'AVG(speed)',
   '所有轨迹点的平均飞行速度，单位公里/小时。', 1.0, 'test_map_trajectory',
   '{"metricField": "speed"}', 'AVG(speed)', NOW(), NOW()),
  -- 航程与载重
  ('ind_traj_max_distance',     '最长单机航程', '航程与载重', 'MAX(distance_km)',
   '单架飞机的最长累计飞行距离，单位公里。', 1.0, 'test_map_trajectory',
   '{"metricField": "distance_km"}', 'MAX(distance_km)', NOW(), NOW()),
  ('ind_traj_avg_distance',     '平均累计航程', '航程与载重', 'AVG(distance_km)',
   '所有轨迹点的平均累计飞行距离，单位公里。', 1.0, 'test_map_trajectory',
   '{"metricField": "distance_km"}', 'AVG(distance_km)', NOW(), NOW()),
  ('ind_traj_payload_max',      '最大载重', '航程与载重', 'MAX(payload_kg)',
   '运输/轰炸机的最大载重，单位公斤。', 1.0, 'test_map_trajectory',
   '{"metricField": "payload_kg"}', 'MAX(payload_kg)', NOW(), NOW()),
  ('ind_traj_payload_avg',      '平均载重', '航程与载重', 'AVG(payload_kg)',
   '具备载重飞机的平均载重，单位公斤。', 1.0, 'test_map_trajectory',
   '{"metricField": "payload_kg"}', 'AVG(payload_kg)', NOW(), NOW()),
  ('ind_traj_loaded_aircraft',  '具备载重飞机数', '航程与载重', 'COUNT(DISTINCT CASE WHEN payload_kg IS NOT NULL THEN aircraft_id END)',
   '载重非空的飞机架次数（运输/轰炸机）。', 1.0, 'test_map_trajectory',
   '{"metricField": "payload_kg", "groupField": "aircraft_id"}', 'COUNT(DISTINCT CASE WHEN payload_kg IS NOT NULL THEN aircraft_id END)', NOW(), NOW()),
  -- 续航与燃油
  ('ind_traj_fuel_avg',         '平均剩余燃油', '续航与燃油', 'AVG(fuel_remaining)',
   '所有轨迹点的平均剩余燃油百分比。', 1.0, 'test_map_trajectory',
   '{"metricField": "fuel_remaining"}', 'AVG(fuel_remaining)', NOW(), NOW()),
  ('ind_traj_fuel_min',         '最低剩余燃油', '续航与燃油', 'MIN(fuel_remaining)',
   '所有轨迹点中的最低剩余燃油百分比。', 1.0, 'test_map_trajectory',
   '{"metricField": "fuel_remaining"}', 'MIN(fuel_remaining)', NOW(), NOW()),
  ('ind_traj_burn_avg',         '平均油耗率', '续航与燃油', 'AVG(fuel_burn_rate)',
   '各机平均油耗率，单位百分比/小时。', 1.0, 'test_map_trajectory',
   '{"metricField": "fuel_burn_rate"}', 'AVG(fuel_burn_rate)', NOW(), NOW()),
  ('ind_traj_burn_max',         '最大油耗率', '续航与燃油', 'MAX(fuel_burn_rate)',
   '各机中的最大油耗率，单位百分比/小时。', 1.0, 'test_map_trajectory',
   '{"metricField": "fuel_burn_rate"}', 'MAX(fuel_burn_rate)', NOW(), NOW()),
  -- 任务与机型分布
  ('ind_traj_aircraft_count',       '飞机总架次', '任务与机型', 'COUNT(DISTINCT aircraft_id)',
   '参与任务的飞机总架次数。', 1.0, 'test_map_trajectory',
   '{"groupField": "aircraft_id"}', 'COUNT(DISTINCT aircraft_id)', NOW(), NOW()),
  ('ind_traj_mission_count',        '任务类型数量', '任务与机型', 'COUNT(DISTINCT mission_type)',
   '本次数据覆盖的任务类型数量。', 1.0, 'test_map_trajectory',
   '{"groupField": "mission_type"}', 'COUNT(DISTINCT mission_type)', NOW(), NOW()),
  ('ind_traj_aircraft_type_count',  '机型数量', '任务与机型', 'COUNT(DISTINCT aircraft_type)',
   '本次数据覆盖的机型数量。', 1.0, 'test_map_trajectory',
   '{"groupField": "aircraft_type"}', 'COUNT(DISTINCT aircraft_type)', NOW(), NOW());


-- ============================================================
-- 4. 验证数据
-- ============================================================
SELECT '========================================' AS '';
SELECT '  地图标注测试数据导入完成！' AS '';
SELECT '' AS '';
SELECT CONCAT('  雷达站: ', COUNT(*), ' 个') AS '' FROM `test_radar`;
SELECT CONCAT('  飞机轨迹: ', COUNT(DISTINCT aircraft_id), ' 架飞机, ', COUNT(*), ' 条记录') AS '' FROM `test_aircraft_trajectory`;
SELECT '' AS '';
SELECT CONCAT('  数据集注册: ', COUNT(*), ' 个') AS '' FROM `assessment`.`ass_dataset` WHERE `id` IN ('test_map_radar', 'test_map_trajectory');
SELECT '' AS '';
SELECT '  预期测试用例:' AS '';
SELECT '  - map_marker: 问"标注所有雷达站的位置" → 8个标记点' AS '';
SELECT '  - map_area:   问"显示东海方向的雷达覆盖范围" → 圆形范围' AS '';
SELECT '  - map_route:  问"显示威龙-01的巡逻路线" → 折线轨迹' AS '';
SELECT '  - 组合:       问"标注所有雷达站和飞机轨迹" → 标点+连线+范围' AS '';
SELECT '========================================' AS '';
