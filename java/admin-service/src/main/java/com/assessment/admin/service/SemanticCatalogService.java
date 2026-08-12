package com.assessment.admin.service;

import com.assessment.admin.model.Dataset;
import com.assessment.admin.model.FieldAnnotation;
import com.assessment.admin.model.FieldSynonym;
import com.assessment.admin.repository.DatasetRepository;
import com.assessment.admin.repository.FieldAnnotationRepository;
import com.assessment.admin.repository.FieldSynonymRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.*;
import java.util.regex.Pattern;

/**
 * 语义目录（Semantic Catalog）服务。
 * 建立"业务概念 → 物理列"的索引，供指标编译器确定性解析公式项。
 * 数据来源：
 *   1. 数据集字段标注（ass_field_annotation）：annotation / businessMeaning / columnComment
 *   2. 人工维护的同义词条目（ass_field_synonym）
 * 匹配方式：归一化精确匹配 + 包含匹配（业务概念较长的场景）。
 */
@Service
public class SemanticCatalogService {

    private static final Pattern NORM_PATTERN = Pattern.compile(
            "[\\s\\u3000（）()【】\\[\\]《》<>「」“”‘’\\-_·、，。！？：；]+");

    @Autowired
    private DatasetRepository datasetRepo;

    @Autowired
    private FieldAnnotationRepository fieldAnnotationRepo;

    @Autowired
    private FieldSynonymRepository fieldSynonymRepo;

    @Autowired
    private SqlExecutionService sqlExecutionService;

    public static String normalize(String text) {
        if (text == null || text.isEmpty()) return "";
        return NORM_PATTERN.matcher(text).replaceAll("").toLowerCase(Locale.ROOT);
    }

    /** 从字段标注 + 人工同义词重建语义目录（幂等：同 concept+column 覆盖更新）。 */
    public Map<String, Object> rebuildCatalog(String databaseId) {
        List<Dataset> datasets = (databaseId == null || databaseId.isEmpty())
                ? datasetRepo.findAll()
                : datasetRepo.findByDatabaseId(databaseId);

        List<FieldSynonym> syns = new ArrayList<>();
        int created = 0;
        int updated = 0;
        Map<String, FieldSynonym> existing = new HashMap<>();
        for (FieldSynonym s : fieldSynonymRepo.findAll()) {
            existing.put(key(s.getConceptNorm(), s.getDatasetId(), s.getColumnName()), s);
        }

        for (Dataset ds : datasets) {
            List<FieldAnnotation> anns = fieldAnnotationRepo.findByDatasetId(ds.getId());
            for (FieldAnnotation a : anns) {
                List<String> concepts = new ArrayList<>();
                addConcept(concepts, a.getAnnotation());
                addConcept(concepts, a.getBusinessMeaning());
                addConcept(concepts, a.getColumnComment());
                for (String concept : concepts) {
                    String k = key(normalize(concept), ds.getId(), a.getColumnName());
                    FieldSynonym s = existing.get(k);
                    if (s == null) {
                        s = new FieldSynonym();
                        s.setId("fs_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12));
                        s.setConcept(concept);
                        s.setConceptNorm(normalize(concept));
                        s.setDatabaseId(ds.getDatabaseId());
                        s.setDatasetId(ds.getId());
                        s.setTableName(a.getTableName());
                        s.setColumnName(a.getColumnName());
                        s.setColumnComment(a.getColumnComment());
                        s.setSource("annotation");
                        syns.add(s);
                        existing.put(k, s);
                        created++;
                    } else if (s.getColumnComment() == null && a.getColumnComment() != null) {
                        s.setColumnComment(a.getColumnComment());
                        updated++;
                    }
                }
            }
        }
        // live schema 兜底：真实表列（字段标注可能不全）也进入语义目录
        for (Dataset ds : datasets) {
            if (ds.getDatabaseId() == null || ds.getDatabaseId().isEmpty()) continue;
            List<String> liveCols = sqlExecutionService.listColumnsOnDatabase(
                    ds.getDatabaseId(), ds.getTableName());
            for (String col : liveCols) {
                if (col == null || col.isBlank()) continue;
                String k = key(normalize(col), ds.getId(), col);
                if (existing.containsKey(k)) continue;
                FieldSynonym s = new FieldSynonym();
                s.setId("fs_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12));
                s.setConcept(col);
                s.setConceptNorm(normalize(col));
                s.setDatabaseId(ds.getDatabaseId());
                s.setDatasetId(ds.getId());
                s.setTableName(ds.getTableName());
                s.setColumnName(col);
                s.setColumnComment("");
                s.setSource("schema");
                syns.add(s);
                existing.put(k, s);
                created++;
            }
        }
        if (!syns.isEmpty()) {
            fieldSynonymRepo.saveAll(syns);
        }

        return Map.of(
                "success", true,
                "created", created,
                "updated", updated,
                "total", fieldSynonymRepo.count(),
                "databaseId", databaseId == null ? "" : databaseId);
    }

    /** 搜索概念对应的候选列（归一化精确 > 包含，按来源可靠性排序）。 */
    public List<Map<String, Object>> searchConcept(String concept, String databaseId, int limit) {
        String norm = normalize(concept);
        if (norm.isEmpty()) return List.of();
        List<FieldSynonym> exact = fieldSynonymRepo.findByConceptNorm(norm);
        List<Map<String, Object>> results = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        int max = Math.max(1, Math.min(limit <= 0 ? 10 : limit, 50));

        for (FieldSynonym s : exact) {
            if (databaseId != null && !databaseId.isEmpty()
                    && s.getDatabaseId() != null && !databaseId.equals(s.getDatabaseId())) {
                continue;
            }
            addResult(results, seen, s, 1.0);
        }

        if (results.size() < max) {
            List<FieldSynonym> all = (databaseId == null || databaseId.isEmpty())
                    ? fieldSynonymRepo.findAll()
                    : fieldSynonymRepo.findByDatabaseId(databaseId);
            List<Scored> scored = new ArrayList<>();
            for (FieldSynonym s : all) {
                if (seen.contains(s.getId())) continue;
                double sim = containmentSimilarity(norm, s.getConceptNorm());
                if (sim > 0) {
                    scored.add(new Scored(s, sim));
                }
            }
            scored.sort((a, b) -> Double.compare(b.sim, a.sim));
            for (Scored sc : scored) {
                if (results.size() >= max) break;
                addResult(results, seen, sc.s, sc.sim);
            }
        }
        return results;
    }

    /** 某数据源下的完整目录视图（供前端绑定编辑器 / LLM 建议使用）。 */
    public Map<String, Object> catalogForDatabase(String databaseId) {
        List<Dataset> datasets = (databaseId == null || databaseId.isEmpty())
                ? datasetRepo.findAll()
                : datasetRepo.findByDatabaseId(databaseId);
        List<Map<String, Object>> tables = new ArrayList<>();
        for (Dataset ds : datasets) {
            Map<String, Object> table = new LinkedHashMap<>();
            table.put("datasetName", ds.getName());
            table.put("tableName", ds.getTableName());
            table.put("description", ds.getDescription());
            table.put("keyMappings", ds.getKeyMappings());
            Map<String, Map<String, Object>> annByCol = new LinkedHashMap<>();
            for (FieldAnnotation a : fieldAnnotationRepo.findByDatasetId(ds.getId())) {
                Map<String, Object> c = new LinkedHashMap<>();
                c.put("columnName", a.getColumnName());
                c.put("dataType", a.getColumnType());
                c.put("comment", a.getColumnComment());
                c.put("annotation", a.getAnnotation());
                c.put("businessMeaning", a.getBusinessMeaning());
                c.put("dataCategory", a.getDataCategory());
                annByCol.put(a.getColumnName(), c);
            }
            List<Map<String, Object>> cols = new ArrayList<>();
            Set<String> seenCols = new LinkedHashSet<>();
            List<String> liveCols = (ds.getDatabaseId() == null || ds.getDatabaseId().isEmpty())
                    ? List.of()
                    : sqlExecutionService.listColumnsOnDatabase(ds.getDatabaseId(), ds.getTableName());
            for (String col : liveCols) {
                if (col == null || col.isBlank() || seenCols.contains(col)) continue;
                seenCols.add(col);
                if (annByCol.containsKey(col)) {
                    cols.add(annByCol.get(col));
                } else {
                    Map<String, Object> c = new LinkedHashMap<>();
                    c.put("columnName", col);
                    c.put("dataType", "");
                    c.put("comment", "");
                    c.put("annotation", "");
                    c.put("businessMeaning", "");
                    c.put("dataCategory", "");
                    cols.add(c);
                }
            }
            for (Map.Entry<String, Map<String, Object>> e : annByCol.entrySet()) {
                if (!seenCols.contains(e.getKey())) cols.add(e.getValue());
            }
            table.put("columns", cols);
            tables.add(table);
        }
        return Map.of("success", true, "databaseId", databaseId == null ? "" : databaseId, "tables", tables);
    }

    /** 保存人工同义词条目（幂等 upsert）。 */
    public Map<String, Object> upsertSynonym(Map<String, Object> body) {
        String concept = str(body.get("concept"));
        String databaseId = str(body.get("databaseId"));
        String datasetId = str(body.get("datasetId"));
        String tableName = str(body.get("tableName"));
        String columnName = str(body.get("columnName"));
        if (concept.isEmpty() || columnName.isEmpty()) {
            return Map.of("success", false, "message", "concept 与 columnName 必填");
        }
        List<FieldSynonym> hits = fieldSynonymRepo.findByConceptNorm(normalize(concept));
        FieldSynonym s = null;
        for (FieldSynonym h : hits) {
            if (Objects.equals(h.getDatasetId(), datasetId)
                    && Objects.equals(h.getColumnName(), columnName)) {
                s = h;
                break;
            }
        }
        if (s == null) {
            s = new FieldSynonym();
            s.setId("fs_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12));
            s.setConcept(concept);
            s.setConceptNorm(normalize(concept));
            s.setSource(str(body.getOrDefault("source", "manual")));
        }
        s.setDatabaseId(databaseId);
        s.setDatasetId(datasetId);
        s.setTableName(tableName);
        s.setColumnName(columnName);
        s.setColumnComment(str(body.get("columnComment")));
        fieldSynonymRepo.save(s);
        return Map.of("success", true, "id", s.getId());
    }

    /** 语义目录维护页：列出同义词条目（支持按数据源/关键字过滤）。 */
    public Map<String, Object> listSynonyms(String databaseId, String keyword, int limit) {
        List<FieldSynonym> all = (databaseId == null || databaseId.isEmpty())
                ? fieldSynonymRepo.findAll()
                : fieldSynonymRepo.findByDatabaseId(databaseId);
        String kw = normalize(keyword);
        int max = Math.max(1, Math.min(limit <= 0 ? 200 : limit, 1000));
        List<Map<String, Object>> items = new ArrayList<>();
        for (FieldSynonym s : all) {
            if (!kw.isEmpty()) {
                String hay = normalize(s.getConcept() + " " + s.getTableName() + " "
                        + s.getColumnName() + " " + s.getColumnComment());
                if (!hay.contains(kw)) continue;
            }
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", s.getId());
            m.put("concept", s.getConcept());
            m.put("databaseId", s.getDatabaseId());
            m.put("datasetId", s.getDatasetId());
            m.put("datasetName", datasetName(s.getDatasetId()));
            m.put("tableName", s.getTableName());
            m.put("columnName", s.getColumnName());
            m.put("columnComment", s.getColumnComment());
            m.put("source", s.getSource());
            m.put("createTime", s.getCreateTime() == null ? "" : s.getCreateTime().toString());
            m.put("updateTime", s.getUpdateTime() == null ? "" : s.getUpdateTime().toString());
            items.add(m);
            if (items.size() >= max) break;
        }
        return Map.of("success", true, "total", items.size(), "items", items);
    }

    /** 删除同义词条目（重建目录时会被字段标注重新生成，此处仅删除人工/LLM 条目）。 */
    public Map<String, Object> deleteSynonym(String id) {
        if (id == null || id.isBlank()) {
            return Map.of("success", false, "message", "缺少同义词 ID");
        }
        Optional<FieldSynonym> opt = fieldSynonymRepo.findById(id);
        if (opt.isEmpty()) {
            return Map.of("success", false, "message", "同义词条目不存在: " + id);
        }
        fieldSynonymRepo.deleteById(id);
        return Map.of("success", true, "message", "已删除同义词条目");
    }

    private void addConcept(List<String> concepts, String text) {
        if (text == null || text.trim().isEmpty()) return;
        for (String line : text.split("\\n")) {
            String t = line.trim();
            if (t.length() >= 2 && t.length() <= 200 && !concepts.contains(t)) {
                concepts.add(t);
            }
        }
    }

    private void addResult(List<Map<String, Object>> out, Set<String> seen,
                           FieldSynonym s, double sim) {
        if (seen.contains(s.getId())) return;
        seen.add(s.getId());
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("concept", s.getConcept());
        m.put("datasetName", datasetName(s.getDatasetId()));
        m.put("tableName", s.getTableName());
        m.put("columnName", s.getColumnName());
        m.put("columnComment", s.getColumnComment());
        m.put("source", s.getSource());
        m.put("score", Math.round(sim * 1000) / 1000.0);
        out.add(m);
    }

    private String datasetName(String datasetId) {
        return datasetRepo.findById(datasetId).map(Dataset::getName).orElse("");
    }

    private double containmentSimilarity(String norm, String targetNorm) {
        if (norm.isEmpty() || targetNorm.isEmpty()) return 0;
        if (norm.equals(targetNorm)) return 1.0;
        if (norm.length() >= 3 && (norm.contains(targetNorm) || targetNorm.contains(norm))) {
            return 0.7;
        }
        return 0;
    }

    private String key(String conceptNorm, String datasetId, String columnName) {
        return conceptNorm + "|" + (datasetId == null ? "" : datasetId) + "|" + columnName;
    }

    private String str(Object o) {
        return o == null ? "" : String.valueOf(o);
    }

    private static class Scored {
        final FieldSynonym s;
        final double sim;
        Scored(FieldSynonym s, double sim) {
            this.s = s;
            this.sim = sim;
        }
    }
}
