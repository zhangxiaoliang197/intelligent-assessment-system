-- ============================================================
-- 智能评估系统 - MySQL 初始化脚本
-- 用途：在新机器上自动建立数据库、表及初始数据
-- 用法：mysql -u root -p < init-mysql.sql
-- ============================================================

-- 变量（可在此修改默认值）
-- 数据库名、用户、密码
SET @db_name = 'assessment';
SET @db_user = 'root';
SET @db_password = 'root';

-- ============================================================
-- 1. 创建数据库
-- ============================================================
CREATE DATABASE IF NOT EXISTS `assessment`
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE `assessment`;

-- ============================================================
-- 2. 创建表结构
-- ============================================================

-- 2.1 数据库连接配置
CREATE TABLE IF NOT EXISTS `ass_database_config` (
    `id`            VARCHAR(32)   NOT NULL,
    `name`          VARCHAR(100)  NOT NULL,
    `type`          VARCHAR(50)   NOT NULL,
    `host`          VARCHAR(255)  DEFAULT NULL,
    `port`          INT           DEFAULT NULL,
    `db_name`       VARCHAR(100)  DEFAULT NULL,
    `username`      VARCHAR(100)  DEFAULT NULL,
    `password`      VARCHAR(255)  DEFAULT NULL,
    `status`        VARCHAR(20)   DEFAULT '未连接',
    `db_version`    VARCHAR(200)  DEFAULT NULL,
    `latency`       VARCHAR(20)   DEFAULT NULL,
    `error_msg`     VARCHAR(500)  DEFAULT NULL,
    `create_time`   DATETIME      DEFAULT NULL,
    `update_time`   DATETIME      DEFAULT NULL,
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2.2 数据集
CREATE TABLE IF NOT EXISTS `ass_dataset` (
    `id`            VARCHAR(32)   NOT NULL,
    `name`          VARCHAR(200)  NOT NULL,
    `description`   TEXT          DEFAULT NULL,
    `database_id`   VARCHAR(32)   DEFAULT NULL,
    `table_name`    VARCHAR(200)  DEFAULT NULL,
    `sql_text`      TEXT          DEFAULT NULL,
    `records`       INT           DEFAULT 0,
    `last_executed` DATETIME      DEFAULT NULL,
    `create_time`   DATETIME      DEFAULT NULL,
    `update_time`   DATETIME      DEFAULT NULL,
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2.3 字段标注
CREATE TABLE IF NOT EXISTS `ass_field_annotation` (
    `id`               VARCHAR(32)   NOT NULL,
    `dataset_id`       VARCHAR(32)   NOT NULL,
    `table_name`       VARCHAR(200)  NOT NULL,
    `column_name`      VARCHAR(200)  NOT NULL,
    `column_type`      VARCHAR(100)  DEFAULT NULL,
    `is_primary_key`   TINYINT(1)    DEFAULT NULL,
    `is_nullable`      TINYINT(1)    DEFAULT NULL,
    `column_comment`   VARCHAR(500)  DEFAULT NULL,
    `annotation`       TEXT          DEFAULT NULL,
    `business_meaning` TEXT          DEFAULT NULL,
    `data_category`    VARCHAR(100)  DEFAULT NULL,
    `create_time`      DATETIME      DEFAULT NULL,
    `update_time`      DATETIME      DEFAULT NULL,
    PRIMARY KEY (`id`),
    INDEX `idx_fa_dataset` (`dataset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2.4 指标
CREATE TABLE IF NOT EXISTS `ass_indicator` (
    `id`                 VARCHAR(32)   NOT NULL,
    `name`               VARCHAR(200)  NOT NULL,
    `category`           VARCHAR(100)  DEFAULT NULL,
    `formula`            TEXT          DEFAULT NULL,
    `description`        TEXT          DEFAULT NULL,
    `weight`             DOUBLE        DEFAULT NULL,
    `dataset_id`         VARCHAR(32)   DEFAULT NULL,
    `field_mapping`      JSON          DEFAULT NULL,
    `calculation_method` TEXT          DEFAULT NULL,
    `create_time`        DATETIME      DEFAULT NULL,
    `update_time`        DATETIME      DEFAULT NULL,
    PRIMARY KEY (`id`),
    INDEX `idx_ind_dataset` (`dataset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2.5 大模型配置
CREATE TABLE IF NOT EXISTS `ass_llm_config` (
    `id`          VARCHAR(32)   NOT NULL,
    `name`        VARCHAR(100)  NOT NULL,
    `llm_type`    VARCHAR(50)   NOT NULL,
    `api_url`     VARCHAR(500)  DEFAULT NULL,
    `api_key`     VARCHAR(500)  DEFAULT NULL,
    `model`       VARCHAR(100)  DEFAULT NULL,
    `temperature` DOUBLE        DEFAULT NULL,
    `max_tokens`  INT           DEFAULT NULL,
    `top_p`       DOUBLE        DEFAULT NULL,
    `is_active`   TINYINT(1)    NOT NULL DEFAULT 0,
    `create_time` DATETIME      DEFAULT NULL,
    `update_time` DATETIME      DEFAULT NULL,
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- 3. 插入初始数据（仅当表为空时）
-- ============================================================

-- 3.1 默认大模型配置（DeepSeek）
INSERT IGNORE INTO `ass_llm_config` (`id`, `name`, `llm_type`, `api_url`, `api_key`, `model`, `temperature`, `max_tokens`, `top_p`, `is_active`, `create_time`, `update_time`)
VALUES ('llm_001', 'DeepSeek 默认', 'deepseek', 'https://api.deepseek.com/v1', '', 'deepseek-chat', 0.7, 2000, 0.9, 1, NOW(), NOW());

-- ============================================================
-- 完成
-- ============================================================
SELECT '========================================' AS '';
SELECT '  MySQL 初始化完成！' AS '';
SELECT '  数据库: assessment' AS '';
SELECT '  表: ass_database_config, ass_dataset, ass_field_annotation, ass_indicator, ass_llm_config' AS '';
SELECT '  默认 LLM: DeepSeek (llm_001, 已激活)' AS '';
SELECT '========================================' AS '';
