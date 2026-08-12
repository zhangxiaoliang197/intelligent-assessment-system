package com.assessment.admin.service;

import com.assessment.admin.model.Dataset;
import com.assessment.admin.model.FieldAnnotation;
import com.assessment.admin.model.FieldSynonym;
import com.assessment.admin.model.Indicator;
import com.assessment.admin.repository.DatasetRepository;
import com.assessment.admin.repository.FieldAnnotationRepository;
import com.assessment.admin.repository.FieldSynonymRepository;
import com.assessment.admin.repository.IndicatorRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.*;

/**
 * 指标规格（Indicator Spec）校验与 dry-run。
 *
 * 校验分两层：
 *  1. 结构校验（不碰数据库）：JSON 可解析、绑定/连接键引用真实表列（基于数据集结构 + 语义目录）；
 *  2. dry-run（真实库安全试执行）：对每个来源表执行 `SELECT 1 FROM <t> ... LIMIT 1`，
 *     验证表存在、列可读、账号有权限。只读且限 1 行，不产出最终结果。
 */
@Service
public class IndicatorSpecService {

    @Autowired
    private IndicatorRepository indicatorRepo;

    @Autowired
    private DatasetRepository datasetRepo;

    @Autowired
    private FieldAnnotationRepository fieldAnnotationRepo;

    @Autowired
    private FieldSynonymRepository fieldSynonymRepo;

    @Autowired
    private SqlExecutionService sqlExecutionService;

    private final Map<String, Set<String>> liveColumnsCache = new HashMap<>();

    /** 校验并保存指标规格，返回绑定状态。 */
    public Map<String, Object> saveAndValidate(String indicatorId, String specJson) {
        Optional<Indicator> opt = indicatorRepo.findById(indicatorId);
        if (opt.isEmpty()) {
            return Map.of("success", false, "message", "指标不存在");
        }
        Indicator ind = opt.get();
        if (specJson == null || specJson.trim().isEmpty()) {
            return Map.of("success", false, "message", "indicatorSpec 不能为空");
        }

        Map<String, Object> spec;
        try {
            spec = parseJsonObject(specJson);
        } catch (Exception e) {
            return Map.of("success", false, "message", "indicatorSpec 不是合法 JSON: " + e.getMessage());
        }

        Map<String, Object> validation = validateSpec(spec);
        String status = Boolean.TRUE.equals(validation.get("ready")) ? "ready" : "not_ready";
        ind.setIndicatorSpec(specJson);
        ind.setBindStatus(status);
        indicatorRepo.save(ind);

        Map<String, Object> result = new LinkedHashMap<>(validation);
        result.put("success", true);
        result.put("bindStatus", status);
        return result;
    }

    /** 校验规格（只读，不落库）。 */
    @SuppressWarnings("unchecked")
    public Map<String, Object> validateSpec(Map<String, Object> spec) {
        List<String> errors = new ArrayList<>();
        Map<String, Object> tables = new LinkedHashMap<>();

        List<Map<String, Object>> sourceTables = listOf(spec.get("sourceTables"));
        Map<String, Object> preAggregations = mapOf(spec.get("preAggregations"));
        if (sourceTables.isEmpty() && preAggregations.isEmpty()) {
            errors.add("缺少 sourceTables 或 preAggregations（来源表）");
        }
        for (Map<String, Object> t : sourceTables) {
            String alias = str(t.get("alias"));
            String tableName = str(t.get("tableName"));
            if (alias.isEmpty() || tableName.isEmpty()) {
                errors.add("sourceTables 项缺少 alias 或 tableName");
                continue;
            }
            tables.put(alias, tableName);
        }

        // 连接键：左右两侧必须引用已声明的别名.列，且列存在于数据集结构中
        for (Map<String, Object> km : listOf(spec.get("keyMappings"))) {
            String left = str(km.get("left"));
            String right = str(km.get("right"));
            if (left.isEmpty() || right.isEmpty()) {
                errors.add("keyMappings 项缺少 left/right");
                continue;
            }
            checkColumnRef(left, tables, errors, "连接键");
            checkColumnRef(right, tables, errors, "连接键");
        }

        // 绑定：每个 term 必须有 binding，且引用的表列存在
        List<String> boundTerms = new ArrayList<>();
        for (Map<String, Object> b : listOf(spec.get("bindings"))) {
            String term = str(b.get("term"));
            if (term.isEmpty()) {
                errors.add("bindings 存在缺少 term 的项");
                continue;
            }
            boundTerms.add(term);
            String kind = str(b.get("kind"));
            if (kind.isEmpty()) kind = "agg";
            String table = str(b.get("table"));
            String column = str(b.get("column"));
            String agg = str(b.get("agg"));
            switch (kind) {
                case "direct":
                    if (table.isEmpty() || column.isEmpty()) {
                        errors.add("direct 绑定「" + term + "」缺少 table/column");
                        continue;
                    }
                    break;
                case "expr":
                    if (str(b.get("expr")).isEmpty()) {
                        errors.add("expr 绑定「" + term + "」缺少 expr");
                        continue;
                    }
                    break;
                case "scoped": {
                    Map<String, Object> base = mapOf(b.get("base"));
                    Map<String, Object> scope = mapOf(b.get("scope"));
                    if (base.isEmpty() || str(base.get("column")).isEmpty()) {
                        errors.add("scoped 绑定「" + term + "」缺少 base 列");
                    }
                    if (scope.isEmpty() || str(scope.get("column")).isEmpty()) {
                        errors.add("scoped 绑定「" + term + "」缺少 scope 列");
                    }
                    continue;
                }
                default:
                    if (table.isEmpty() || column.isEmpty() || agg.isEmpty()) {
                        errors.add("绑定项「" + term + "」缺少 table/column/agg");
                        continue;
                    }
                    break;
            }
            if (kind.equals("expr")) {
                continue; // expr 表达式在编译期做完整校验（Python 编译器为执行前最后一道闸）
            }
            if (!tables.containsKey(table)) {
                errors.add("绑定项「" + term + "」引用了未声明的表别名: " + table);
                continue;
            }
            if (!columnExists(str(tables.get(table)), column)) {
                errors.add("绑定项「" + term + "」的列不存在: "
                        + tables.get(table) + "." + column);
            }
        }

        // output.expression：引用绑定 term 时需已绑定，且需要 output.alias
        Map<String, Object> output = mapOf(spec.get("output"));
        String outputExpr = str(output.get("expression"));
        if (!outputExpr.isEmpty()) {
            if (str(output.get("alias")).isEmpty()) {
                errors.add("output.expression 需要 output.alias");
            }
            java.util.regex.Matcher m = java.util.regex.Pattern
                    .compile("\\$\\{([^}]+)\\}").matcher(outputExpr);
            while (m.find()) {
                if (!boundTerms.contains(m.group(1))) {
                    errors.add("output.expression 引用了未绑定的 term: " + m.group(1));
                }
            }
        }

        // 公式 term 覆盖：简单分词后检查是否有未绑定项（仅提示，不阻断）
        String formula = str(spec.get("formula"));
        List<String> missingTerms = new ArrayList<>();
        if (!formula.isEmpty()) {
            for (String word : splitChineseWords(formula)) {
                boolean hit = boundTerms.stream()
                        .anyMatch(t -> t.contains(word) || word.contains(t));
                if (!hit && word.length() >= 2) {
                    missingTerms.add(word);
                }
            }
        }

        boolean ready = errors.isEmpty();
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("ready", ready);
        result.put("errors", errors);
        result.put("missingTerms", missingTerms);
        result.put("bindingCount", boundTerms.size());
        return result;
    }

    /** dry-run：对每个来源表做一次只读 1 行试查询。 */
    public Map<String, Object> dryRun(String indicatorId) {
        Optional<Indicator> opt = indicatorRepo.findById(indicatorId);
        if (opt.isEmpty()) {
            return Map.of("success", false, "message", "指标不存在");
        }
        Indicator ind = opt.get();
        String specJson = ind.getIndicatorSpec();
        if (specJson == null || specJson.trim().isEmpty()) {
            return Map.of("success", false, "message", "指标尚未配置 indicatorSpec");
        }
        Map<String, Object> spec;
        try {
            spec = parseJsonObject(specJson);
        } catch (Exception e) {
            return Map.of("success", false, "message", "indicatorSpec 解析失败: " + e.getMessage());
        }

        Dataset ds = ind.getDatasetId() == null ? null
                : datasetRepo.findById(ind.getDatasetId()).orElse(null);
        if (ds == null || ds.getDatabaseId() == null) {
            return Map.of("success", false, "message", "指标未关联数据集，无法 dry-run");
        }

        List<String> tableNames = new ArrayList<>();
        for (Map<String, Object> t : listOf(spec.get("sourceTables"))) {
            String tn = str(t.get("tableName"));
            if (!tn.isEmpty() && !tableNames.contains(tn)) tableNames.add(tn);
        }
        for (Object paObj : mapOf(spec.get("preAggregations")).values()) {
            Map<String, Object> pa = mapOf(paObj);
            for (String key : new String[]{"table", "joinTable"}) {
                String tn = str(pa.get(key));
                if (!tn.isEmpty() && !tableNames.contains(tn)) tableNames.add(tn);
            }
        }
        if (tableNames.isEmpty()) {
            return Map.of("success", false, "message", "spec 缺少 sourceTables/preAggregations 来源表");
        }

        List<Map<String, Object>> checks = new ArrayList<>();
        boolean allOk = true;
        for (String tableName : tableNames) {
            String sql = "SELECT 1 FROM " + quoteIdent(tableName) + " WHERE 1=0";
            Map<String, Object> res = sqlExecutionService.executeSqlOnDatabase(ds.getDatabaseId(), sql);
            boolean ok = Boolean.TRUE.equals(res.get("success"));
            if (!ok) allOk = false;
            Map<String, Object> check = new LinkedHashMap<>();
            check.put("table", tableName);
            check.put("ok", ok);
            check.put("message", ok ? "表可读" : res.getOrDefault("message", "试查询失败"));
            checks.add(check);
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("success", true);
        result.put("dryRunOk", allOk);
        result.put("checks", checks);
        return result;
    }

    private void checkColumnRef(String ref, Map<String, Object> tables,
                                List<String> errors, String label) {
        int dot = ref.indexOf('.');
        if (dot <= 0 || dot == ref.length() - 1) {
            errors.add(label + " 格式应为 别名.列名: " + ref);
            return;
        }
        String alias = ref.substring(0, dot);
        String column = ref.substring(dot + 1);
        Object tableName = tables.get(alias);
        if (tableName == null) {
            errors.add(label + " 引用了未声明的别名: " + alias);
            return;
        }
        if (!columnExists(String.valueOf(tableName), column)) {
            errors.add(label + " 的列不存在: " + tableName + "." + column);
        }
    }

    private boolean columnExists(String tableName, String columnName) {
        for (Dataset ds : datasetRepo.findAll()) {
            if (!Objects.equals(ds.getTableName(), tableName)) continue;
            for (FieldAnnotation a : fieldAnnotationRepo.findByDatasetId(ds.getId())) {
                if (Objects.equals(a.getColumnName(), columnName)) return true;
            }
        }
        // 语义目录兜底（live 表列可能未落 field_annotation）
        for (FieldSynonym s : fieldSynonymRepo.findAll()) {
            if (Objects.equals(s.getTableName(), tableName)
                    && Objects.equals(s.getColumnName(), columnName)) {
                return true;
            }
        }
        // live schema 兜底：字段标注/语义目录未覆盖的真实列
        Set<String> live = liveColumnsCache.computeIfAbsent(tableName, this::loadLiveColumns);
        return live.contains(columnName);
    }

    /** 简单标识符原样，含空格等特殊字符的表名用双引号（达梦/Oracle 方言）。 */
    private String quoteIdent(String name) {
        if (name != null && name.matches("[A-Za-z_][A-Za-z0-9_]*")) return name;
        return "\"" + (name == null ? "" : name.replace("\"", "\"\"")) + "\"";
    }

    private Set<String> loadLiveColumns(String tableName) {
        Set<String> cols = new HashSet<>();
        for (Dataset ds : datasetRepo.findAll()) {
            if (!Objects.equals(ds.getTableName(), tableName) || ds.getDatabaseId() == null) {
                continue;
            }
            List<String> list = sqlExecutionService.listColumnsOnDatabase(
                    ds.getDatabaseId(), tableName);
            if (list != null) cols.addAll(list);
        }
        return cols;
    }

    private Map<String, Object> mapOf(Object o) {
        if (o instanceof Map) return (Map<String, Object>) o;
        return Map.of();
    }

    private String str(Object o) {
        return o == null ? "" : String.valueOf(o);
    }

    private List<Map<String, Object>> listOf(Object o) {
        if (!(o instanceof List)) return List.of();
        List<Map<String, Object>> out = new ArrayList<>();
        for (Object item : (List<Object>) o) {
            if (item instanceof Map) out.add((Map<String, Object>) item);
        }
        return out;
    }

    private Map<String, Object> parseJsonObject(String json) throws Exception {
        Object o = new com.fasterxml.jackson.databind.ObjectMapper().readValue(json, Object.class);
        if (!(o instanceof Map)) throw new Exception("顶层必须是 JSON 对象");
        @SuppressWarnings("unchecked")
        Map<String, Object> m = (Map<String, Object>) o;
        return m;
    }

    private List<String> splitChineseWords(String text) {
        // 简单分词：中文连续串 + 英文/数字词
        List<String> words = new ArrayList<>();
        java.util.regex.Matcher m = java.util.regex.Pattern
                .compile("[一-龥]{2,}|[A-Za-z_][A-Za-z0-9_]{1,}")
                .matcher(text);
        while (m.find()) {
            words.add(m.group());
        }
        return words;
    }

}
