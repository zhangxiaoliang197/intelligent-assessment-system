-- ============================================================
-- 智能评估系统 - 演示指标种子数据
-- 让 situation-service 的「indicator」数据源有记录可返回，
-- 配合 scripts/demo-business-data.sql 的演示业务库与数据集使用。
--
-- 用法（本机 MySQL root/root）：
--   mysql -h localhost -P 3306 -u root -proot assessment < scripts/demo-indicator-data.sql
--
-- 说明：
--   - 指标绑定到 demo_business 已注册的数据集（ds_0037d14b=t_force 兵力单位编制表、
--     ds_67804b95=t_deployment 兵力部署态势表 等），field_mapping 指向对应表字段。
--   - 重复执行会因主键冲突报错，属正常（本脚本非幂等）。
-- ============================================================

USE `assessment`;

INSERT INTO `ass_indicator`
  (`id`, `name`, `category`, `formula`, `description`, `weight`, `dataset_id`, `field_mapping`, `calculation_method`, `create_time`, `update_time`)
VALUES
  ('ind_deployable',     '可部署兵力',   '兵力', 'SUM(deployable_count)',
   '各单位可部署兵力合计，反映可投入部署的兵力规模。', 1.0, 'ds_0037d14b',
   '{"metricField": "deployable_count"}', 'SUM(deployable_count)', NOW(), NOW()),
  ('ind_establish_ratio','兵力编现比',   '兵力', 'SUM(present_count)/SUM(establishment)',
   '实际在编人数与编制人数的比值，反映满编程度。', 1.0, 'ds_0037d14b',
   '{"numerator": "present_count", "denominator": "establishment"}', 'SUM(present_count)/SUM(establishment)', NOW(), NOW()),
  ('ind_combat_power',   '区域战备水平', '战备', 'AVG(combat_power)',
   '各区域平均战斗力评分，反映战备水平。', 1.0, 'ds_67804b95',
   '{"metricField": "combat_power"}', 'AVG(combat_power)', NOW(), NOW()),
  ('ind_mobility',       '区域机动能力', '战备', 'AVG(mobility_score)',
   '各区域平均机动能力评分。', 1.0, 'ds_67804b95',
   '{"metricField": "mobility_score"}', 'AVG(mobility_score)', NOW(), NOW()),
  ('ind_personnel',      '兵力部署规模', '部署', 'SUM(personnel_count)',
   '各区域部署人员总数。', 1.0, 'ds_67804b95',
   '{"metricField": "personnel_count"}', 'SUM(personnel_count)', NOW(), NOW()),
  ('ind_equipment',      '装备部署规模', '部署', 'SUM(equipment_count)',
   '各区域部署装备总数。', 1.0, 'ds_67804b95',
   '{"metricField": "equipment_count"}', 'SUM(equipment_count)', NOW(), NOW());

SELECT '  演示指标已插入: ' AS '' ;
SELECT COUNT(*) AS indicator_count FROM `ass_indicator`;
