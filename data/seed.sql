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
