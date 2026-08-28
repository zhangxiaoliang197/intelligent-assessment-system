using Aegis.Domain.Entities;

namespace Aegis.API.SeedData;

/// <summary>
/// Ontology-normalized dataset derived only from the supplied
/// "机动目标打击因果溯源结构化数据集".
///
/// Modeling principles:
/// 1. Force units, equipment and the enemy target are independent Entity instances.
/// 2. Force-equipment affiliation/operation is expressed through OPERATES; no "部队+装备" compound entity is created.
/// 3. ActionNode represents source-described actions/events. A joint source record may have multiple performers.
/// 4. StateNode represents one entity's state at each of the seven source time nodes. When the source does not
///    independently describe that entity, the snapshot is explicitly marked as carried/aggregate/not-explicit rather
///    than pretending the source supplied a new observation.
/// 5. CAUSES is reserved for causal/process dependency between ActionNode instances. The target-impact effect event is
///    the terminal node used by reverse causal tracing.
/// </summary>
public static class MilitaryDatasetSeed
{
    private const string ReconForce = "FORCE-RECON-01";
    private const string FireForce = "FORCE-FIRE-01";
    private const string CommandForce = "FORCE-C2-01";
    private const string AssessmentForce = "FORCE-BDA-01";
    private const string ReconUav = "EQUIP-RECON-UAV-01";
    private const string RocketSystem = "EQUIP-ROCKET-01";
    private const string CommandShelter = "EQUIP-C2-SHELTER-01";
    private const string AssessmentUav = "EQUIP-BDA-UAV-01";
    private const string EnemyConvoy = "TARGET-CONVOY-01";

    public static MilitaryDataset Create()
    {
        var entities = BuildEntities();
        var entityRelations = new[]
        {
            new MilitaryEntityRelation(ReconForce, ReconUav, "OPERATES"),
            new MilitaryEntityRelation(FireForce, RocketSystem, "OPERATES"),
            new MilitaryEntityRelation(CommandForce, CommandShelter, "OPERATES"),
            new MilitaryEntityRelation(AssessmentForce, AssessmentUav, "OPERATES"),
        };

        // Action nodes are source-record actions/events, not invented ontology categories.
        // "其余实体保持待机/状态无变化" is represented in StateNode snapshots rather than as fake actions.
        var actions = new[]
        {
            // 时序节点 1：T0日 08:00
            Action("ACT-T1-01", 1, 1, "开机升空、全域巡航扫描", "T0日 08:00",
                "北纬36°21′50″，东经118°33′40″（海拔8500m敌后预设侦察空域）", "reconnaissance",
                "鲁中丘陵山区机动目标区域", [ReconUav], [], [],
                "设备工况正常，进入侦察待机模式"),
            Action("ACT-T1-02", 2, 1, "阵地值守、装备通电自检、弹药装填待命", "T0日 08:00",
                "北纬36°18′25″，东经118°29′15″（我方后方隐蔽野战阵地）", "firepower",
                "无", [FireForce, RocketSystem], [], [],
                "装备状态完好，具备随时接战条件"),
            Action("ACT-T1-03", 3, 1, "全域态势值守、系统开机运行", "T0日 08:00",
                "北纬36°19′10″，东经118°30′50″（我方前沿机动指挥点位）", "command",
                "全域战场态势", [CommandForce, CommandShelter], [], [],
                "情报系统正常待机，等待数据接入"),
            Action("ACT-T1-04", 4, 1, "匀速向前线炮兵阵地机动", "T0日 08:00",
                "北纬36°20′15″，东经118°32′30″", "enemyTarget",
                "前线作战单元（补给前置机动）", [EnemyConvoy], [], [],
                "正常行军、无异常暴露"),
            Action("ACT-T1-05", 5, 1, "地面静置待命", "T0日 08:00",
                "北纬36°18′30″，东经118°29′20″（我方地面待机阵地）", "assessment",
                "无", [AssessmentUav], [], [],
                "设备正常待机"),

            // 时序节点 2：T0日 08:00-09:10
            Action("ACT-T2-01", 6, 2, "持续扫描、捕获移动热源并锁定机动目标", "T0日 08:00-09:10",
                "北纬36°21′35″，东经118°34′05″（敌后目标空域持续巡航）", "reconnaissance",
                "敌方机动弹药补给车队", [ReconForce, ReconUav], [EnemyConvoy], [],
                "成功锁定机动目标，获取实时轨迹、速度、编队数据，持续回传指挥端"),
            Action("ACT-T2-02", 7, 2, "持续匀速机动、无规避、无停车隐蔽", "T0日 08:00-09:10",
                "北纬36°21′20″，东经118°33′50″（沿山区战备公路动态机动）", "enemyTarget",
                "无", [EnemyConvoy], [], [],
                "自身机动特征完全暴露，未感知我方侦察"),

            // 时序节点 3：T0日 09:10-09:35
            Action("ACT-T3-01", 8, 3, "融合多源数据、甄别目标属性并完成目标研判", "T0日 09:10-09:35",
                "北纬36°19′10″，东经118°30′50″（我方前沿指挥点位）", "command",
                "敌方机动弹药补给车队侦察数据", [CommandForce, CommandShelter], [EnemyConvoy], [],
                "100%确认目标身份，判定为最高价值打击目标，形成动态打击决策方案"),
            Action("ACT-T3-02", 9, 3, "持续向前线机动", "T0日 09:10-09:35",
                "北纬36°21′45″，东经118°34′20″（山区战备公路中段）", "enemyTarget",
                "无", [EnemyConvoy], [], [],
                "行驶轨迹稳定，未改变机动路线"),
            Action("ACT-T3-03", 10, 3, "持续跟踪目标并稳定回传数据", "T0日 09:10-09:35",
                "文档未重复给出独立坐标（沿用持续巡航跟踪场景）", "reconnaissance",
                "敌方机动弹药补给车队", [ReconUav], [EnemyConvoy], [],
                "稳定回传目标动态数据，侦察状态无变更"),

            // 时序节点 4：T0日 09:35-10:00
            Action("ACT-T4-01", 11, 4, "下发机动目标动态打击指令", "T0日 09:35-10:00",
                "北纬36°19′10″，东经118°30′50″（我方前沿指挥点位）", "command",
                "远程火力打击单元", [CommandForce], [], [FireForce],
                "推送目标实时坐标、轨迹修正参数、打击弹种、作战预案，建立动态目标参数联动链路"),
            Action("ACT-T4-02", 12, 4, "接收作战指令并完成战前筹备、参数装订与阵地校准", "T0日 09:35-10:00",
                "北纬36°18′25″，东经118°29′15″（后方隐蔽野战阵地）", "firepower",
                "作战任务指令、机动目标参数", [FireForce, RocketSystem], [], [],
                "装备自检、机动目标轨迹参数装订、4枚侵彻爆破弹装填、阵地校准全部完成"),
            Action("ACT-T4-03", 13, 4, "匀速机动、无战术规避", "T0日 09:35-10:00",
                "北纬36°22′00″，东经118°34′45″（山区战备公路火力打击窗口区域）", "enemyTarget",
                "无", [EnemyConvoy], [], [],
                "进入我方火力最佳打击区间"),
            Action("ACT-T4-04", 14, 4, "持续跟踪锁定并回传目标动态", "T0日 09:35-10:00",
                "文档未重复给出独立坐标（沿用持续巡航跟踪场景）", "reconnaissance",
                "敌方机动弹药补给车队", [ReconUav], [EnemyConvoy], [],
                "持续提供机动目标动态数据"),

            // 时序节点 5：T0日 10:00-10:07
            Action("ACT-T5-01", 15, 5, "实时修正目标机动坐标并下发开火终极指令", "T0日 10:00-10:07",
                "北纬36°19′10″，东经118°30′50″（我方前沿指挥点位）", "command",
                "远程火箭炮单元、机动目标动态轨迹", [CommandForce], [EnemyConvoy], [FireForce],
                "完成打击参数最后校准，授权开火"),
            Action("ACT-T5-02", 16, 5, "依据动态轨迹提前量发射4枚高精度制导弹药", "T0日 10:00-10:07",
                "北纬36°18′25″，东经118°29′15″（后方隐蔽野战阵地）", "firepower",
                "敌方机动弹药补给车队", [FireForce, RocketSystem], [EnemyConvoy], [],
                "弹药正常发射、精准奔袭目标区域"),
            Action("ACT-T5-03", 17, 5, "正常机动行驶", "T0日 10:00-10:07",
                "北纬36°21′02″，东经118°34′16″", "enemyTarget",
                "无", [EnemyConvoy], [], [],
                "机动过程中进入弹药命中阶段"),
            Action("ACT-T5-04", 18, 5, "弹药精准命中编队核心并引发车载弹药殉爆", "T0日 10:00-10:07",
                "北纬36°21′02″，东经118°34′16″", "effect",
                "敌方机动弹药补给车队", [], [EnemyConvoy], [],
                "核心车辆损毁、人员伤亡、部分弹药销毁；随后目标机动、补给、自卫与作战能力归零",
                isCausalTerminal: true),

            // 时序节点 6：T0日 10:07-10:08
            Action("ACT-T6-01", 19, 6, "停止射击并启动战后撤收流程", "T0日 10:07-10:08",
                "北纬36°18′25″，东经118°29′15″（原野战阵地）", "firepower",
                "自身作战阵地", [FireForce, RocketSystem], [], [],
                "射击任务完成，进入撤离准备状态"),

            // 时序节点 7：T0日 10:08-10:25
            Action("ACT-T7-01", 20, 7, "6分钟快速撤收、阵地转移、战术撤离", "T0日 10:08-10:25",
                "北纬36°18′25″，东经118°29′15″ → 北纬36°18′10″，东经118°28′55″（机动转移途中）", "firepower",
                "自身作战编组", [FireForce, RocketSystem], [], [],
                "成功脱离作战阵地，规避敌方反击风险"),
            Action("ACT-T7-02", 21, 7, "升空抵近侦察并核查目标损毁状态", "T0日 10:08-10:25",
                "北纬36°18′30″，东经118°29′20″ → 北纬36°21′02″，东经118°34′16″（目标上空抵近区域）", "assessment",
                "敌方损毁机动车队", [AssessmentForce, AssessmentUav], [EnemyConvoy], [],
                "核验目标完全损毁、无残余作战能力并实时回传战场画面"),
            Action("ACT-T7-03", 22, 7, "接收评估数据、核验作战效果并闭环作战任务", "T0日 10:08-10:25",
                "北纬36°19′10″，东经118°30′50″（我方前沿指挥点位）", "command",
                "战场评估数据、作战任务", [CommandForce], [], [],
                "确认打击任务全额达成，更新战场全局态势")
        };

        var states = BuildStates();

        // Causal/process dependencies grounded in the source sequence.
        // Branches after the target-impact terminal are retained in the overview but do not become ancestors in trace-back.
        var causes = new[]
        {
            new MilitaryCausalLink("ACT-T2-01", "ACT-T3-01"),
            new MilitaryCausalLink("ACT-T3-01", "ACT-T4-01"),
            new MilitaryCausalLink("ACT-T4-01", "ACT-T4-02"),
            new MilitaryCausalLink("ACT-T4-01", "ACT-T5-01"),
            new MilitaryCausalLink("ACT-T4-04", "ACT-T5-01"),
            new MilitaryCausalLink("ACT-T4-02", "ACT-T5-02"),
            new MilitaryCausalLink("ACT-T5-01", "ACT-T5-02"),
            new MilitaryCausalLink("ACT-T5-02", "ACT-T5-04"),
            new MilitaryCausalLink("ACT-T5-02", "ACT-T6-01"),
            new MilitaryCausalLink("ACT-T6-01", "ACT-T7-01"),
            new MilitaryCausalLink("ACT-T5-04", "ACT-T7-02"),
            new MilitaryCausalLink("ACT-T7-02", "ACT-T7-03")
        };

        return new MilitaryDataset
        {
            Entities = entities,
            EntityRelations = entityRelations,
            Actions = actions,
            States = states,
            Causes = causes
        };
    }

    private static IReadOnlyList<MilitaryEntityNode> BuildEntities() =>
    [
        Entity(ReconForce, "陆军航空兵某侦察中队", "ForceUnit", "reconnaissance", new()
        {
            ["编制"] = "2人/单机",
            ["职能"] = "敌后全域侦察、机动目标跟踪、态势回传",
            ["能力特征"] = "具备全天候隐蔽作业能力"
        }),
        Entity(FireForce, "陆军远程火力旅某营", "ForceUnit", "firepower", new()
        {
            ["编组"] = "12人",
            ["配置"] = "发射车、指挥车、弹药补给车各1台",
            ["职能"] = "远程精准火力打击、快打快撤"
        }),
        Entity(CommandForce, "前沿机动指挥分队", "ForceUnit", "command", new()
        {
            ["职能"] = "多源情报融合、目标研判、任务下发、动态参数修正、态势统筹"
        }),
        Entity(AssessmentForce, "战场效果评估分队", "ForceUnit", "assessment", new()
        {
            ["职能"] = "打击后抵近侦察、目标毁伤核验、作战效果判定"
        }),
        Entity(ReconUav, "中型长航时侦察无人机", "Equipment", "reconnaissance", new()
        {
            ["最大续航"] = "32h",
            ["实用升限"] = "9000m",
            ["侦察半径"] = "1200km",
            ["传感器"] = "SAR雷达+光电红外双模吊舱",
            ["动态定位精度"] = "±1.5m",
            ["坐标更新频率"] = "1次/秒",
            ["通信"] = "加密实时通信",
            ["任务适配"] = "全天候隐蔽侦察与机动目标持续跟踪"
        }),
        Entity(RocketSystem, "远程箱式火箭炮系统", "Equipment", "firepower", new()
        {
            ["射程"] = "50-370km",
            ["圆概率误差"] = "≤5m",
            ["制导"] = "卫星+惯性双制导",
            ["机动目标能力"] = "支持机动目标轨迹修正",
            ["载弹量"] = "单车8枚",
            ["阵地展开"] = "8min",
            ["撤收"] = "6min",
            ["适配弹药"] = "反车辆侵彻爆破弹药",
            ["任务适配"] = "快速机动作战、快打快撤"
        }),
        Entity(CommandShelter, "野战机动指挥方舱系统", "Equipment", "command", new()
        {
            ["多源数据融合时延"] = "≤2s",
            ["指令下发时延"] = "≤1s",
            ["功能"] = "机动目标轨迹推演、动态坐标校准、全域态势融合研判"
        }),
        Entity(AssessmentUav, "近程小型评估无人机", "Equipment", "assessment", new()
        {
            ["续航"] = "4h",
            ["作业高度"] = "1000-3000m",
            ["传感器"] = "高清可见光+红外成像设备",
            ["功能"] = "近距离实体状态识别、毁伤细节采集与画面实时回传"
        }),
        Entity(EnemyConvoy, "敌方前沿机动弹药补给车队", "Target", "enemyTarget", new()
        {
            ["目标类型"] = "后勤机动作战单元",
            ["固定编制"] = "6台车辆（2台弹药运输车、2台油料车、1台指挥通信车、1台防空护卫车）",
            ["在编人员"] = "28人",
            ["固定载荷"] = "大口径榴弹、反坦克弹药、迫击炮弹合计65吨；随车单兵防空武器若干",
            ["固有能力"] = "公路机动、前线弹药补给、基础单兵防空自卫",
            ["防护限制"] = "无重型装甲、无固定防空阵地"
        })
    ];

    private static IReadOnlyList<MilitaryStateNode> BuildStates()
    {
        var result = new List<MilitaryStateNode>(63);

        // 侦察部队：仅 T2 源记录明确写成“无人机+侦察部队”；其它节点不把无人机的位置/动作伪装成部队独立观测。
        AddSeries(result, ReconForce,
            T(1, "T0日 08:00", "文档未单列侦察部队独立位置", "文档未单列侦察部队独立行动；其操作装备执行开机升空与全域巡航扫描", "无独立记录", "无独立结果记录", "侦察任务保障状态（由静态职能与后续联合记录可知）", "not-explicitly-recorded", null, null),
            T(2, "T0日 08:00-09:10", "北纬36°21′35″，东经118°34′05″（源记录为侦察部队+侦察无人机联合实体）", "SAR雷达+红外吊舱持续扫描，捕获移动热源与车辆轨迹，识别车队编队特征，每秒更新目标坐标", "敌方机动弹药补给车队", "成功锁定机动目标，获取实时轨迹、速度、编队数据，持续回传指挥端", "目标锁定、持续跟踪、动态数据输出状态", "joint-explicit-record", 36.359722, 118.568056),
            T(3, "T0日 09:10-09:35", "文档未单列侦察部队独立位置", "文档仅明确侦察无人机持续跟踪；侦察部队独立行动未单列", "敌方机动弹药补给车队", "无独立结果记录", "沿用联合记录中的持续侦察任务状态", "carried-forward", null, null),
            T(4, "T0日 09:35-10:00", "文档未单列侦察部队独立位置", "文档仅明确侦察无人机持续跟踪锁定；侦察部队独立行动未单列", "敌方机动弹药补给车队", "无独立结果记录", "沿用持续侦察任务状态", "carried-forward", null, null),
            T(5, "T0日 10:00-10:07", "文档未单列", "文档未单列新增行动", "无独立记录", "无新增直接结果", "沿用持续侦察任务状态", "not-explicitly-recorded", null, null),
            T(6, "T0日 10:07-10:08", "文档未单列", "文档未单列新增行动", "无独立记录", "无新增直接结果", "沿用上一节点状态", "not-explicitly-recorded", null, null),
            T(7, "T0日 10:08-10:25", "文档未单列", "文档未单列新增行动", "无独立记录", "无新增直接结果", "沿用上一节点状态", "not-explicitly-recorded", null, null));

        AddSeries(result, ReconUav,
            T(1, "T0日 08:00", "北纬36°21′50″，东经118°33′40″（海拔8500m敌后预设侦察空域）", "开机升空、全域巡航扫描", "鲁中丘陵山区机动目标区域", "设备工况正常，进入侦察待机模式", "空域隐蔽巡航、待机侦察（无目标锁定）", "explicit-record", 36.363889, 118.561111),
            T(2, "T0日 08:00-09:10", "北纬36°21′35″，东经118°34′05″（敌后目标空域持续巡航）", "SAR雷达+红外吊舱持续扫描，捕获移动热源与车辆轨迹，识别车队编队特征，每秒更新目标坐标", "敌方机动弹药补给车队", "成功锁定机动目标，获取实时轨迹、速度、编队数据，持续回传指挥端", "目标锁定、持续跟踪、动态数据输出状态", "joint-explicit-record", 36.359722, 118.568056),
            T(3, "T0日 09:10-09:35", "文档未重复给出坐标（持续跟踪场景）", "持续跟踪目标，稳定回传数据", "敌方机动弹药补给车队", "稳定回传数据", "目标锁定、持续跟踪、动态数据输出状态", "explicit-record", null, null),
            T(4, "T0日 09:35-10:00", "文档未重复给出坐标（持续跟踪场景）", "持续跟踪锁定", "敌方机动弹药补给车队", "持续提供目标动态信息", "目标锁定、持续跟踪、动态数据输出状态", "explicit-record", null, null),
            T(5, "T0日 10:00-10:07", "文档未单列", "文档未单列新增行动；沿用前序持续跟踪任务状态", "敌方机动弹药补给车队", "无新增直接结果", "目标锁定、持续跟踪、动态数据输出状态", "carried-forward", null, null),
            T(6, "T0日 10:07-10:08", "文档未单列", "文档未单列新增行动", "无独立记录", "无新增直接结果", "沿用上一节点状态", "not-explicitly-recorded", null, null),
            T(7, "T0日 10:08-10:25", "文档未单列", "文档未单列新增行动", "无独立记录", "无新增直接结果", "沿用上一节点状态", "not-explicitly-recorded", null, null));

        // 火力部队 / 火箭炮系统：文档多处以“部队+装备”联合实体描述，因此联合记录分别挂到两个实体，但 sourceBasis 明确标记。
        var fireJoint = new[]
        {
            T(1, "T0日 08:00", "北纬36°18′25″，东经118°29′15″（我方后方隐蔽野战阵地）", "阵地值守、装备通电自检、弹药装填待命", "无", "装备状态完好，具备随时接战条件", "阵地待机、未装订参数、待击待命", "joint-explicit-record", 36.306944, 118.487500),
            T(2, "T0日 08:00-09:10", "沿用T1野战阵地", "保持原有待机状态，无新增行动", "无", "状态无变化", "阵地待机、未装订参数、待击待命", "aggregate-unchanged-record", 36.306944, 118.487500),
            T(3, "T0日 09:10-09:35", "沿用T1野战阵地", "保持待机状态", "无", "状态无变化", "阵地待机、未装订参数、待击待命", "aggregate-unchanged-record", 36.306944, 118.487500),
            T(4, "T0日 09:35-10:00", "北纬36°18′25″，东经118°29′15″（后方隐蔽野战阵地）", "接收作战指令，完成装备自检、机动目标轨迹参数装订、4枚侵彻爆破弹装填、阵地校准", "作战任务指令、机动目标参数", "战前筹备全部完成，可实时修正打击参数", "备战待击、参数装订完成、随时可开火", "joint-explicit-record", 36.306944, 118.487500),
            T(5, "T0日 10:00-10:07", "北纬36°18′25″，东经118°29′15″（后方隐蔽野战阵地）", "依据动态轨迹提前量，发射4枚高精度制导弹药", "敌方机动弹药补给车队", "弹药正常发射、精准奔袭目标区域", "射击执行状态、火力输出完成", "joint-explicit-record", 36.306944, 118.487500),
            T(6, "T0日 10:07-10:08", "北纬36°18′25″，东经118°29′15″（原野战阵地）", "停止射击，启动战后撤收流程", "自身作战阵地", "射击任务完成，进入撤离准备状态", "射击完成、待撤离状态", "joint-explicit-record", 36.306944, 118.487500),
            T(7, "T0日 10:08-10:25", "北纬36°18′25″，东经118°29′15″ → 北纬36°18′10″，东经118°28′55″（机动转移途中）", "6分钟快速撤收、阵地转移、战术撤离", "自身作战编组", "成功脱离作战阵地，规避敌方反击风险", "安全机动转移、作战任务阶段性完成", "joint-explicit-record", 36.302778, 118.481944)
        };
        AddSeries(result, FireForce, fireJoint);
        AddSeries(result, RocketSystem, fireJoint);

        // 指挥分队与方舱：T1/T3 为联合记录；T4/T5/T7 明确主体是指挥部队，方舱只保留状态连续性，不伪造独立动作。
        AddSeries(result, CommandForce,
            T(1, "T0日 08:00", "北纬36°19′10″，东经118°30′50″（我方前沿机动指挥点位）", "全域态势值守、系统开机运行", "全域战场态势", "情报系统正常待机，等待数据接入", "常态值守、无作战任务", "joint-explicit-record", 36.319444, 118.513889),
            T(2, "T0日 08:00-09:10", "沿用T1前沿机动指挥点位", "保持原有待机、值守状态，无新增行动", "无", "无状态变化", "常态值守、无作战任务", "aggregate-unchanged-record", 36.319444, 118.513889),
            T(3, "T0日 09:10-09:35", "北纬36°19′10″，东经118°30′50″（我方前沿指挥点位）", "融合无人机、卫星多源数据，甄别目标属性，推演机动轨迹，研判作战价值，确认打击优先级", "敌方机动弹药补给车队侦察数据", "100%确认目标身份，判定为最高价值打击目标，形成动态打击决策方案", "专项任务研判状态、任务方案生成完成", "joint-explicit-record", 36.319444, 118.513889),
            T(4, "T0日 09:35-10:00", "北纬36°19′10″，东经118°30′50″（我方前沿指挥点位）", "下发机动目标动态打击指令，推送目标实时坐标、轨迹修正参数、打击弹种、作战预案", "远程火力打击单元", "打击任务成功下发，建立动态目标参数联动链路", "任务指挥状态、实时监控目标动态", "explicit-record", 36.319444, 118.513889),
            T(5, "T0日 10:00-10:07", "北纬36°19′10″，东经118°30′50″（我方前沿指挥点位）", "实时修正目标机动坐标，下发开火终极指令", "远程火箭炮单元、机动目标动态轨迹", "完成打击参数最后校准，授权开火", "实时作战指挥状态", "explicit-record", 36.319444, 118.513889),
            T(6, "T0日 10:07-10:08", "沿用前沿机动指挥点位", "文档未单列新增行动", "无", "无新增直接结果", "沿用实时作战指挥状态", "not-explicitly-recorded", 36.319444, 118.513889),
            T(7, "T0日 10:08-10:25", "北纬36°19′10″，东经118°30′50″（我方前沿指挥点位）", "接收评估数据，核验作战效果，闭环作战任务", "战场评估数据、作战任务", "确认打击任务全额达成，更新战场全局态势", "任务闭环、态势更新完成、回归常态值守", "explicit-record", 36.319444, 118.513889));

        AddSeries(result, CommandShelter,
            T(1, "T0日 08:00", "北纬36°19′10″，东经118°30′50″（我方前沿机动指挥点位）", "全域态势值守、系统开机运行", "全域战场态势", "情报系统正常待机，等待数据接入", "常态值守、无作战任务", "joint-explicit-record", 36.319444, 118.513889),
            T(2, "T0日 08:00-09:10", "沿用T1前沿机动指挥点位", "保持原有待机、值守状态，无新增行动", "无", "无状态变化", "常态值守、无作战任务", "aggregate-unchanged-record", 36.319444, 118.513889),
            T(3, "T0日 09:10-09:35", "北纬36°19′10″，东经118°30′50″（我方前沿指挥点位）", "融合无人机、卫星多源数据，甄别目标属性，推演机动轨迹，研判作战价值，确认打击优先级", "敌方机动弹药补给车队侦察数据", "100%确认目标身份并形成动态打击决策方案", "专项任务研判状态、任务方案生成完成", "joint-explicit-record", 36.319444, 118.513889),
            T(4, "T0日 09:35-10:00", "沿用前沿机动指挥点位", "文档未将方舱作为独立行动主体单列；系统作为指挥部队所操作装备持续提供支撑", "无独立记录", "无独立结果记录", "沿用专项任务支撑状态", "carried-forward", 36.319444, 118.513889),
            T(5, "T0日 10:00-10:07", "沿用前沿机动指挥点位", "文档未将方舱作为独立行动主体单列；持续支撑动态坐标校准与指令下发", "无独立记录", "无独立结果记录", "作战指挥系统支撑状态", "carried-forward", 36.319444, 118.513889),
            T(6, "T0日 10:07-10:08", "沿用前沿机动指挥点位", "文档未单列新增行动", "无", "无新增直接结果", "沿用作战指挥系统支撑状态", "not-explicitly-recorded", 36.319444, 118.513889),
            T(7, "T0日 10:08-10:25", "沿用前沿机动指挥点位", "文档未将方舱作为独立行动主体单列；随指挥分队完成任务闭环", "无独立记录", "无独立结果记录", "回归常态系统支撑状态", "carried-forward", 36.319444, 118.513889));

        // 评估无人机 T1 明确；评估部队直到 T7 才以联合实体明确出现。
        AddSeries(result, AssessmentForce,
            T(1, "T0日 08:00", "文档未单列评估部队独立位置", "文档仅明确近程小型评估无人机地面待机；评估部队独立行动未单列", "无独立记录", "无独立结果记录", "评估任务待命状态", "not-explicitly-recorded", null, null),
            T(2, "T0日 08:00-09:10", "文档未单列独立位置", "其余我方实体保持原有待机、值守状态", "无", "无状态变化", "评估任务待命状态", "aggregate-unchanged-record", null, null),
            T(3, "T0日 09:10-09:35", "文档未单列独立位置", "文档仅明确评估无人机保持待机；评估部队独立行动未单列", "无", "无状态变化", "评估任务待命状态", "carried-forward", null, null),
            T(4, "T0日 09:35-10:00", "文档未单列", "文档未单列新增行动", "无", "无新增直接结果", "沿用评估任务待命状态", "not-explicitly-recorded", null, null),
            T(5, "T0日 10:00-10:07", "文档未单列", "文档未单列新增行动", "无", "无新增直接结果", "沿用评估任务待命状态", "not-explicitly-recorded", null, null),
            T(6, "T0日 10:07-10:08", "文档未单列", "文档未单列新增行动", "无", "无新增直接结果", "沿用评估任务待命状态", "not-explicitly-recorded", null, null),
            T(7, "T0日 10:08-10:25", "北纬36°18′30″，东经118°29′20″ → 北纬36°21′02″，东经118°34′16″（源记录为评估部队+评估无人机联合实体）", "升空抵近侦察，高清核查目标损毁状态，实时回传战场画面", "敌方损毁机动车队", "核验目标完全损毁、无残余作战能力", "空中评估作业、态势采集状态", "joint-explicit-record", 36.350556, 118.571111));

        AddSeries(result, AssessmentUav,
            T(1, "T0日 08:00", "北纬36°18′30″，东经118°29′20″（我方地面待机阵地）", "地面静置待命", "无", "设备正常待机", "地面待机、未升空", "explicit-record", 36.308333, 118.488889),
            T(2, "T0日 08:00-09:10", "沿用T1地面待机阵地", "保持原有待机状态，无新增行动", "无", "状态无变化", "地面待机、未升空", "aggregate-unchanged-record", 36.308333, 118.488889),
            T(3, "T0日 09:10-09:35", "沿用T1地面待机阵地", "保持待机状态", "无", "状态无变化", "地面待机、未升空", "explicit-record", 36.308333, 118.488889),
            T(4, "T0日 09:35-10:00", "沿用地面待机阵地", "文档未单列新增行动", "无", "无新增直接结果", "地面待机、未升空", "carried-forward", 36.308333, 118.488889),
            T(5, "T0日 10:00-10:07", "沿用地面待机阵地", "文档未单列新增行动", "无", "无新增直接结果", "地面待机、未升空", "carried-forward", 36.308333, 118.488889),
            T(6, "T0日 10:07-10:08", "沿用地面待机阵地", "文档未单列新增行动", "无", "无新增直接结果", "地面待机、未升空", "carried-forward", 36.308333, 118.488889),
            T(7, "T0日 10:08-10:25", "北纬36°18′30″，东经118°29′20″ → 北纬36°21′02″，东经118°34′16″（目标上空抵近区域）", "升空抵近侦察，高清核查目标损毁状态，实时回传战场画面", "敌方损毁机动车队", "核验目标完全损毁、无残余作战能力", "空中评估作业、态势采集状态", "joint-explicit-record", 36.350556, 118.571111));

        AddSeries(result, EnemyConvoy,
            T(1, "T0日 08:00", "北纬36°20′15″，东经118°32′30″", "匀速向前线炮兵阵地机动", "前线作战单元（补给前置机动）", "正常行军、无异常暴露", "满编完好、机动正常、补给能力100%、自卫能力100%", "explicit-record", 36.337500, 118.541667),
            T(2, "T0日 08:00-09:10", "北纬36°21′20″，东经118°33′50″（沿山区战备公路动态机动）", "持续匀速机动、无规避、无停车隐蔽", "无", "自身机动特征完全暴露，未感知我方侦察", "暴露可侦察状态、作战实力无衰减、编队完整", "explicit-record", 36.355556, 118.563889),
            T(3, "T0日 09:10-09:35", "北纬36°21′45″，东经118°34′20″（山区战备公路中段）", "持续向前线机动", "无", "行驶轨迹稳定，未改变机动路线", "满编完好、作战能力无损耗、机动状态稳定", "explicit-record", 36.362500, 118.572222),
            T(4, "T0日 09:35-10:00", "北纬36°22′00″，东经118°34′45″（山区战备公路火力打击窗口区域）", "匀速机动、无战术规避", "无", "进入我方火力最佳打击区间", "完整作战状态、无实力损耗", "explicit-record", 36.366667, 118.579167),
            T(5, "T0日 10:00-10:07", "北纬36°21′02″，东经118°34′16″", "正常机动行驶", "无", "弹药精准命中编队核心，引发车载弹药殉爆", "即时受损状态，核心车辆损毁、人员伤亡、部分弹药销毁", "explicit-record", 36.350556, 118.571111),
            T(6, "T0日 10:07-10:08", "北纬36°21′02″，东经118°34′16″（打击命中点位）", "无有效作战、机动行动（完全失能）", "无", "6台车辆全部损毁瘫痪，65吨弹药完全殉爆，防空装备全部报废，28名人员大部伤亡、残余人员失能", "彻底报废、机动能力0、补给能力0、自卫能力0、作战实力完全归零", "explicit-record", 36.350556, 118.571111),
            T(7, "T0日 10:08-10:25", "北纬36°21′02″，东经118°34′16″（打击损毁点位）", "无任何行动能力", "无", "彻底丧失后勤保障功能，敌方前线弹药补给链路断裂", "永久战损失效、无恢复作战能力", "explicit-record", 36.350556, 118.571111));

        return result;
    }

    private static MilitaryEntityNode Entity(
        string id,
        string name,
        string ontologyType,
        string operationalRole,
        Dictionary<string, string> staticProps)
    {
        staticProps["数据来源"] = "机动目标打击因果溯源结构化数据集";
        return new MilitaryEntityNode
        {
            Id = id,
            Name = name,
            OntologyType = ontologyType,
            OperationalRole = operationalRole,
            StaticProps = staticProps
        };
    }

    private static MilitaryActionNode Action(
        string id,
        int sequence,
        int timeNode,
        string name,
        string timestamp,
        string location,
        string actionType,
        string actionObject,
        IReadOnlyList<string> performerEntityIds,
        IReadOnlyList<string> targetEntityIds,
        IReadOnlyList<string> recipientEntityIds,
        string directResult,
        bool isCausalTerminal = false) => new()
    {
        Id = id,
        Sequence = sequence,
        TimeNode = timeNode,
        Name = name,
        Timestamp = timestamp,
        Location = location,
        ActionType = actionType,
        ActionObject = actionObject,
        PerformerEntityIds = performerEntityIds,
        TargetEntityIds = targetEntityIds,
        RecipientEntityIds = recipientEntityIds,
        DirectResult = directResult,
        IsCausalTerminal = isCausalTerminal
    };

    private static TimelineTemplate T(
        int sequence,
        string timestamp,
        string location,
        string action,
        string actionObject,
        string directResult,
        string updatedState,
        string sourceBasis,
        double? latitude,
        double? longitude) =>
        new(sequence, timestamp, location, action, actionObject, directResult, updatedState, sourceBasis, latitude, longitude);

    private static void AddSeries(
        ICollection<MilitaryStateNode> result,
        string entityId,
        params TimelineTemplate[] records)
    {
        if (records.Length != 7)
            throw new InvalidOperationException($"Entity {entityId} must have exactly seven time-node snapshots.");

        foreach (var record in records)
        {
            result.Add(new MilitaryStateNode
            {
                Id = $"STATE-{entityId}-{record.Sequence:00}",
                EntityId = entityId,
                Sequence = record.Sequence,
                Timestamp = record.Timestamp,
                Location = record.Location,
                Action = record.Action,
                ActionObject = record.ActionObject,
                DirectResult = record.DirectResult,
                UpdatedState = record.UpdatedState,
                SourceBasis = record.SourceBasis,
                Latitude = record.Latitude,
                Longitude = record.Longitude
            });
        }
    }

    private sealed record TimelineTemplate(
        int Sequence,
        string Timestamp,
        string Location,
        string Action,
        string ActionObject,
        string DirectResult,
        string UpdatedState,
        string SourceBasis,
        double? Latitude,
        double? Longitude);
}
