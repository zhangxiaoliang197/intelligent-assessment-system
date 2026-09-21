-- ipage 时间轴回放优化：能力半径收缩（配合 page-kit.js 日内归一化 + 圈绑飞机生命周期）
-- 背景：多架次按"日内归一化"叠加到同一虚拟日后同屏峰值 5-6 架（两两机间距中位 187km），
--       原半径（侦察 280/420km 等）导致所有圈完全重叠、无法分辨；
-- 目标：多数圈独立、临近两圈的侦察/打击带仅部分重叠。
-- 执行：mysql -uroot -p mock_situation < update-radius-day-normalized.sql
-- 生效：无需重启服务（取数侧每次实时读取本表），前端刷新重跑 ipage 问题即可。

USE mock_situation;

-- 蓝方：高空长航时侦察机 侦察半径 280 → 60
UPDATE mock_aircraft_type SET recon_radius_km = 60 WHERE type_id = 'BT-03';

-- 蓝方：空中预警指挥机 侦察半径 420 → 90
UPDATE mock_aircraft_type SET recon_radius_km = 90 WHERE type_id = 'BT-05';

-- 蓝方：一次性攻击无人机 侦察/打击半径 120/120 → 45/45
UPDATE mock_aircraft_type SET recon_radius_km = 45, strike_radius_km = 45 WHERE type_id = 'BT-06';

-- 红方：突击无人机（无人攻击机）侦察/打击半径 80/120 → 30/40
UPDATE mock_aircraft_type SET recon_radius_km = 30, strike_radius_km = 40 WHERE type_id = 'RT-02';

-- 红方：侦察无人机 侦察半径 180 → 50
UPDATE mock_aircraft_type SET recon_radius_km = 50 WHERE type_id = 'RT-03';

-- 校验
SELECT type_id, type_name, faction, recon_radius_km, strike_radius_km FROM mock_aircraft_type;
