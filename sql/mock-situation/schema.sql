-- ============================================================
-- 态势图模块 mock 数据库：战机侦察打击（台海场景，虚构数据）
-- 数据库：mock_situation，共 12 张表
-- 阵营设定（全库统一）：红方 = 大陆方（我方）；蓝方 = 敌方
-- 设计约定（与 ipage 的 researcher 地理整形规则对齐）：
--   1. 航迹表使用 seq + aircraft_id/aircraft_name + xxx_lng/xxx_lat → 自动连线成航线
--   2. 范围圈表使用 name + lng/lat + radius_km → 自动生成圆形范围圈
--   3. 事件表携带 event_lng/event_lat → 自动落点标注
-- ============================================================

CREATE DATABASE IF NOT EXISTS mock_situation DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE mock_situation;

-- ------------------------------------------------------------
-- 1. 机型档案表（模糊命名，不涉及真实机型）
-- ------------------------------------------------------------
DROP TABLE IF EXISTS mock_aircraft_type;
CREATE TABLE mock_aircraft_type (
    type_id           VARCHAR(32)  NOT NULL COMMENT '机型编号',
    type_name         VARCHAR(64)  NOT NULL COMMENT '机型名称（模糊命名）',
    faction           VARCHAR(8)   NOT NULL COMMENT '阵营（红方/蓝方）；我方即红方（大陆方），蓝方为敌方',
    category          VARCHAR(32)  NOT NULL COMMENT '类别：侦察机/预警机/无人攻击机/无人侦察机',
    max_speed_kmh     INT          NOT NULL COMMENT '最大速度 km/h',
    cruise_speed_kmh  INT          NOT NULL COMMENT '巡航速度 km/h',
    max_altitude_m    INT          NOT NULL COMMENT '最大升限 m',
    max_range_km      INT          NOT NULL COMMENT '最大航程 km',
    recon_radius_km   INT          DEFAULT 0 COMMENT '侦察半径 km',
    strike_radius_km  INT          DEFAULT 0 COMMENT '打击半径 km',
    combat_load_kg    INT          DEFAULT 0 COMMENT '最大载弹量 kg',
    crew              INT          DEFAULT 1 COMMENT '机组人数',
    PRIMARY KEY (type_id),
    KEY idx_type_faction (faction)
) ENGINE=InnoDB COMMENT='机型档案（虚构模糊命名）';

-- ------------------------------------------------------------
-- 2. 飞机档案表
-- ------------------------------------------------------------
DROP TABLE IF EXISTS mock_aircraft;
CREATE TABLE mock_aircraft (
    aircraft_id      VARCHAR(32)  NOT NULL COMMENT '飞机编号',
    callsign         VARCHAR(64)  NOT NULL COMMENT '呼号，如 侦察机01',
    type_id          VARCHAR(32)  NOT NULL COMMENT '机型编号',
    faction          VARCHAR(8)   NOT NULL COMMENT '阵营（红方/蓝方）；我方即红方（大陆方），蓝方为敌方',
    squadron         VARCHAR(64)  DEFAULT NULL COMMENT '所属中队',
    base_name        VARCHAR(64)  DEFAULT NULL COMMENT '驻扎基地',
    home_lng         DECIMAL(10,6) DEFAULT NULL COMMENT '驻场经度',
    home_lat         DECIMAL(10,6) DEFAULT NULL COMMENT '驻场纬度',
    status           VARCHAR(16)  NOT NULL DEFAULT '在役' COMMENT '状态：在役/战损/维修',
    commission_date  DATE         DEFAULT NULL COMMENT '列装日期',
    PRIMARY KEY (aircraft_id),
    KEY idx_ac_type (type_id),
    KEY idx_ac_faction (faction)
) ENGINE=InnoDB COMMENT='飞机档案';

-- ------------------------------------------------------------
-- 3. 我方（红方，大陆方）航迹点表（核心时序表，含威胁预计算字段）
-- ------------------------------------------------------------
DROP TABLE IF EXISTS mock_track_point;
CREATE TABLE mock_track_point (
    id                BIGINT        NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    aircraft_id       VARCHAR(32)   NOT NULL COMMENT '飞机编号',
    aircraft_name     VARCHAR(64)   NOT NULL COMMENT '飞机呼号',
    faction           VARCHAR(8)    NOT NULL DEFAULT '红方' COMMENT '阵营（红方/蓝方）；我方即红方（大陆方），蓝方为敌方',
    mission_id        VARCHAR(32)   DEFAULT NULL COMMENT '所属任务编号',
    seq               INT           NOT NULL COMMENT '航迹点序号（升序连线）',
    record_time       DATETIME      NOT NULL COMMENT '记录时间',
    track_lng         DECIMAL(10,6) NOT NULL COMMENT '经度',
    track_lat         DECIMAL(10,6) NOT NULL COMMENT '纬度',
    altitude_m        INT           DEFAULT NULL COMMENT '高度 m',
    speed_kmh         INT           DEFAULT NULL COMMENT '速度 km/h',
    heading_deg       INT           DEFAULT NULL COMMENT '航向 角度',
    vertical_rate_mps DECIMAL(5,1)  DEFAULT NULL COMMENT '垂直速率 m/s',
    overlap_count     INT           DEFAULT 0 COMMENT '处于敌方（蓝方）火力圈数量（预计算）',
    threat_level      TINYINT       DEFAULT 0 COMMENT '威胁等级 0-4（预计算：0无/1低/2中/3高/4极高）',
    PRIMARY KEY (id),
    KEY idx_tp_aircraft (aircraft_id, seq),
    KEY idx_tp_time (record_time),
    KEY idx_tp_mission (mission_id)
) ENGINE=InnoDB COMMENT='我方（红方）航迹点（时间序列）';

-- ------------------------------------------------------------
-- 4. 敌方（蓝方）航迹点表（打击半径为机型定值，见 mock_aircraft_type.strike_radius_km；
--    飞机位置随时间移动，牵动打击覆盖范围沿航迹动态形成）
-- ------------------------------------------------------------
DROP TABLE IF EXISTS mock_enemy_track_point;
CREATE TABLE mock_enemy_track_point (
    id                     BIGINT        NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    enemy_aircraft_id      VARCHAR(32)   NOT NULL COMMENT '敌机编号（关联 mock_aircraft.aircraft_id 取机型/阵营）',
    enemy_aircraft_name    VARCHAR(64)   NOT NULL COMMENT '敌机呼号',
    mission_id             VARCHAR(32)   DEFAULT NULL COMMENT '所属任务编号',
    seq                    INT           NOT NULL COMMENT '航迹点序号',
    record_time            DATETIME      NOT NULL COMMENT '记录时间',
    track_lng              DECIMAL(10,6) NOT NULL COMMENT '经度',
    track_lat              DECIMAL(10,6) NOT NULL COMMENT '纬度',
    altitude_m             INT           DEFAULT NULL COMMENT '高度 m',
    speed_kmh              INT           DEFAULT NULL COMMENT '速度 km/h',
    heading_deg            INT           DEFAULT NULL COMMENT '航向 角度',
    coverage_overlap_count INT           DEFAULT 0 COMMENT '与友机火力圈重叠数（预计算，按机型定值半径）',
    PRIMARY KEY (id),
    KEY idx_et_aircraft (enemy_aircraft_id, seq),
    KEY idx_et_time (record_time),
    KEY idx_et_mission (mission_id)
) ENGINE=InnoDB COMMENT='敌方（蓝方）航迹点（火力覆盖随飞机位置移动）';

-- ------------------------------------------------------------
-- 5. 作战能力范围表（LEGACY：保留作手动覆盖路径，新数据不再写入）
-- ------------------------------------------------------------
-- 注：能力圈由 ipage 在运行时按"当前时间 t + 飞机当前位置 + 机型档案半径"动态生成
--     （一架飞机一个圈，圆心随飞机走），不依赖本表预计算。
--     本表仅保留作向后兼容：用户手动指定能力圈时（range_type='manual'）可写入。
DROP TABLE IF EXISTS mock_capability_range;
CREATE TABLE mock_capability_range (
    range_id      VARCHAR(32)   NOT NULL COMMENT '范围编号',
    name          VARCHAR(64)  NOT NULL COMMENT '范围名称',
    faction       VARCHAR(8)   NOT NULL DEFAULT '红方' COMMENT '阵营（红方/蓝方）；我方即红方（大陆方），蓝方为敌方',
    range_type    VARCHAR(16)  NOT NULL COMMENT '类型：侦察范围/打击范围/manual',
    lng           DECIMAL(10,6) NOT NULL COMMENT '圆心经度',
    lat           DECIMAL(10,6) NOT NULL COMMENT '圆心纬度',
    radius_km     DECIMAL(8,1)  NOT NULL COMMENT '半径 km',
    owner_type    VARCHAR(16)  DEFAULT NULL COMMENT '归属类型：飞机/机型/基地',
    owner_id      VARCHAR(32)  DEFAULT NULL COMMENT '归属编号',
    aircraft_id   VARCHAR(32)  DEFAULT NULL COMMENT '关联飞机编号（legacy）',
    mission_id    VARCHAR(32)  DEFAULT NULL COMMENT '关联任务编号（legacy）',
    snapshot_time DATETIME     DEFAULT NULL COMMENT '快照时间（legacy）',
    PRIMARY KEY (range_id),
    KEY idx_cr_aircraft (aircraft_id),
    KEY idx_cr_mission (mission_id),
    KEY idx_cr_time (snapshot_time),
    KEY idx_cr_type (range_type)
) ENGINE=InnoDB COMMENT='[LEGACY] 作战能力范围圈（运行时由 map_builder 动态生成，本表仅供手动覆盖）';

-- ------------------------------------------------------------
-- 6. 敌方（蓝方）静态威胁单元表（地面防空/雷达/岸舰导弹阵地）
-- ------------------------------------------------------------
DROP TABLE IF EXISTS mock_enemy_threat;
CREATE TABLE mock_enemy_threat (
    threat_id        VARCHAR(32)   NOT NULL COMMENT '威胁单元编号',
    threat_name      VARCHAR(64)   NOT NULL COMMENT '名称（圈标注名）',
    threat_type      VARCHAR(32)   NOT NULL COMMENT '类型：远程防空阵地/中程防空阵地/预警雷达站/岸舰导弹阵地',
    lng              DECIMAL(10,6) NOT NULL COMMENT '经度',
    lat              DECIMAL(10,6) NOT NULL COMMENT '纬度',
    detect_radius_km INT           NOT NULL DEFAULT 0 COMMENT '探测半径 km',
    strike_radius_km INT           NOT NULL DEFAULT 0 COMMENT '打击半径 km',
    threat_level     TINYINT       NOT NULL DEFAULT 2 COMMENT '威胁等级 1-4',
    status           VARCHAR(16)   NOT NULL DEFAULT '活跃' COMMENT '状态：活跃/压制/摧毁',
    note             VARCHAR(255)  DEFAULT NULL COMMENT '备注',
    PRIMARY KEY (threat_id),
    KEY idx_threat_type (threat_type)
) ENGINE=InnoDB COMMENT='敌方（蓝方）静态威胁单元';

-- ------------------------------------------------------------
-- 7. 打击目标表
-- ------------------------------------------------------------
DROP TABLE IF EXISTS mock_target;
CREATE TABLE mock_target (
    target_id      VARCHAR(32)   NOT NULL COMMENT '目标编号',
    target_name    VARCHAR(64)   NOT NULL COMMENT '目标名称',
    category       VARCHAR(32)   NOT NULL COMMENT '类别：预警雷达站/指挥所/弹药库/港口设施/机场跑道/防空阵地/通信中继站/燃油储备库',
    importance     TINYINT       NOT NULL DEFAULT 3 COMMENT '重要度 1-5 星',
    lng            DECIMAL(10,6) NOT NULL COMMENT '经度',
    lat            DECIMAL(10,6) NOT NULL COMMENT '纬度',
    defense_level  TINYINT       NOT NULL DEFAULT 2 COMMENT '防御等级 1-5',
    status         VARCHAR(16)   NOT NULL DEFAULT '完好' COMMENT '状态：完好/受损/摧毁',
    destroyed_time DATETIME      DEFAULT NULL COMMENT '摧毁/受损时间',
    PRIMARY KEY (target_id),
    KEY idx_target_status (status)
) ENGINE=InnoDB COMMENT='打击目标（敌方/蓝方目标）';

-- ------------------------------------------------------------
-- 8. 任务表
-- ------------------------------------------------------------
DROP TABLE IF EXISTS mock_mission;
CREATE TABLE mock_mission (
    mission_id     VARCHAR(32)  NOT NULL COMMENT '任务编号',
    mission_name   VARCHAR(128) NOT NULL COMMENT '任务名称',
    mission_type   VARCHAR(16)  NOT NULL COMMENT '类型：侦察/打击/预警/护航/巡逻',
    aircraft_id    VARCHAR(32)  NOT NULL COMMENT '执行飞机编号',
    aircraft_name  VARCHAR(64)  NOT NULL COMMENT '执行飞机呼号',
    faction        VARCHAR(8)   NOT NULL DEFAULT '红方' COMMENT '阵营（红方/蓝方）；我方即红方（大陆方），蓝方为敌方',
    target_id      VARCHAR(32)  DEFAULT NULL COMMENT '关联目标编号（打击/侦察任务）',
    start_time     DATETIME     NOT NULL COMMENT '开始时间',
    end_time       DATETIME     NOT NULL COMMENT '结束时间',
    status         VARCHAR(16)  NOT NULL DEFAULT '完成' COMMENT '状态：完成/中止/进行中',
    result_summary VARCHAR(255) DEFAULT NULL COMMENT '结果概述',
    PRIMARY KEY (mission_id),
    KEY idx_mission_time (start_time),
    KEY idx_mission_type (mission_type),
    KEY idx_mission_aircraft (aircraft_id)
) ENGINE=InnoDB COMMENT='飞行任务';

-- ------------------------------------------------------------
-- 9. 打击事件表（打击效果评估）
-- ------------------------------------------------------------
DROP TABLE IF EXISTS mock_strike_event;
CREATE TABLE mock_strike_event (
    event_id        VARCHAR(32)   NOT NULL COMMENT '事件编号',
    mission_id      VARCHAR(32)   NOT NULL COMMENT '所属任务编号',
    aircraft_id     VARCHAR(32)   NOT NULL COMMENT '执行飞机编号',
    aircraft_name   VARCHAR(64)   NOT NULL COMMENT '执行飞机呼号',
    target_id       VARCHAR(32)   NOT NULL COMMENT '目标编号',
    target_name     VARCHAR(64)   NOT NULL COMMENT '目标名称',
    event_time      DATETIME      NOT NULL COMMENT '打击时间',
    event_lng       DECIMAL(10,6) NOT NULL COMMENT '打击点经度（目标坐标附近）',
    event_lat       DECIMAL(10,6) NOT NULL COMMENT '打击点纬度',
    weapon_type     VARCHAR(32)   NOT NULL COMMENT '弹药类型：精确制导炸弹/防区外导弹/反辐射导弹',
    hit_result      VARCHAR(16)   NOT NULL COMMENT '结果：摧毁/受损/未命中',
    collateral_note VARCHAR(255)  DEFAULT NULL COMMENT '毁伤评估备注',
    PRIMARY KEY (event_id),
    KEY idx_strike_time (event_time),
    KEY idx_strike_target (target_id)
) ENGINE=InnoDB COMMENT='打击事件与效果评估';

-- ------------------------------------------------------------
-- 10. 战损记录表
-- ------------------------------------------------------------
DROP TABLE IF EXISTS mock_battle_damage;
CREATE TABLE mock_battle_damage (
    damage_id    VARCHAR(32)   NOT NULL COMMENT '战损编号',
    aircraft_id  VARCHAR(32)   NOT NULL COMMENT '飞机编号',
    aircraft_name VARCHAR(64)  NOT NULL COMMENT '飞机呼号',
    faction      VARCHAR(8)    NOT NULL COMMENT '阵营（红方/蓝方）；我方即红方（大陆方），蓝方为敌方',
    mission_id   VARCHAR(32)   DEFAULT NULL COMMENT '所属任务编号',
    event_time   DATETIME      NOT NULL COMMENT '战损时间',
    event_lng    DECIMAL(10,6) NOT NULL COMMENT '事件地点经度',
    event_lat    DECIMAL(10,6) NOT NULL COMMENT '事件地点纬度',
    damage_type  VARCHAR(16)   NOT NULL COMMENT '类型：击伤/击落/迫降/事故',
    severity     VARCHAR(16)   NOT NULL COMMENT '程度：轻损/中损/重损/坠毁',
    caused_by    VARCHAR(32)   NOT NULL COMMENT '原因：敌防空火力/空战/机械故障',
    confirmed    TINYINT       NOT NULL DEFAULT 1 COMMENT '是否确认 0/1',
    PRIMARY KEY (damage_id),
    KEY idx_damage_time (event_time),
    KEY idx_damage_faction (faction)
) ENGINE=InnoDB COMMENT='战损记录（含我方红方与敌方蓝方）';

-- ------------------------------------------------------------
-- 11. 侦察发现事件表
-- ------------------------------------------------------------
DROP TABLE IF EXISTS mock_recon_event;
CREATE TABLE mock_recon_event (
    event_id      VARCHAR(32)   NOT NULL COMMENT '事件编号',
    aircraft_id   VARCHAR(32)   NOT NULL COMMENT '侦察机编号',
    aircraft_name VARCHAR(64)   NOT NULL COMMENT '侦察机呼号',
    target_id     VARCHAR(32)   DEFAULT NULL COMMENT '发现目标编号',
    target_name   VARCHAR(64)   DEFAULT NULL COMMENT '发现目标名称',
    mission_id    VARCHAR(32)   DEFAULT NULL COMMENT '所属任务编号',
    event_time    DATETIME      NOT NULL COMMENT '发现时间',
    event_lng     DECIMAL(10,6) NOT NULL COMMENT '发现地点经度',
    event_lat     DECIMAL(10,6) NOT NULL COMMENT '发现地点纬度',
    confidence    TINYINT       NOT NULL DEFAULT 80 COMMENT '置信度 0-100',
    intel_summary VARCHAR(255)  DEFAULT NULL COMMENT '情报摘要',
    PRIMARY KEY (event_id),
    KEY idx_recon_time (event_time),
    KEY idx_recon_target (target_id)
) ENGINE=InnoDB COMMENT='侦察发现事件';

-- ------------------------------------------------------------
-- 12. 每日态势汇总表（时间轴拖动动态变化的核心数据源）
-- ------------------------------------------------------------
DROP TABLE IF EXISTS mock_daily_situation;
CREATE TABLE mock_daily_situation (
    stat_date           DATE         NOT NULL COMMENT '统计日期',
    campaign_phase      VARCHAR(16)  NOT NULL COMMENT '当日活动类型（动态派生）：低烈度日/前出日/侦察日/摩擦日/对抗日/打击日',
    blue_sortie_count   INT          NOT NULL DEFAULT 0 COMMENT '蓝方（敌方）当日架次',
    red_sortie_count    INT          NOT NULL DEFAULT 0 COMMENT '红方（我方）当日架次',
    recon_event_count   INT          NOT NULL DEFAULT 0 COMMENT '当日侦察发现次数',
    strike_event_count  INT          NOT NULL DEFAULT 0 COMMENT '当日打击次数',
    blue_loss_today     INT          NOT NULL DEFAULT 0 COMMENT '蓝方（敌方）当日战损',
    red_loss_today      INT          NOT NULL DEFAULT 0 COMMENT '红方（我方）当日战损',
    blue_loss_total     INT          NOT NULL DEFAULT 0 COMMENT '蓝方（敌方）累计战损',
    red_loss_total      INT          NOT NULL DEFAULT 0 COMMENT '红方（我方）累计战损',
    max_threat_level    TINYINT      NOT NULL DEFAULT 0 COMMENT '当日最高威胁等级 0-4',
    threat_index        TINYINT      NOT NULL DEFAULT 0 COMMENT '当日威胁指数 0-100',
    enemy_patrol_active TINYINT      NOT NULL DEFAULT 0 COMMENT '敌机是否出动 0/1',
    PRIMARY KEY (stat_date)
) ENGINE=InnoDB COMMENT='每日态势汇总（时间轴切片核心表）';
