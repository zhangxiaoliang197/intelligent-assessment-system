// Generated from MilitaryDatasetSeed.cs — dataset: military-causal-v5
MATCH (n) WHERE n.dataset STARTS WITH 'military-causal-' AND (n:Entity OR n:ActionNode OR n:StateNode) DETACH DELETE n;

CREATE CONSTRAINT aegis_entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT aegis_action_id IF NOT EXISTS FOR (n:ActionNode) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT aegis_state_id IF NOT EXISTS FOR (n:StateNode) REQUIRE n.id IS UNIQUE;

UNWIND [
  { id: 'FORCE-RECON-01', name: '陆军航空兵某侦察中队', ontologyType: 'ForceUnit', operationalRole: 'reconnaissance', staticProps: '{"编制": "2人/单机", "职能": "敌后全域侦察、机动目标跟踪、态势回传", "能力特征": "具备全天候隐蔽作业能力", "数据来源": "机动目标打击因果溯源结构化数据集"}' },
  { id: 'FORCE-FIRE-01', name: '陆军远程火力旅某营', ontologyType: 'ForceUnit', operationalRole: 'firepower', staticProps: '{"编组": "12人", "配置": "发射车、指挥车、弹药补给车各1台", "职能": "远程精准火力打击、快打快撤", "数据来源": "机动目标打击因果溯源结构化数据集"}' },
  { id: 'FORCE-C2-01', name: '前沿机动指挥分队', ontologyType: 'ForceUnit', operationalRole: 'command', staticProps: '{"职能": "多源情报融合、目标研判、任务下发、动态参数修正、态势统筹", "数据来源": "机动目标打击因果溯源结构化数据集"}' },
  { id: 'FORCE-BDA-01', name: '战场效果评估分队', ontologyType: 'ForceUnit', operationalRole: 'assessment', staticProps: '{"职能": "打击后抵近侦察、目标毁伤核验、作战效果判定", "数据来源": "机动目标打击因果溯源结构化数据集"}' },
  { id: 'EQUIP-RECON-UAV-01', name: '中型长航时侦察无人机', ontologyType: 'Equipment', operationalRole: 'reconnaissance', staticProps: '{"最大续航": "32h", "实用升限": "9000m", "侦察半径": "1200km", "传感器": "SAR雷达+光电红外双模吊舱", "动态定位精度": "±1.5m", "坐标更新频率": "1次/秒", "通信": "加密实时通信", "任务适配": "全天候隐蔽侦察与机动目标持续跟踪", "数据来源": "机动目标打击因果溯源结构化数据集"}' },
  { id: 'EQUIP-ROCKET-01', name: '远程箱式火箭炮系统', ontologyType: 'Equipment', operationalRole: 'firepower', staticProps: '{"射程": "50-370km", "圆概率误差": "≤5m", "制导": "卫星+惯性双制导", "机动目标能力": "支持机动目标轨迹修正", "载弹量": "单车8枚", "阵地展开": "8min", "撤收": "6min", "适配弹药": "反车辆侵彻爆破弹药", "任务适配": "快速机动作战、快打快撤", "数据来源": "机动目标打击因果溯源结构化数据集"}' },
  { id: 'EQUIP-C2-SHELTER-01', name: '野战机动指挥方舱系统', ontologyType: 'Equipment', operationalRole: 'command', staticProps: '{"多源数据融合时延": "≤2s", "指令下发时延": "≤1s", "功能": "机动目标轨迹推演、动态坐标校准、全域态势融合研判", "数据来源": "机动目标打击因果溯源结构化数据集"}' },
  { id: 'EQUIP-BDA-UAV-01', name: '近程小型评估无人机', ontologyType: 'Equipment', operationalRole: 'assessment', staticProps: '{"续航": "4h", "作业高度": "1000-3000m", "传感器": "高清可见光+红外成像设备", "功能": "近距离实体状态识别、毁伤细节采集与画面实时回传", "数据来源": "机动目标打击因果溯源结构化数据集"}' },
  { id: 'TARGET-CONVOY-01', name: '敌方前沿机动弹药补给车队', ontologyType: 'Target', operationalRole: 'enemyTarget', staticProps: '{"目标类型": "后勤机动作战单元", "固定编制": "6台车辆（2台弹药运输车、2台油料车、1台指挥通信车、1台防空护卫车）", "在编人员": "28人", "固定载荷": "大口径榴弹、反坦克弹药、迫击炮弹合计65吨；随车单兵防空武器若干", "固有能力": "公路机动、前线弹药补给、基础单兵防空自卫", "防护限制": "无重型装甲、无固定防空阵地", "数据来源": "机动目标打击因果溯源结构化数据集"}' }
] AS row
MERGE (e:Entity {id: row.id})
SET e.name=row.name, e.ontologyType=row.ontologyType, e.operationalRole=row.operationalRole, e.staticProps=row.staticProps, e.canonicalKey=row.id, e.origin='ASSERTED', e.lifecycleStatus='ACTIVE', e.dataset='military-causal-v5';

UNWIND [
  { from: 'FORCE-RECON-01', to: 'EQUIP-RECON-UAV-01' },
  { from: 'FORCE-FIRE-01', to: 'EQUIP-ROCKET-01' },
  { from: 'FORCE-C2-01', to: 'EQUIP-C2-SHELTER-01' },
  { from: 'FORCE-BDA-01', to: 'EQUIP-BDA-UAV-01' }
] AS row
MATCH (a:Entity {id:row.from, dataset:'military-causal-v5'}), (b:Entity {id:row.to, dataset:'military-causal-v5'})
MERGE (a)-[:OPERATES]->(b);

UNWIND [
  { id: 'ACT-T1-01', sequence: 1, timeNode: 1, name: '开机升空、全域巡航扫描', timestamp: 'T0日 08:00', location: '北纬36°21′50″，东经118°33′40″（海拔8500m敌后预设侦察空域）', actionType: 'reconnaissance', actionObject: '鲁中丘陵山区机动目标区域', directResult: '设备工况正常，进入侦察待机模式', isCausalTerminal: false },
  { id: 'ACT-T1-02', sequence: 2, timeNode: 1, name: '阵地值守、装备通电自检、弹药装填待命', timestamp: 'T0日 08:00', location: '北纬36°18′25″，东经118°29′15″（我方后方隐蔽野战阵地）', actionType: 'firepower', actionObject: '无', directResult: '装备状态完好，具备随时接战条件', isCausalTerminal: false },
  { id: 'ACT-T1-03', sequence: 3, timeNode: 1, name: '全域态势值守、系统开机运行', timestamp: 'T0日 08:00', location: '北纬36°19′10″，东经118°30′50″（我方前沿机动指挥点位）', actionType: 'command', actionObject: '全域战场态势', directResult: '情报系统正常待机，等待数据接入', isCausalTerminal: false },
  { id: 'ACT-T1-04', sequence: 4, timeNode: 1, name: '匀速向前线炮兵阵地机动', timestamp: 'T0日 08:00', location: '北纬36°20′15″，东经118°32′30″', actionType: 'enemyTarget', actionObject: '前线作战单元（补给前置机动）', directResult: '正常行军、无异常暴露', isCausalTerminal: false },
  { id: 'ACT-T1-05', sequence: 5, timeNode: 1, name: '地面静置待命', timestamp: 'T0日 08:00', location: '北纬36°18′30″，东经118°29′20″（我方地面待机阵地）', actionType: 'assessment', actionObject: '无', directResult: '设备正常待机', isCausalTerminal: false },
  { id: 'ACT-T2-01', sequence: 6, timeNode: 2, name: '持续扫描、捕获移动热源并锁定机动目标', timestamp: 'T0日 08:00-09:10', location: '北纬36°21′35″，东经118°34′05″（敌后目标空域持续巡航）', actionType: 'reconnaissance', actionObject: '敌方机动弹药补给车队', directResult: '成功锁定机动目标，获取实时轨迹、速度、编队数据，持续回传指挥端', isCausalTerminal: false },
  { id: 'ACT-T2-02', sequence: 7, timeNode: 2, name: '持续匀速机动、无规避、无停车隐蔽', timestamp: 'T0日 08:00-09:10', location: '北纬36°21′20″，东经118°33′50″（沿山区战备公路动态机动）', actionType: 'enemyTarget', actionObject: '无', directResult: '自身机动特征完全暴露，未感知我方侦察', isCausalTerminal: false },
  { id: 'ACT-T3-01', sequence: 8, timeNode: 3, name: '融合多源数据、甄别目标属性并完成目标研判', timestamp: 'T0日 09:10-09:35', location: '北纬36°19′10″，东经118°30′50″（我方前沿指挥点位）', actionType: 'command', actionObject: '敌方机动弹药补给车队侦察数据', directResult: '100%确认目标身份，判定为最高价值打击目标，形成动态打击决策方案', isCausalTerminal: false },
  { id: 'ACT-T3-02', sequence: 9, timeNode: 3, name: '持续向前线机动', timestamp: 'T0日 09:10-09:35', location: '北纬36°21′45″，东经118°34′20″（山区战备公路中段）', actionType: 'enemyTarget', actionObject: '无', directResult: '行驶轨迹稳定，未改变机动路线', isCausalTerminal: false },
  { id: 'ACT-T3-03', sequence: 10, timeNode: 3, name: '持续跟踪目标并稳定回传数据', timestamp: 'T0日 09:10-09:35', location: '文档未重复给出独立坐标（沿用持续巡航跟踪场景）', actionType: 'reconnaissance', actionObject: '敌方机动弹药补给车队', directResult: '稳定回传目标动态数据，侦察状态无变更', isCausalTerminal: false },
  { id: 'ACT-T4-01', sequence: 11, timeNode: 4, name: '下发机动目标动态打击指令', timestamp: 'T0日 09:35-10:00', location: '北纬36°19′10″，东经118°30′50″（我方前沿指挥点位）', actionType: 'command', actionObject: '远程火力打击单元', directResult: '推送目标实时坐标、轨迹修正参数、打击弹种、作战预案，建立动态目标参数联动链路', isCausalTerminal: false },
  { id: 'ACT-T4-02', sequence: 12, timeNode: 4, name: '接收作战指令并完成战前筹备、参数装订与阵地校准', timestamp: 'T0日 09:35-10:00', location: '北纬36°18′25″，东经118°29′15″（后方隐蔽野战阵地）', actionType: 'firepower', actionObject: '作战任务指令、机动目标参数', directResult: '装备自检、机动目标轨迹参数装订、4枚侵彻爆破弹装填、阵地校准全部完成', isCausalTerminal: false },
  { id: 'ACT-T4-03', sequence: 13, timeNode: 4, name: '匀速机动、无战术规避', timestamp: 'T0日 09:35-10:00', location: '北纬36°22′00″，东经118°34′45″（山区战备公路火力打击窗口区域）', actionType: 'enemyTarget', actionObject: '无', directResult: '进入我方火力最佳打击区间', isCausalTerminal: false },
  { id: 'ACT-T4-04', sequence: 14, timeNode: 4, name: '持续跟踪锁定并回传目标动态', timestamp: 'T0日 09:35-10:00', location: '文档未重复给出独立坐标（沿用持续巡航跟踪场景）', actionType: 'reconnaissance', actionObject: '敌方机动弹药补给车队', directResult: '持续提供机动目标动态数据', isCausalTerminal: false },
  { id: 'ACT-T5-01', sequence: 15, timeNode: 5, name: '实时修正目标机动坐标并下发开火终极指令', timestamp: 'T0日 10:00-10:07', location: '北纬36°19′10″，东经118°30′50″（我方前沿指挥点位）', actionType: 'command', actionObject: '远程火箭炮单元、机动目标动态轨迹', directResult: '完成打击参数最后校准，授权开火', isCausalTerminal: false },
  { id: 'ACT-T5-02', sequence: 16, timeNode: 5, name: '依据动态轨迹提前量发射4枚高精度制导弹药', timestamp: 'T0日 10:00-10:07', location: '北纬36°18′25″，东经118°29′15″（后方隐蔽野战阵地）', actionType: 'firepower', actionObject: '敌方机动弹药补给车队', directResult: '弹药正常发射、精准奔袭目标区域', isCausalTerminal: false },
  { id: 'ACT-T5-03', sequence: 17, timeNode: 5, name: '正常机动行驶', timestamp: 'T0日 10:00-10:07', location: '北纬36°21′02″，东经118°34′16″', actionType: 'enemyTarget', actionObject: '无', directResult: '机动过程中进入弹药命中阶段', isCausalTerminal: false },
  { id: 'ACT-T5-04', sequence: 18, timeNode: 5, name: '弹药精准命中编队核心并引发车载弹药殉爆', timestamp: 'T0日 10:00-10:07', location: '北纬36°21′02″，东经118°34′16″', actionType: 'effect', actionObject: '敌方机动弹药补给车队', directResult: '核心车辆损毁、人员伤亡、部分弹药销毁；随后目标机动、补给、自卫与作战能力归零', isCausalTerminal: true },
  { id: 'ACT-T6-01', sequence: 19, timeNode: 6, name: '停止射击并启动战后撤收流程', timestamp: 'T0日 10:07-10:08', location: '北纬36°18′25″，东经118°29′15″（原野战阵地）', actionType: 'firepower', actionObject: '自身作战阵地', directResult: '射击任务完成，进入撤离准备状态', isCausalTerminal: false },
  { id: 'ACT-T7-01', sequence: 20, timeNode: 7, name: '6分钟快速撤收、阵地转移、战术撤离', timestamp: 'T0日 10:08-10:25', location: '北纬36°18′25″，东经118°29′15″ → 北纬36°18′10″，东经118°28′55″（机动转移途中）', actionType: 'firepower', actionObject: '自身作战编组', directResult: '成功脱离作战阵地，规避敌方反击风险', isCausalTerminal: false },
  { id: 'ACT-T7-02', sequence: 21, timeNode: 7, name: '升空抵近侦察并核查目标损毁状态', timestamp: 'T0日 10:08-10:25', location: '北纬36°18′30″，东经118°29′20″ → 北纬36°21′02″，东经118°34′16″（目标上空抵近区域）', actionType: 'assessment', actionObject: '敌方损毁机动车队', directResult: '核验目标完全损毁、无残余作战能力并实时回传战场画面', isCausalTerminal: false },
  { id: 'ACT-T7-03', sequence: 22, timeNode: 7, name: '接收评估数据、核验作战效果并闭环作战任务', timestamp: 'T0日 10:08-10:25', location: '北纬36°19′10″，东经118°30′50″（我方前沿指挥点位）', actionType: 'command', actionObject: '战场评估数据、作战任务', directResult: '确认打击任务全额达成，更新战场全局态势', isCausalTerminal: false }
] AS row
MERGE (a:ActionNode {id:row.id})
SET a.sequence=row.sequence, a.timeNode=row.timeNode, a.name=row.name, a.timestamp=row.timestamp, a.location=row.location, a.actionType=row.actionType, a.actionObject=row.actionObject, a.directResult=row.directResult, a.isCausalTerminal=row.isCausalTerminal, a.origin='ASSERTED', a.lifecycleStatus='ACTIVE', a.dataset='military-causal-v5';

UNWIND [
  { action: 'ACT-T1-01', entity: 'EQUIP-RECON-UAV-01' },
  { action: 'ACT-T1-02', entity: 'FORCE-FIRE-01' },
  { action: 'ACT-T1-02', entity: 'EQUIP-ROCKET-01' },
  { action: 'ACT-T1-03', entity: 'FORCE-C2-01' },
  { action: 'ACT-T1-03', entity: 'EQUIP-C2-SHELTER-01' },
  { action: 'ACT-T1-04', entity: 'TARGET-CONVOY-01' },
  { action: 'ACT-T1-05', entity: 'EQUIP-BDA-UAV-01' },
  { action: 'ACT-T2-01', entity: 'FORCE-RECON-01' },
  { action: 'ACT-T2-01', entity: 'EQUIP-RECON-UAV-01' },
  { action: 'ACT-T2-02', entity: 'TARGET-CONVOY-01' },
  { action: 'ACT-T3-01', entity: 'FORCE-C2-01' },
  { action: 'ACT-T3-01', entity: 'EQUIP-C2-SHELTER-01' },
  { action: 'ACT-T3-02', entity: 'TARGET-CONVOY-01' },
  { action: 'ACT-T3-03', entity: 'EQUIP-RECON-UAV-01' },
  { action: 'ACT-T4-01', entity: 'FORCE-C2-01' },
  { action: 'ACT-T4-02', entity: 'FORCE-FIRE-01' },
  { action: 'ACT-T4-02', entity: 'EQUIP-ROCKET-01' },
  { action: 'ACT-T4-03', entity: 'TARGET-CONVOY-01' },
  { action: 'ACT-T4-04', entity: 'EQUIP-RECON-UAV-01' },
  { action: 'ACT-T5-01', entity: 'FORCE-C2-01' },
  { action: 'ACT-T5-02', entity: 'FORCE-FIRE-01' },
  { action: 'ACT-T5-02', entity: 'EQUIP-ROCKET-01' },
  { action: 'ACT-T5-03', entity: 'TARGET-CONVOY-01' },
  { action: 'ACT-T6-01', entity: 'FORCE-FIRE-01' },
  { action: 'ACT-T6-01', entity: 'EQUIP-ROCKET-01' },
  { action: 'ACT-T7-01', entity: 'FORCE-FIRE-01' },
  { action: 'ACT-T7-01', entity: 'EQUIP-ROCKET-01' },
  { action: 'ACT-T7-02', entity: 'FORCE-BDA-01' },
  { action: 'ACT-T7-02', entity: 'EQUIP-BDA-UAV-01' },
  { action: 'ACT-T7-03', entity: 'FORCE-C2-01' }
] AS row

MATCH (e:Entity {id:row.entity, dataset:'military-causal-v5'}), (a:ActionNode {id:row.action, dataset:'military-causal-v5'})
MERGE (e)-[:PERFORMS]->(a);

UNWIND [
  { action: 'ACT-T2-01', entity: 'TARGET-CONVOY-01' },
  { action: 'ACT-T3-01', entity: 'TARGET-CONVOY-01' },
  { action: 'ACT-T3-03', entity: 'TARGET-CONVOY-01' },
  { action: 'ACT-T4-04', entity: 'TARGET-CONVOY-01' },
  { action: 'ACT-T5-01', entity: 'TARGET-CONVOY-01' },
  { action: 'ACT-T5-02', entity: 'TARGET-CONVOY-01' },
  { action: 'ACT-T5-04', entity: 'TARGET-CONVOY-01' },
  { action: 'ACT-T7-02', entity: 'TARGET-CONVOY-01' }
] AS row

MATCH (a:ActionNode {id:row.action, dataset:'military-causal-v5'}), (e:Entity {id:row.entity, dataset:'military-causal-v5'})
MERGE (a)-[:TARGETS]->(e);

UNWIND [
  { action: 'ACT-T4-01', entity: 'FORCE-FIRE-01' },
  { action: 'ACT-T5-01', entity: 'FORCE-FIRE-01' }
] AS row

MATCH (a:ActionNode {id:row.action, dataset:'military-causal-v5'}), (e:Entity {id:row.entity, dataset:'military-causal-v5'})
MERGE (a)-[:DIRECTED_TO]->(e);

UNWIND [
  { id: 'STATE-FORCE-RECON-01-01', entityId: 'FORCE-RECON-01', sequence: 1, timestamp: 'T0日 08:00', location: '文档未单列侦察部队独立位置', action: '文档未单列侦察部队独立行动；其操作装备执行开机升空与全域巡航扫描', actionObject: '无独立记录', directResult: '无独立结果记录', updatedState: '侦察任务保障状态（由静态职能与后续联合记录可知）', sourceBasis: 'not-explicitly-recorded', latitude: null, longitude: null },
  { id: 'STATE-FORCE-RECON-01-02', entityId: 'FORCE-RECON-01', sequence: 2, timestamp: 'T0日 08:00-09:10', location: '北纬36°21′35″，东经118°34′05″（源记录为侦察部队+侦察无人机联合实体）', action: 'SAR雷达+红外吊舱持续扫描，捕获移动热源与车辆轨迹，识别车队编队特征，每秒更新目标坐标', actionObject: '敌方机动弹药补给车队', directResult: '成功锁定机动目标，获取实时轨迹、速度、编队数据，持续回传指挥端', updatedState: '目标锁定、持续跟踪、动态数据输出状态', sourceBasis: 'joint-explicit-record', latitude: 36.359722, longitude: 118.568056 },
  { id: 'STATE-FORCE-RECON-01-03', entityId: 'FORCE-RECON-01', sequence: 3, timestamp: 'T0日 09:10-09:35', location: '文档未单列侦察部队独立位置', action: '文档仅明确侦察无人机持续跟踪；侦察部队独立行动未单列', actionObject: '敌方机动弹药补给车队', directResult: '无独立结果记录', updatedState: '沿用联合记录中的持续侦察任务状态', sourceBasis: 'carried-forward', latitude: null, longitude: null },
  { id: 'STATE-FORCE-RECON-01-04', entityId: 'FORCE-RECON-01', sequence: 4, timestamp: 'T0日 09:35-10:00', location: '文档未单列侦察部队独立位置', action: '文档仅明确侦察无人机持续跟踪锁定；侦察部队独立行动未单列', actionObject: '敌方机动弹药补给车队', directResult: '无独立结果记录', updatedState: '沿用持续侦察任务状态', sourceBasis: 'carried-forward', latitude: null, longitude: null },
  { id: 'STATE-FORCE-RECON-01-05', entityId: 'FORCE-RECON-01', sequence: 5, timestamp: 'T0日 10:00-10:07', location: '文档未单列', action: '文档未单列新增行动', actionObject: '无独立记录', directResult: '无新增直接结果', updatedState: '沿用持续侦察任务状态', sourceBasis: 'not-explicitly-recorded', latitude: null, longitude: null },
  { id: 'STATE-FORCE-RECON-01-06', entityId: 'FORCE-RECON-01', sequence: 6, timestamp: 'T0日 10:07-10:08', location: '文档未单列', action: '文档未单列新增行动', actionObject: '无独立记录', directResult: '无新增直接结果', updatedState: '沿用上一节点状态', sourceBasis: 'not-explicitly-recorded', latitude: null, longitude: null },
  { id: 'STATE-FORCE-RECON-01-07', entityId: 'FORCE-RECON-01', sequence: 7, timestamp: 'T0日 10:08-10:25', location: '文档未单列', action: '文档未单列新增行动', actionObject: '无独立记录', directResult: '无新增直接结果', updatedState: '沿用上一节点状态', sourceBasis: 'not-explicitly-recorded', latitude: null, longitude: null },
  { id: 'STATE-EQUIP-RECON-UAV-01-01', entityId: 'EQUIP-RECON-UAV-01', sequence: 1, timestamp: 'T0日 08:00', location: '北纬36°21′50″，东经118°33′40″（海拔8500m敌后预设侦察空域）', action: '开机升空、全域巡航扫描', actionObject: '鲁中丘陵山区机动目标区域', directResult: '设备工况正常，进入侦察待机模式', updatedState: '空域隐蔽巡航、待机侦察（无目标锁定）', sourceBasis: 'explicit-record', latitude: 36.363889, longitude: 118.561111 },
  { id: 'STATE-EQUIP-RECON-UAV-01-02', entityId: 'EQUIP-RECON-UAV-01', sequence: 2, timestamp: 'T0日 08:00-09:10', location: '北纬36°21′35″，东经118°34′05″（敌后目标空域持续巡航）', action: 'SAR雷达+红外吊舱持续扫描，捕获移动热源与车辆轨迹，识别车队编队特征，每秒更新目标坐标', actionObject: '敌方机动弹药补给车队', directResult: '成功锁定机动目标，获取实时轨迹、速度、编队数据，持续回传指挥端', updatedState: '目标锁定、持续跟踪、动态数据输出状态', sourceBasis: 'joint-explicit-record', latitude: 36.359722, longitude: 118.568056 },
  { id: 'STATE-EQUIP-RECON-UAV-01-03', entityId: 'EQUIP-RECON-UAV-01', sequence: 3, timestamp: 'T0日 09:10-09:35', location: '文档未重复给出坐标（持续跟踪场景）', action: '持续跟踪目标，稳定回传数据', actionObject: '敌方机动弹药补给车队', directResult: '稳定回传数据', updatedState: '目标锁定、持续跟踪、动态数据输出状态', sourceBasis: 'explicit-record', latitude: null, longitude: null },
  { id: 'STATE-EQUIP-RECON-UAV-01-04', entityId: 'EQUIP-RECON-UAV-01', sequence: 4, timestamp: 'T0日 09:35-10:00', location: '文档未重复给出坐标（持续跟踪场景）', action: '持续跟踪锁定', actionObject: '敌方机动弹药补给车队', directResult: '持续提供目标动态信息', updatedState: '目标锁定、持续跟踪、动态数据输出状态', sourceBasis: 'explicit-record', latitude: null, longitude: null },
  { id: 'STATE-EQUIP-RECON-UAV-01-05', entityId: 'EQUIP-RECON-UAV-01', sequence: 5, timestamp: 'T0日 10:00-10:07', location: '文档未单列', action: '文档未单列新增行动；沿用前序持续跟踪任务状态', actionObject: '敌方机动弹药补给车队', directResult: '无新增直接结果', updatedState: '目标锁定、持续跟踪、动态数据输出状态', sourceBasis: 'carried-forward', latitude: null, longitude: null },
  { id: 'STATE-EQUIP-RECON-UAV-01-06', entityId: 'EQUIP-RECON-UAV-01', sequence: 6, timestamp: 'T0日 10:07-10:08', location: '文档未单列', action: '文档未单列新增行动', actionObject: '无独立记录', directResult: '无新增直接结果', updatedState: '沿用上一节点状态', sourceBasis: 'not-explicitly-recorded', latitude: null, longitude: null },
  { id: 'STATE-EQUIP-RECON-UAV-01-07', entityId: 'EQUIP-RECON-UAV-01', sequence: 7, timestamp: 'T0日 10:08-10:25', location: '文档未单列', action: '文档未单列新增行动', actionObject: '无独立记录', directResult: '无新增直接结果', updatedState: '沿用上一节点状态', sourceBasis: 'not-explicitly-recorded', latitude: null, longitude: null },
  { id: 'STATE-FORCE-FIRE-01-01', entityId: 'FORCE-FIRE-01', sequence: 1, timestamp: 'T0日 08:00', location: '北纬36°18′25″，东经118°29′15″（我方后方隐蔽野战阵地）', action: '阵地值守、装备通电自检、弹药装填待命', actionObject: '无', directResult: '装备状态完好，具备随时接战条件', updatedState: '阵地待机、未装订参数、待击待命', sourceBasis: 'joint-explicit-record', latitude: 36.306944, longitude: 118.4875 },
  { id: 'STATE-FORCE-FIRE-01-02', entityId: 'FORCE-FIRE-01', sequence: 2, timestamp: 'T0日 08:00-09:10', location: '沿用T1野战阵地', action: '保持原有待机状态，无新增行动', actionObject: '无', directResult: '状态无变化', updatedState: '阵地待机、未装订参数、待击待命', sourceBasis: 'aggregate-unchanged-record', latitude: 36.306944, longitude: 118.4875 },
  { id: 'STATE-FORCE-FIRE-01-03', entityId: 'FORCE-FIRE-01', sequence: 3, timestamp: 'T0日 09:10-09:35', location: '沿用T1野战阵地', action: '保持待机状态', actionObject: '无', directResult: '状态无变化', updatedState: '阵地待机、未装订参数、待击待命', sourceBasis: 'aggregate-unchanged-record', latitude: 36.306944, longitude: 118.4875 },
  { id: 'STATE-FORCE-FIRE-01-04', entityId: 'FORCE-FIRE-01', sequence: 4, timestamp: 'T0日 09:35-10:00', location: '北纬36°18′25″，东经118°29′15″（后方隐蔽野战阵地）', action: '接收作战指令，完成装备自检、机动目标轨迹参数装订、4枚侵彻爆破弹装填、阵地校准', actionObject: '作战任务指令、机动目标参数', directResult: '战前筹备全部完成，可实时修正打击参数', updatedState: '备战待击、参数装订完成、随时可开火', sourceBasis: 'joint-explicit-record', latitude: 36.306944, longitude: 118.4875 },
  { id: 'STATE-FORCE-FIRE-01-05', entityId: 'FORCE-FIRE-01', sequence: 5, timestamp: 'T0日 10:00-10:07', location: '北纬36°18′25″，东经118°29′15″（后方隐蔽野战阵地）', action: '依据动态轨迹提前量，发射4枚高精度制导弹药', actionObject: '敌方机动弹药补给车队', directResult: '弹药正常发射、精准奔袭目标区域', updatedState: '射击执行状态、火力输出完成', sourceBasis: 'joint-explicit-record', latitude: 36.306944, longitude: 118.4875 },
  { id: 'STATE-FORCE-FIRE-01-06', entityId: 'FORCE-FIRE-01', sequence: 6, timestamp: 'T0日 10:07-10:08', location: '北纬36°18′25″，东经118°29′15″（原野战阵地）', action: '停止射击，启动战后撤收流程', actionObject: '自身作战阵地', directResult: '射击任务完成，进入撤离准备状态', updatedState: '射击完成、待撤离状态', sourceBasis: 'joint-explicit-record', latitude: 36.306944, longitude: 118.4875 },
  { id: 'STATE-FORCE-FIRE-01-07', entityId: 'FORCE-FIRE-01', sequence: 7, timestamp: 'T0日 10:08-10:25', location: '北纬36°18′25″，东经118°29′15″ → 北纬36°18′10″，东经118°28′55″（机动转移途中）', action: '6分钟快速撤收、阵地转移、战术撤离', actionObject: '自身作战编组', directResult: '成功脱离作战阵地，规避敌方反击风险', updatedState: '安全机动转移、作战任务阶段性完成', sourceBasis: 'joint-explicit-record', latitude: 36.302778, longitude: 118.481944 },
  { id: 'STATE-EQUIP-ROCKET-01-01', entityId: 'EQUIP-ROCKET-01', sequence: 1, timestamp: 'T0日 08:00', location: '北纬36°18′25″，东经118°29′15″（我方后方隐蔽野战阵地）', action: '阵地值守、装备通电自检、弹药装填待命', actionObject: '无', directResult: '装备状态完好，具备随时接战条件', updatedState: '阵地待机、未装订参数、待击待命', sourceBasis: 'joint-explicit-record', latitude: 36.306944, longitude: 118.4875 },
  { id: 'STATE-EQUIP-ROCKET-01-02', entityId: 'EQUIP-ROCKET-01', sequence: 2, timestamp: 'T0日 08:00-09:10', location: '沿用T1野战阵地', action: '保持原有待机状态，无新增行动', actionObject: '无', directResult: '状态无变化', updatedState: '阵地待机、未装订参数、待击待命', sourceBasis: 'aggregate-unchanged-record', latitude: 36.306944, longitude: 118.4875 },
  { id: 'STATE-EQUIP-ROCKET-01-03', entityId: 'EQUIP-ROCKET-01', sequence: 3, timestamp: 'T0日 09:10-09:35', location: '沿用T1野战阵地', action: '保持待机状态', actionObject: '无', directResult: '状态无变化', updatedState: '阵地待机、未装订参数、待击待命', sourceBasis: 'aggregate-unchanged-record', latitude: 36.306944, longitude: 118.4875 },
  { id: 'STATE-EQUIP-ROCKET-01-04', entityId: 'EQUIP-ROCKET-01', sequence: 4, timestamp: 'T0日 09:35-10:00', location: '北纬36°18′25″，东经118°29′15″（后方隐蔽野战阵地）', action: '接收作战指令，完成装备自检、机动目标轨迹参数装订、4枚侵彻爆破弹装填、阵地校准', actionObject: '作战任务指令、机动目标参数', directResult: '战前筹备全部完成，可实时修正打击参数', updatedState: '备战待击、参数装订完成、随时可开火', sourceBasis: 'joint-explicit-record', latitude: 36.306944, longitude: 118.4875 },
  { id: 'STATE-EQUIP-ROCKET-01-05', entityId: 'EQUIP-ROCKET-01', sequence: 5, timestamp: 'T0日 10:00-10:07', location: '北纬36°18′25″，东经118°29′15″（后方隐蔽野战阵地）', action: '依据动态轨迹提前量，发射4枚高精度制导弹药', actionObject: '敌方机动弹药补给车队', directResult: '弹药正常发射、精准奔袭目标区域', updatedState: '射击执行状态、火力输出完成', sourceBasis: 'joint-explicit-record', latitude: 36.306944, longitude: 118.4875 },
  { id: 'STATE-EQUIP-ROCKET-01-06', entityId: 'EQUIP-ROCKET-01', sequence: 6, timestamp: 'T0日 10:07-10:08', location: '北纬36°18′25″，东经118°29′15″（原野战阵地）', action: '停止射击，启动战后撤收流程', actionObject: '自身作战阵地', directResult: '射击任务完成，进入撤离准备状态', updatedState: '射击完成、待撤离状态', sourceBasis: 'joint-explicit-record', latitude: 36.306944, longitude: 118.4875 },
  { id: 'STATE-EQUIP-ROCKET-01-07', entityId: 'EQUIP-ROCKET-01', sequence: 7, timestamp: 'T0日 10:08-10:25', location: '北纬36°18′25″，东经118°29′15″ → 北纬36°18′10″，东经118°28′55″（机动转移途中）', action: '6分钟快速撤收、阵地转移、战术撤离', actionObject: '自身作战编组', directResult: '成功脱离作战阵地，规避敌方反击风险', updatedState: '安全机动转移、作战任务阶段性完成', sourceBasis: 'joint-explicit-record', latitude: 36.302778, longitude: 118.481944 },
  { id: 'STATE-FORCE-C2-01-01', entityId: 'FORCE-C2-01', sequence: 1, timestamp: 'T0日 08:00', location: '北纬36°19′10″，东经118°30′50″（我方前沿机动指挥点位）', action: '全域态势值守、系统开机运行', actionObject: '全域战场态势', directResult: '情报系统正常待机，等待数据接入', updatedState: '常态值守、无作战任务', sourceBasis: 'joint-explicit-record', latitude: 36.319444, longitude: 118.513889 },
  { id: 'STATE-FORCE-C2-01-02', entityId: 'FORCE-C2-01', sequence: 2, timestamp: 'T0日 08:00-09:10', location: '沿用T1前沿机动指挥点位', action: '保持原有待机、值守状态，无新增行动', actionObject: '无', directResult: '无状态变化', updatedState: '常态值守、无作战任务', sourceBasis: 'aggregate-unchanged-record', latitude: 36.319444, longitude: 118.513889 },
  { id: 'STATE-FORCE-C2-01-03', entityId: 'FORCE-C2-01', sequence: 3, timestamp: 'T0日 09:10-09:35', location: '北纬36°19′10″，东经118°30′50″（我方前沿指挥点位）', action: '融合无人机、卫星多源数据，甄别目标属性，推演机动轨迹，研判作战价值，确认打击优先级', actionObject: '敌方机动弹药补给车队侦察数据', directResult: '100%确认目标身份，判定为最高价值打击目标，形成动态打击决策方案', updatedState: '专项任务研判状态、任务方案生成完成', sourceBasis: 'joint-explicit-record', latitude: 36.319444, longitude: 118.513889 },
  { id: 'STATE-FORCE-C2-01-04', entityId: 'FORCE-C2-01', sequence: 4, timestamp: 'T0日 09:35-10:00', location: '北纬36°19′10″，东经118°30′50″（我方前沿指挥点位）', action: '下发机动目标动态打击指令，推送目标实时坐标、轨迹修正参数、打击弹种、作战预案', actionObject: '远程火力打击单元', directResult: '打击任务成功下发，建立动态目标参数联动链路', updatedState: '任务指挥状态、实时监控目标动态', sourceBasis: 'explicit-record', latitude: 36.319444, longitude: 118.513889 },
  { id: 'STATE-FORCE-C2-01-05', entityId: 'FORCE-C2-01', sequence: 5, timestamp: 'T0日 10:00-10:07', location: '北纬36°19′10″，东经118°30′50″（我方前沿指挥点位）', action: '实时修正目标机动坐标，下发开火终极指令', actionObject: '远程火箭炮单元、机动目标动态轨迹', directResult: '完成打击参数最后校准，授权开火', updatedState: '实时作战指挥状态', sourceBasis: 'explicit-record', latitude: 36.319444, longitude: 118.513889 },
  { id: 'STATE-FORCE-C2-01-06', entityId: 'FORCE-C2-01', sequence: 6, timestamp: 'T0日 10:07-10:08', location: '沿用前沿机动指挥点位', action: '文档未单列新增行动', actionObject: '无', directResult: '无新增直接结果', updatedState: '沿用实时作战指挥状态', sourceBasis: 'not-explicitly-recorded', latitude: 36.319444, longitude: 118.513889 },
  { id: 'STATE-FORCE-C2-01-07', entityId: 'FORCE-C2-01', sequence: 7, timestamp: 'T0日 10:08-10:25', location: '北纬36°19′10″，东经118°30′50″（我方前沿指挥点位）', action: '接收评估数据，核验作战效果，闭环作战任务', actionObject: '战场评估数据、作战任务', directResult: '确认打击任务全额达成，更新战场全局态势', updatedState: '任务闭环、态势更新完成、回归常态值守', sourceBasis: 'explicit-record', latitude: 36.319444, longitude: 118.513889 },
  { id: 'STATE-EQUIP-C2-SHELTER-01-01', entityId: 'EQUIP-C2-SHELTER-01', sequence: 1, timestamp: 'T0日 08:00', location: '北纬36°19′10″，东经118°30′50″（我方前沿机动指挥点位）', action: '全域态势值守、系统开机运行', actionObject: '全域战场态势', directResult: '情报系统正常待机，等待数据接入', updatedState: '常态值守、无作战任务', sourceBasis: 'joint-explicit-record', latitude: 36.319444, longitude: 118.513889 },
  { id: 'STATE-EQUIP-C2-SHELTER-01-02', entityId: 'EQUIP-C2-SHELTER-01', sequence: 2, timestamp: 'T0日 08:00-09:10', location: '沿用T1前沿机动指挥点位', action: '保持原有待机、值守状态，无新增行动', actionObject: '无', directResult: '无状态变化', updatedState: '常态值守、无作战任务', sourceBasis: 'aggregate-unchanged-record', latitude: 36.319444, longitude: 118.513889 },
  { id: 'STATE-EQUIP-C2-SHELTER-01-03', entityId: 'EQUIP-C2-SHELTER-01', sequence: 3, timestamp: 'T0日 09:10-09:35', location: '北纬36°19′10″，东经118°30′50″（我方前沿指挥点位）', action: '融合无人机、卫星多源数据，甄别目标属性，推演机动轨迹，研判作战价值，确认打击优先级', actionObject: '敌方机动弹药补给车队侦察数据', directResult: '100%确认目标身份并形成动态打击决策方案', updatedState: '专项任务研判状态、任务方案生成完成', sourceBasis: 'joint-explicit-record', latitude: 36.319444, longitude: 118.513889 },
  { id: 'STATE-EQUIP-C2-SHELTER-01-04', entityId: 'EQUIP-C2-SHELTER-01', sequence: 4, timestamp: 'T0日 09:35-10:00', location: '沿用前沿机动指挥点位', action: '文档未将方舱作为独立行动主体单列；系统作为指挥部队所操作装备持续提供支撑', actionObject: '无独立记录', directResult: '无独立结果记录', updatedState: '沿用专项任务支撑状态', sourceBasis: 'carried-forward', latitude: 36.319444, longitude: 118.513889 },
  { id: 'STATE-EQUIP-C2-SHELTER-01-05', entityId: 'EQUIP-C2-SHELTER-01', sequence: 5, timestamp: 'T0日 10:00-10:07', location: '沿用前沿机动指挥点位', action: '文档未将方舱作为独立行动主体单列；持续支撑动态坐标校准与指令下发', actionObject: '无独立记录', directResult: '无独立结果记录', updatedState: '作战指挥系统支撑状态', sourceBasis: 'carried-forward', latitude: 36.319444, longitude: 118.513889 },
  { id: 'STATE-EQUIP-C2-SHELTER-01-06', entityId: 'EQUIP-C2-SHELTER-01', sequence: 6, timestamp: 'T0日 10:07-10:08', location: '沿用前沿机动指挥点位', action: '文档未单列新增行动', actionObject: '无', directResult: '无新增直接结果', updatedState: '沿用作战指挥系统支撑状态', sourceBasis: 'not-explicitly-recorded', latitude: 36.319444, longitude: 118.513889 },
  { id: 'STATE-EQUIP-C2-SHELTER-01-07', entityId: 'EQUIP-C2-SHELTER-01', sequence: 7, timestamp: 'T0日 10:08-10:25', location: '沿用前沿机动指挥点位', action: '文档未将方舱作为独立行动主体单列；随指挥分队完成任务闭环', actionObject: '无独立记录', directResult: '无独立结果记录', updatedState: '回归常态系统支撑状态', sourceBasis: 'carried-forward', latitude: 36.319444, longitude: 118.513889 },
  { id: 'STATE-FORCE-BDA-01-01', entityId: 'FORCE-BDA-01', sequence: 1, timestamp: 'T0日 08:00', location: '文档未单列评估部队独立位置', action: '文档仅明确近程小型评估无人机地面待机；评估部队独立行动未单列', actionObject: '无独立记录', directResult: '无独立结果记录', updatedState: '评估任务待命状态', sourceBasis: 'not-explicitly-recorded', latitude: null, longitude: null },
  { id: 'STATE-FORCE-BDA-01-02', entityId: 'FORCE-BDA-01', sequence: 2, timestamp: 'T0日 08:00-09:10', location: '文档未单列独立位置', action: '其余我方实体保持原有待机、值守状态', actionObject: '无', directResult: '无状态变化', updatedState: '评估任务待命状态', sourceBasis: 'aggregate-unchanged-record', latitude: null, longitude: null },
  { id: 'STATE-FORCE-BDA-01-03', entityId: 'FORCE-BDA-01', sequence: 3, timestamp: 'T0日 09:10-09:35', location: '文档未单列独立位置', action: '文档仅明确评估无人机保持待机；评估部队独立行动未单列', actionObject: '无', directResult: '无状态变化', updatedState: '评估任务待命状态', sourceBasis: 'carried-forward', latitude: null, longitude: null },
  { id: 'STATE-FORCE-BDA-01-04', entityId: 'FORCE-BDA-01', sequence: 4, timestamp: 'T0日 09:35-10:00', location: '文档未单列', action: '文档未单列新增行动', actionObject: '无', directResult: '无新增直接结果', updatedState: '沿用评估任务待命状态', sourceBasis: 'not-explicitly-recorded', latitude: null, longitude: null },
  { id: 'STATE-FORCE-BDA-01-05', entityId: 'FORCE-BDA-01', sequence: 5, timestamp: 'T0日 10:00-10:07', location: '文档未单列', action: '文档未单列新增行动', actionObject: '无', directResult: '无新增直接结果', updatedState: '沿用评估任务待命状态', sourceBasis: 'not-explicitly-recorded', latitude: null, longitude: null },
  { id: 'STATE-FORCE-BDA-01-06', entityId: 'FORCE-BDA-01', sequence: 6, timestamp: 'T0日 10:07-10:08', location: '文档未单列', action: '文档未单列新增行动', actionObject: '无', directResult: '无新增直接结果', updatedState: '沿用评估任务待命状态', sourceBasis: 'not-explicitly-recorded', latitude: null, longitude: null },
  { id: 'STATE-FORCE-BDA-01-07', entityId: 'FORCE-BDA-01', sequence: 7, timestamp: 'T0日 10:08-10:25', location: '北纬36°18′30″，东经118°29′20″ → 北纬36°21′02″，东经118°34′16″（源记录为评估部队+评估无人机联合实体）', action: '升空抵近侦察，高清核查目标损毁状态，实时回传战场画面', actionObject: '敌方损毁机动车队', directResult: '核验目标完全损毁、无残余作战能力', updatedState: '空中评估作业、态势采集状态', sourceBasis: 'joint-explicit-record', latitude: 36.350556, longitude: 118.571111 },
  { id: 'STATE-EQUIP-BDA-UAV-01-01', entityId: 'EQUIP-BDA-UAV-01', sequence: 1, timestamp: 'T0日 08:00', location: '北纬36°18′30″，东经118°29′20″（我方地面待机阵地）', action: '地面静置待命', actionObject: '无', directResult: '设备正常待机', updatedState: '地面待机、未升空', sourceBasis: 'explicit-record', latitude: 36.308333, longitude: 118.488889 },
  { id: 'STATE-EQUIP-BDA-UAV-01-02', entityId: 'EQUIP-BDA-UAV-01', sequence: 2, timestamp: 'T0日 08:00-09:10', location: '沿用T1地面待机阵地', action: '保持原有待机状态，无新增行动', actionObject: '无', directResult: '状态无变化', updatedState: '地面待机、未升空', sourceBasis: 'aggregate-unchanged-record', latitude: 36.308333, longitude: 118.488889 },
  { id: 'STATE-EQUIP-BDA-UAV-01-03', entityId: 'EQUIP-BDA-UAV-01', sequence: 3, timestamp: 'T0日 09:10-09:35', location: '沿用T1地面待机阵地', action: '保持待机状态', actionObject: '无', directResult: '状态无变化', updatedState: '地面待机、未升空', sourceBasis: 'explicit-record', latitude: 36.308333, longitude: 118.488889 },
  { id: 'STATE-EQUIP-BDA-UAV-01-04', entityId: 'EQUIP-BDA-UAV-01', sequence: 4, timestamp: 'T0日 09:35-10:00', location: '沿用地面待机阵地', action: '文档未单列新增行动', actionObject: '无', directResult: '无新增直接结果', updatedState: '地面待机、未升空', sourceBasis: 'carried-forward', latitude: 36.308333, longitude: 118.488889 },
  { id: 'STATE-EQUIP-BDA-UAV-01-05', entityId: 'EQUIP-BDA-UAV-01', sequence: 5, timestamp: 'T0日 10:00-10:07', location: '沿用地面待机阵地', action: '文档未单列新增行动', actionObject: '无', directResult: '无新增直接结果', updatedState: '地面待机、未升空', sourceBasis: 'carried-forward', latitude: 36.308333, longitude: 118.488889 },
  { id: 'STATE-EQUIP-BDA-UAV-01-06', entityId: 'EQUIP-BDA-UAV-01', sequence: 6, timestamp: 'T0日 10:07-10:08', location: '沿用地面待机阵地', action: '文档未单列新增行动', actionObject: '无', directResult: '无新增直接结果', updatedState: '地面待机、未升空', sourceBasis: 'carried-forward', latitude: 36.308333, longitude: 118.488889 },
  { id: 'STATE-EQUIP-BDA-UAV-01-07', entityId: 'EQUIP-BDA-UAV-01', sequence: 7, timestamp: 'T0日 10:08-10:25', location: '北纬36°18′30″，东经118°29′20″ → 北纬36°21′02″，东经118°34′16″（目标上空抵近区域）', action: '升空抵近侦察，高清核查目标损毁状态，实时回传战场画面', actionObject: '敌方损毁机动车队', directResult: '核验目标完全损毁、无残余作战能力', updatedState: '空中评估作业、态势采集状态', sourceBasis: 'joint-explicit-record', latitude: 36.350556, longitude: 118.571111 },
  { id: 'STATE-TARGET-CONVOY-01-01', entityId: 'TARGET-CONVOY-01', sequence: 1, timestamp: 'T0日 08:00', location: '北纬36°20′15″，东经118°32′30″', action: '匀速向前线炮兵阵地机动', actionObject: '前线作战单元（补给前置机动）', directResult: '正常行军、无异常暴露', updatedState: '满编完好、机动正常、补给能力100%、自卫能力100%', sourceBasis: 'explicit-record', latitude: 36.3375, longitude: 118.541667 },
  { id: 'STATE-TARGET-CONVOY-01-02', entityId: 'TARGET-CONVOY-01', sequence: 2, timestamp: 'T0日 08:00-09:10', location: '北纬36°21′20″，东经118°33′50″（沿山区战备公路动态机动）', action: '持续匀速机动、无规避、无停车隐蔽', actionObject: '无', directResult: '自身机动特征完全暴露，未感知我方侦察', updatedState: '暴露可侦察状态、作战实力无衰减、编队完整', sourceBasis: 'explicit-record', latitude: 36.355556, longitude: 118.563889 },
  { id: 'STATE-TARGET-CONVOY-01-03', entityId: 'TARGET-CONVOY-01', sequence: 3, timestamp: 'T0日 09:10-09:35', location: '北纬36°21′45″，东经118°34′20″（山区战备公路中段）', action: '持续向前线机动', actionObject: '无', directResult: '行驶轨迹稳定，未改变机动路线', updatedState: '满编完好、作战能力无损耗、机动状态稳定', sourceBasis: 'explicit-record', latitude: 36.3625, longitude: 118.572222 },
  { id: 'STATE-TARGET-CONVOY-01-04', entityId: 'TARGET-CONVOY-01', sequence: 4, timestamp: 'T0日 09:35-10:00', location: '北纬36°22′00″，东经118°34′45″（山区战备公路火力打击窗口区域）', action: '匀速机动、无战术规避', actionObject: '无', directResult: '进入我方火力最佳打击区间', updatedState: '完整作战状态、无实力损耗', sourceBasis: 'explicit-record', latitude: 36.366667, longitude: 118.579167 },
  { id: 'STATE-TARGET-CONVOY-01-05', entityId: 'TARGET-CONVOY-01', sequence: 5, timestamp: 'T0日 10:00-10:07', location: '北纬36°21′02″，东经118°34′16″', action: '正常机动行驶', actionObject: '无', directResult: '弹药精准命中编队核心，引发车载弹药殉爆', updatedState: '即时受损状态，核心车辆损毁、人员伤亡、部分弹药销毁', sourceBasis: 'explicit-record', latitude: 36.350556, longitude: 118.571111 },
  { id: 'STATE-TARGET-CONVOY-01-06', entityId: 'TARGET-CONVOY-01', sequence: 6, timestamp: 'T0日 10:07-10:08', location: '北纬36°21′02″，东经118°34′16″（打击命中点位）', action: '无有效作战、机动行动（完全失能）', actionObject: '无', directResult: '6台车辆全部损毁瘫痪，65吨弹药完全殉爆，防空装备全部报废，28名人员大部伤亡、残余人员失能', updatedState: '彻底报废、机动能力0、补给能力0、自卫能力0、作战实力完全归零', sourceBasis: 'explicit-record', latitude: 36.350556, longitude: 118.571111 },
  { id: 'STATE-TARGET-CONVOY-01-07', entityId: 'TARGET-CONVOY-01', sequence: 7, timestamp: 'T0日 10:08-10:25', location: '北纬36°21′02″，东经118°34′16″（打击损毁点位）', action: '无任何行动能力', actionObject: '无', directResult: '彻底丧失后勤保障功能，敌方前线弹药补给链路断裂', updatedState: '永久战损失效、无恢复作战能力', sourceBasis: 'explicit-record', latitude: 36.350556, longitude: 118.571111 }
] AS row
MERGE (s:StateNode {id:row.id})
SET s.entityId=row.entityId, s.sequence=row.sequence, s.timestamp=row.timestamp, s.location=row.location, s.action=row.action, s.actionObject=row.actionObject, s.directResult=row.directResult, s.updatedState=row.updatedState, s.sourceBasis=row.sourceBasis, s.latitude=row.latitude, s.longitude=row.longitude, s.origin='ASSERTED', s.lifecycleStatus='ACTIVE', s.dataset='military-causal-v5'
WITH row,s
MATCH (e:Entity {id:row.entityId, dataset:'military-causal-v5'})
MERGE (e)-[r:HAS_STATE]->(s)
SET r.time=row.timestamp, r.location=row.location, r.sequence=row.sequence;

UNWIND [
  { from: 'ACT-T2-01', to: 'ACT-T3-01' },
  { from: 'ACT-T3-01', to: 'ACT-T4-01' },
  { from: 'ACT-T4-01', to: 'ACT-T4-02' },
  { from: 'ACT-T4-01', to: 'ACT-T5-01' },
  { from: 'ACT-T4-04', to: 'ACT-T5-01' },
  { from: 'ACT-T4-02', to: 'ACT-T5-02' },
  { from: 'ACT-T5-01', to: 'ACT-T5-02' },
  { from: 'ACT-T5-02', to: 'ACT-T5-04' },
  { from: 'ACT-T5-02', to: 'ACT-T6-01' },
  { from: 'ACT-T6-01', to: 'ACT-T7-01' },
  { from: 'ACT-T5-04', to: 'ACT-T7-02' },
  { from: 'ACT-T7-02', to: 'ACT-T7-03' }
] AS row
MATCH (a:ActionNode {id:row.from, dataset:'military-causal-v5'}), (b:ActionNode {id:row.to, dataset:'military-causal-v5'})
MERGE (a)-[:CAUSES]->(b);

MATCH (e:Entity {dataset:'military-causal-v5'}) WITH count(e) AS entities MATCH (a:ActionNode {dataset:'military-causal-v5'}) WITH entities,count(a) AS actions MATCH (s:StateNode {dataset:'military-causal-v5'}) WITH entities,actions,count(s) AS states MATCH (x)-[r]->(y) WHERE x.dataset='military-causal-v5' AND y.dataset='military-causal-v5' RETURN entities,actions,states,count(r) AS relationships,count(DISTINCT type(r)) AS relationTypes;