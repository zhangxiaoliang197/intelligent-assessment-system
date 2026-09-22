package com.assessment.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Pattern;

/**
 * 注解校验器：把"结构一致性"与"值域一致性"两类校验从页面生成期左移到保存期。
 *
 * 分层设计（见 {@code .trae/documents/ipage-注解校验左移方案.md}）：
 * 1. ① 格式校验由 {@link SemanticSchemaValidator} 负责（保存前调用，不合格拒绝保存）；
 * 2. ② **结构一致性**由本类负责：注解引用的列必须真实存在、几何列成对、同角色不重复、
 *    状态规范值必须在运行时段内 —— 不查业务库（表结构由调用方传入），不合格**拒绝保存**；
 * 3. ③ **值域一致性**由本类负责：只对配置了 {@code values} 的列做受限采样比对，
 *    结果**仅告警不阻断**（业务数据是活的，今天通过不代表明天仍通过）。
 *
 * 校验口径以"页面服务（Python）真正消费的键"为准：本类拒绝的注解，运行期一定会被静默忽略，
 * 因此拒绝保存比放任保存更安全。运行期只保留零成本兜底（注解列缺失回落 + 值域漂移告警）。
 */
@Service
public class AnnotationValidator {

    private static final Logger logger = LoggerFactory.getLogger(AnnotationValidator.class);

    /** 运行时状态规范键（与 ipage field_resolver.STATUS_KEYS、page-kit STATUS_STYLES 三方对齐）。 */
    public static final Set<String> STATUS_KEYS =
            Set.of("destroyed", "miss", "critical", "heavy", "light");

    /** 有确定性消费者的字段角色：同一张表重复声明会让后者静默失效。 */
    private static final List<String> STRICT_ROLES = List.of(
            "lng", "lat", "seq", "time", "radius", "altitude", "speed", "heading", "status");

    /** 阵营规范值：命中这些值才吃语义色，其余由调色板稳定分配。 */
    private static final Set<String> FACTION_CANONICAL = Set.of("蓝方", "红方", "blue", "red");

    /** 地面设施类符号：与 entityKind=air 同时出现属语义可疑。 */
    private static final Set<String> GROUND_SYMBOLS = Set.of(
            "sam", "radar", "coastal", "depot", "fuel", "anchor", "runway", "tower", "ring");

    /** 单次保存最多采样的列数（对齐 DataHub 的 sample-values 上限思路）。 */
    private static final int MAX_SAMPLE_COLUMNS = 20;
    /** 单列采样最多保留的取值个数（高基数列自然截断）。 */
    private static final int MAX_SAMPLE_VALUES = 200;

    /** 安全标识符：与 ipage 侧一致，避免采样 SQL 拼接特殊字符。 */
    private static final Pattern SAFE_IDENT =
            Pattern.compile("^[A-Za-z_\\u4e00-\\u9fa5][A-Za-z0-9_$\\u4e00-\\u9fa5]*$");

    private final ObjectMapper mapper = new ObjectMapper();
    private final SqlExecutionService sqlExecutionService;

    @Value("${annotation.sample-check-enabled:true}")
    private boolean sampleCheckEnabled = true;

    /** 允许注入 null（单测场景）：为 null 时跳过值域采样，只做结构校验。 */
    @Autowired
    public AnnotationValidator(SqlExecutionService sqlExecutionService) {
        this.sqlExecutionService = sqlExecutionService;
    }

    // ──────────────────────────────────────────────────────────────────
    // 数据载体
    // ──────────────────────────────────────────────────────────────────

    /** 一条字段语义：列名 + semantic_json 原文。 */
    public static final class FieldSemantic {
        private final String column;
        private final String semanticJson;

        public FieldSemantic(String column, String semanticJson) {
            this.column = column == null ? "" : column.trim();
            this.semanticJson = semanticJson;
        }

        public String getColumn() { return column; }
        public String getSemanticJson() { return semanticJson; }
    }

    /** 校验结果：errors 非空表示拒绝保存；warnings 为可强制保存的提示。 */
    public static final class Result {
        private final List<String> errors = new ArrayList<>();
        private final List<String> warnings = new ArrayList<>();
        private boolean sampled;
        private boolean structureChecked;
        private String structureFingerprint = "";

        public List<String> getErrors() { return errors; }
        public List<String> getWarnings() { return warnings; }
        public boolean isSampled() { return sampled; }
        public boolean isStructureChecked() { return structureChecked; }
        public String getStructureFingerprint() { return structureFingerprint; }
        public boolean isRejected() { return !errors.isEmpty(); }
    }

    // ──────────────────────────────────────────────────────────────────
    // 主入口
    // ──────────────────────────────────────────────────────────────────

    /**
     * 校验一批注解（数据集级 + 字段级）。
     *
     * @param tableName        物理表名（用于结构指纹与采样 SQL）
     * @param tableColumns     物理表结构（来自 {@code readTableColumns}，每项含 columnName/dataType/comment）
     * @param datasetSemantic  数据集级 semantic_json（可为 null）
     * @param fields           字段级语义列表（保存场景为本次提交的全量；单字段更新场景为合并后的全量）
     * @param datasetId        数据集 ID；为空或为 null 时跳过值域采样
     * @return 校验结果（errors / warnings / 指纹）
     */
    public Result validate(String tableName, List<Map<String, Object>> tableColumns,
                           String datasetSemantic, List<FieldSemantic> fields,
                           String datasetId) {
        Result result = new Result();
        List<FieldSemantic> items = fields == null ? List.of() : fields;
        Map<String, String> columnIndex = indexColumns(tableColumns);

        if (columnIndex.isEmpty()) {
            result.warnings.add("未能读取表结构，已跳过结构一致性校验（仅完成格式校验）");
        } else {
            result.structureChecked = true;
            result.structureFingerprint = fingerprint(tableName, tableColumns);
            checkFieldColumns(items, columnIndex, result);
            checkDatasetReferences(datasetSemantic, columnIndex, result);
            checkRoleConflicts(items, result);
            checkStatusValues(items, result);
            checkFieldValueMaps(items, result);
            checkDatasetConsistency(datasetSemantic, items, result);
        }

        if (datasetId != null && !datasetId.isBlank() && sampleCheckEnabled) {
            sampleValueDomains(datasetId, tableName, items, columnIndex, result);
        } else if (datasetId != null && !datasetId.isBlank()) {
            result.warnings.add("值域采样校验已关闭（annotation.sample-check-enabled=false）");
        }
        return result;
    }

    /** 结构指纹：表名 + 列名/类型/注释的摘要，用于"注解是否过期"判定。 */
    public String fingerprint(String tableName, List<Map<String, Object>> tableColumns) {
        StringBuilder sb = new StringBuilder(tableName == null ? "" : tableName.trim());
        if (tableColumns != null) {
            List<String> parts = new ArrayList<>();
            for (Map<String, Object> column : tableColumns) {
                parts.add(text(column.get("columnName")) + "|"
                        + text(column.get("dataType")) + "|"
                        + text(column.get("comment")));
            }
            parts.sort(String::compareTo);
            sb.append('|').append(String.join(";", parts));
        }
        return sha256(sb.toString());
    }

    // ──────────────────────────────────────────────────────────────────
    // ② 结构一致性规则
    // ──────────────────────────────────────────────────────────────────

    /** R1：字段注解的列必须存在于表结构中。 */
    private void checkFieldColumns(List<FieldSemantic> fields, Map<String, String> columnIndex,
                                  Result result) {
        for (FieldSemantic field : fields) {
            if (field.getColumn().isEmpty()) {
                result.errors.add("存在缺少列名的字段注解");
                continue;
            }
            if (!columnIndex.containsKey(key(field.getColumn()))) {
                result.errors.add("字段 " + field.getColumn() + "：该列在表结构中不存在，注解不会生效");
            }
        }
    }

    /** R2/R3/R4/R5：数据集级语义引用的列必须存在。 */
    private void checkDatasetReferences(String datasetSemantic, Map<String, String> columnIndex,
                                        Result result) {
        JsonNode node = parse(datasetSemantic);
        if (node == null) {
            if (datasetSemantic != null && !datasetSemantic.isBlank()) {
                result.warnings.add("数据集级语义不是合法 JSON，已跳过其结构校验");
            }
            return;
        }
        JsonNode geometry = node.get("geometry");
        if (geometry != null && geometry.isObject()) {
            requireColumn(geometry.get("lngColumn"), "geometry.lngColumn", columnIndex, result);
            requireColumn(geometry.get("latColumn"), "geometry.latColumn", columnIndex, result);
            requireColumn(geometry.get("radiusColumn"), "geometry.radiusColumn", columnIndex, result);
        }
        JsonNode groupKey = node.get("trackGroupKey");
        if (groupKey != null && groupKey.isArray()) {
            for (JsonNode item : groupKey) {
                requireColumn(item, "trackGroupKey", columnIndex, result);
            }
        }
        requireColumn(node.get("eventTimeColumn"), "eventTimeColumn", columnIndex, result);
    }

    private void requireColumn(JsonNode value, String label, Map<String, String> columnIndex,
                              Result result) {
        if (value == null || value.isNull()) {
            return;
        }
        String column = value.asText("");
        if (column.isBlank()) {
            return;
        }
        if (!columnIndex.containsKey(key(column))) {
            result.errors.add(label + " 引用的列 " + column + " 在表结构中不存在");
        }
    }

    /** R6：同一张表同一严格角色只能声明一次。 */
    private void checkRoleConflicts(List<FieldSemantic> fields, Result result) {
        Map<String, List<String>> byRole = new LinkedHashMap<>();
        for (FieldSemantic field : fields) {
            JsonNode node = parse(field.getSemanticJson());
            if (node == null) {
                continue;
            }
            String role = node.path("role").asText("");
            if (role.isBlank() || !STRICT_ROLES.contains(role)) {
                continue;
            }
            byRole.computeIfAbsent(role, k -> new ArrayList<>()).add(field.getColumn());
        }
        for (Map.Entry<String, List<String>> entry : byRole.entrySet()) {
            if (entry.getValue().size() > 1) {
                result.errors.add("角色 " + entry.getKey() + " 被多个字段声明（"
                        + String.join("、", entry.getValue())
                        + "），运行期只会取第一个，请只保留一个");
            }
        }
    }

    /** R7：status 角色的 values 规范值必须落在运行时段内。 */
    private void checkStatusValues(List<FieldSemantic> fields, Result result) {
        for (FieldSemantic field : fields) {
            JsonNode node = parse(field.getSemanticJson());
            if (node == null || !"status".equals(node.path("role").asText(""))) {
                continue;
            }
            for (String canonical : valueMap(node.get("values")).values()) {
                if (!STATUS_KEYS.contains(canonical)) {
                    result.errors.add("字段 " + field.getColumn() + "：状态规范值 " + canonical
                            + " 不在运行时段内（可选 " + String.join("/", new TreeSet<>(STATUS_KEYS))
                            + "），该映射不会生效");
                }
            }
        }
    }

    /** W2/W3：值映射自检（key==value、阵营规范值过多）。 */
    private void checkFieldValueMaps(List<FieldSemantic> fields, Result result) {
        for (FieldSemantic field : fields) {
            JsonNode node = parse(field.getSemanticJson());
            if (node == null) {
                continue;
            }
            Map<String, String> values = valueMap(node.get("values"));
            for (Map.Entry<String, String> entry : values.entrySet()) {
                if (entry.getKey().equals(entry.getValue())) {
                    result.warnings.add("字段 " + field.getColumn() + "：值映射 " + entry.getKey()
                            + " → " + entry.getValue() + " 与原始值相同，该映射无实际作用");
                }
            }
            if (isFactionLike(field.getColumn(), values)) {
                Set<String> canonical = new LinkedHashSet<>(values.values());
                boolean semanticColored = canonical.stream().anyMatch(FACTION_CANONICAL::contains);
                if (!semanticColored && canonical.size() > 8) {
                    result.warnings.add("字段 " + field.getColumn() + "：阵营规范值有 "
                            + canonical.size() + " 个且都不在 蓝方/红方/blue/red 内，"
                            + "超出语义色范围，颜色将由调色板分配");
                }
            }
        }
    }

    /** W1/W4/W5：数据集级语义与字段注解的口径一致性。 */
    private void checkDatasetConsistency(String datasetSemantic, List<FieldSemantic> fields,
                                         Result result) {
        JsonNode node = parse(datasetSemantic);
        boolean hasDatasetSemantic = node != null && node.size() > 0;
        boolean hasFieldSemantic = false;
        for (FieldSemantic field : fields) {
            JsonNode fieldNode = parse(field.getSemanticJson());
            if (fieldNode != null && fieldNode.size() > 0) {
                hasFieldSemantic = true;
                break;
            }
        }
        if (!hasDatasetSemantic && !hasFieldSemantic) {
            result.warnings.add("该数据集未配置任何语义注解，将回退列名启发式；"
                    + "字段命名不符合约定时地图/航迹可能降级");
            return;
        }
        if (!hasDatasetSemantic) {
            return;
        }
        // W1：声明了 geometry 但没有任何字段声明 lng/lat 角色
        if (node.has("geometry") && node.get("geometry").isObject()) {
            boolean rolePair = fields.stream().anyMatch(field -> {
                JsonNode fieldNode = parse(field.getSemanticJson());
                if (fieldNode == null) {
                    return false;
                }
                String role = fieldNode.path("role").asText("");
                return "lng".equals(role) || "lat".equals(role);
            });
            if (!rolePair) {
                result.warnings.add("数据集级声明了 geometry，但没有任何字段标注 role=lng/lat，"
                        + "两处口径不一致（运行期以 geometry 为准）");
            }
        }
        // W5：entityKind=air 配地面设施类符号
        String entityKind = node.path("entityKind").asText("");
        String symbolDefault = node.path("symbolDefault").asText("");
        if ("air".equals(entityKind) && GROUND_SYMBOLS.contains(symbolDefault)) {
            result.warnings.add("entityKind=air 与 symbolDefault=" + symbolDefault
                    + " 语义不匹配，空中平台通常使用 fighter/awacs/recon/bomber");
        }
    }

    // ──────────────────────────────────────────────────────────────────
    // ③ 值域采样（受限、仅告警、库不可达则跳过）
    // ──────────────────────────────────────────────────────────────────

    private void sampleValueDomains(String datasetId, String tableName, List<FieldSemantic> fields,
                                    Map<String, String> columnIndex, Result result) {
        if (sqlExecutionService == null) {
            return;
        }
        if (tableName == null || !SAFE_IDENT.matcher(tableName.trim()).matches()) {
            result.warnings.add("表名缺失或包含特殊字符，已跳过值域采样校验");
            return;
        }
        String table = tableName.trim();
        int sampledColumns = 0;
        boolean skippedForLimit = false;
        for (FieldSemantic field : fields) {
            JsonNode fieldNode = parse(field.getSemanticJson());
            Map<String, String> values = valueMap(fieldNode == null ? null : fieldNode.get("values"));
            if (values.isEmpty()) {
                continue;
            }
            if (!columnIndex.containsKey(key(field.getColumn()))) {
                continue;   // 列不存在已由 R1 拒绝，无需采样
            }
            if (sampledColumns >= MAX_SAMPLE_COLUMNS) {
                skippedForLimit = true;
                continue;
            }
            if (!SAFE_IDENT.matcher(field.getColumn()).matches()) {
                result.warnings.add("字段 " + field.getColumn()
                        + "：列名包含特殊字符，已跳过该列的值域采样校验");
                continue;
            }
            sampledColumns++;
            sampleOneColumn(datasetId, table, field.getColumn(), values.keySet(), result);
        }
        if (skippedForLimit) {
            result.warnings.add("本次保存的值域采样只覆盖前 " + MAX_SAMPLE_COLUMNS
                    + " 个带值映射的列，其余列未校验");
        }
    }

    private void sampleOneColumn(String datasetId, String table, String column,
                                 Set<String> declared, Result result) {
        String sql = "SELECT " + column + " AS dim_value, COUNT(*) AS cnt FROM " + table
                + " GROUP BY " + column + " ORDER BY cnt DESC";
        Map<String, Object> payload;
        try {
            payload = sqlExecutionService.executeSql(datasetId, sql);
        } catch (Exception e) {
            logger.warn("值域采样异常 table={} column={}: {}", table, column, e.getMessage());
            result.warnings.add("字段 " + column + "：值域采样失败（" + e.getClass().getSimpleName()
                    + "），本次未校验该列");
            return;
        }
        if (payload == null || !Boolean.TRUE.equals(payload.get("success"))) {
            // 业务库不可达/无权限等：跳过即可，绝不因此拒绝保存
            String message = payload == null ? "无响应" : text(payload.get("message"));
            logger.warn("值域采样失败 table={} column={} message={}", table, column, message);
            result.warnings.add("字段 " + column + "：未能采样真实取值（" + abbreviate(message)
                    + "），本次未校验该列");
            return;
        }
        result.sampled = true;
        Set<String> actual = new LinkedHashSet<>();
        Object rows = payload.get("rows");
        if (rows instanceof List<?> list) {
            for (Object item : list) {
                if (!(item instanceof Map<?, ?> row)) {
                    continue;
                }
                Object value = row.get("dim_value");
                if (value != null && !value.toString().isBlank()) {
                    actual.add(value.toString());
                    if (actual.size() >= MAX_SAMPLE_VALUES) {
                        break;
                    }
                }
            }
        }
        Set<String> missing = new TreeSet<>(declared);
        missing.removeAll(actual);
        Set<String> extra = new TreeSet<>(actual);
        extra.removeAll(declared);
        if (!missing.isEmpty()) {
            result.warnings.add("字段 " + column + "：注解声明但真实数据中未出现的取值 —— "
                    + join(abbreviateAll(missing)) + "（可能是拼写错误或该枚举尚未启用）");
        }
        if (!extra.isEmpty()) {
            result.warnings.add("字段 " + column + "：真实数据出现但注解未声明的取值 —— "
                    + join(abbreviateAll(extra)) + "（建议补充注解，否则该取值不会参与语义判定）");
        }
    }

    // ──────────────────────────────────────────────────────────────────
    // 小工具
    // ──────────────────────────────────────────────────────────────────

    private Map<String, String> indexColumns(List<Map<String, Object>> tableColumns) {
        Map<String, String> index = new LinkedHashMap<>();
        if (tableColumns == null) {
            return index;
        }
        for (Map<String, Object> column : tableColumns) {
            if (column == null) {
                continue;
            }
            String name = text(column.get("columnName"));
            if (!name.isBlank()) {
                index.put(key(name), name);
            }
        }
        return index;
    }

    private JsonNode parse(String semanticJson) {
        if (semanticJson == null || semanticJson.isBlank()) {
            return null;
        }
        try {
            JsonNode node = mapper.readTree(semanticJson);
            return node != null && node.isObject() ? node : null;
        } catch (Exception e) {
            return null;
        }
    }

    private Map<String, String> valueMap(JsonNode values) {
        Map<String, String> map = new LinkedHashMap<>();
        if (values == null || !values.isObject()) {
            return map;
        }
        values.fields().forEachRemaining(entry ->
                map.put(entry.getKey(), entry.getValue().asText("")));
        return map;
    }

    /** 该字段是否是"阵营类"（列名带阵营线索，且配了值映射）。 */
    private boolean isFactionLike(String column, Map<String, String> values) {
        if (values.isEmpty()) {
            return false;
        }
        String low = column.toLowerCase(Locale.ROOT);
        return low.contains("faction") || low.contains("camp") || low.contains("side")
                || low.contains("阵营") || low.contains("归属");
    }

    private static String key(String column) {
        return column == null ? "" : column.trim().toLowerCase(Locale.ROOT);
    }

    private static String text(Object value) {
        return value == null ? "" : value.toString();
    }

    private String abbreviate(String message) {
        String text = message == null ? "" : message;
        return text.length() <= 80 ? text : text.substring(0, 80) + "…";
    }

    private static List<String> abbreviateAll(Set<String> values) {
        List<String> out = new ArrayList<>();
        int count = 0;
        for (String value : values) {
            out.add(value);
            if (++count >= 5) {
                break;
            }
        }
        if (values.size() > out.size()) {
            out.add("等 " + values.size() + " 个");
        }
        return out;
    }

    private static String join(List<String> items) {
        return String.join("、", items);
    }

    private static String sha256(String text) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest(text.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            for (byte b : bytes) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            return "";
        }
    }
}
