package com.assessment.admin.service;

import com.assessment.admin.service.AnnotationValidator.FieldSemantic;
import com.assessment.admin.service.AnnotationValidator.Result;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 注解校验器测试：结构一致性规则（R1–R7）与软告警（W1–W5）。
 *
 * 值域采样需要真实业务库，单测注入 {@code null} 的 SqlExecutionService 使其跳过；
 * 采样的失败降级（库不可达不阻塞保存）由 {@link #samplingIsSkippedWithoutService()} 覆盖。
 */
class AnnotationValidatorTest {

    /** 被测对象：不接数据库，只做结构与语义规则。 */
    private final AnnotationValidator validator = new AnnotationValidator(null);

    private static List<Map<String, Object>> columns(String... names) {
        List<Map<String, Object>> list = new ArrayList<>();
        for (String name : names) {
            Map<String, Object> column = new LinkedHashMap<>();
            column.put("columnName", name);
            column.put("dataType", "VARCHAR");
            column.put("comment", "");
            list.add(column);
        }
        return list;
    }

    private static List<FieldSemantic> fields(String column, String semanticJson) {
        List<FieldSemantic> list = new ArrayList<>();
        list.add(new FieldSemantic(column, semanticJson));
        return list;
    }

    private static boolean hasError(Result result, String keyword) {
        return result.getErrors().stream().anyMatch(item -> item.contains(keyword));
    }

    private static boolean hasWarning(Result result, String keyword) {
        return result.getWarnings().stream().anyMatch(item -> item.contains(keyword));
    }

    // ── R1：字段注解的列必须存在 ─────────────────────────────────────

    @Test
    void unknownFieldColumnIsRejected() {
        Result result = validator.validate("t", columns("id", "name"),
                null, fields("not_exist", "{\"role\":\"lng\"}"), null);
        assertTrue(result.isRejected());
        assertTrue(hasError(result, "not_exist"));
    }

    @Test
    void knownFieldColumnPasses() {
        Result result = validator.validate("t", columns("id", "track_lng"),
                null, fields("track_lng", "{\"role\":\"lng\"}"), null);
        assertFalse(result.isRejected(), String.join("；", result.getErrors()));
    }

    // ── R2/R3/R4/R5：数据集级语义引用的列必须存在 ────────────────────

    @Test
    void geometryColumnMustExist() {
        String semantic = "{\"geometry\":{\"lngColumn\":\"lng\",\"latColumn\":\"nope\"}}";
        Result result = validator.validate("t", columns("lng"),
                semantic, List.of(), null);
        assertTrue(result.isRejected());
        assertTrue(hasError(result, "geometry.latColumn"));
    }

    @Test
    void trackGroupKeyAndEventTimeColumnMustExist() {
        String semantic = "{\"trackGroupKey\":[\"aircraft_id\",\"ghost\"],"
                + "\"eventTimeColumn\":\"missing_time\"}";
        Result result = validator.validate("t", columns("aircraft_id", "record_time"),
                semantic, List.of(), null);
        assertTrue(result.isRejected());
        assertTrue(hasError(result, "trackGroupKey"));
        assertTrue(hasError(result, "eventTimeColumn"));
    }

    @Test
    void validDatasetSemanticPasses() {
        String semantic = "{\"entityKind\":\"air\",\"trackGroupKey\":[\"aircraft_id\"],"
                + "\"eventTimeColumn\":\"record_time\","
                + "\"geometry\":{\"lngColumn\":\"track_lng\",\"latColumn\":\"track_lat\"}}";
        Result result = validator.validate("t",
                columns("aircraft_id", "record_time", "track_lng", "track_lat"),
                semantic, List.of(), null);
        assertFalse(result.isRejected(), String.join("；", result.getErrors()));
    }

    // ── R6：同一严格角色不得重复 ─────────────────────────────────────

    @Test
    void duplicatedStrictRoleIsRejected() {
        List<FieldSemantic> items = new ArrayList<>();
        items.add(new FieldSemantic("a_lng", "{\"role\":\"lng\"}"));
        items.add(new FieldSemantic("b_lng", "{\"role\":\"lng\"}"));
        Result result = validator.validate("t", columns("a_lng", "b_lng"), null, items, null);
        assertTrue(result.isRejected());
        assertTrue(hasError(result, "角色 lng"));
    }

    @Test
    void duplicatedDimensionRoleIsAllowed() {
        List<FieldSemantic> items = new ArrayList<>();
        items.add(new FieldSemantic("kind", "{\"role\":\"dimension\"}"));
        items.add(new FieldSemantic("area", "{\"role\":\"dimension\"}"));
        Result result = validator.validate("t", columns("kind", "area"), null, items, null);
        assertFalse(result.isRejected(), String.join("；", result.getErrors()));
    }

    // ── R7：status 规范值必须在运行时段内 ────────────────────────────

    @Test
    void unknownStatusCanonicalIsRejected() {
        String semantic = "{\"role\":\"status\",\"values\":{\"轻损\":\"slight\"}}";
        Result result = validator.validate("t", columns("damage_status"), null,
                fields("damage_status", semantic), null);
        assertTrue(result.isRejected());
        assertTrue(hasError(result, "slight"));
    }

    @Test
    void knownStatusCanonicalPasses() {
        String semantic = "{\"role\":\"status\",\"values\":{\"轻损\":\"light\",\"已摧毁\":\"destroyed\"}}";
        Result result = validator.validate("t", columns("damage_status"), null,
                fields("damage_status", semantic), null);
        assertFalse(result.isRejected(), String.join("；", result.getErrors()));
    }

    // ── W1/W2/W4/W5：软告警 ─────────────────────────────────────────

    @Test
    void geometryWithoutRoleFieldsWarns() {
        String semantic = "{\"geometry\":{\"lngColumn\":\"lng\",\"latColumn\":\"lat\"}}";
        Result result = validator.validate("t", columns("lng", "lat"), semantic, List.of(), null);
        assertFalse(result.isRejected());
        assertTrue(hasWarning(result, "role=lng/lat"));
    }

    @Test
    void identityValueMappingWarns() {
        String semantic = "{\"role\":\"dimension\",\"values\":{\"红方\":\"红方\"}}";
        Result result = validator.validate("t", columns("faction"), null,
                fields("faction", semantic), null);
        assertFalse(result.isRejected());
        assertTrue(hasWarning(result, "无实际作用"));
    }

    @Test
    void unannotatedDatasetWarns() {
        Result result = validator.validate("t", columns("id", "name"), null, List.of(), null);
        assertFalse(result.isRejected());
        assertTrue(hasWarning(result, "未配置任何语义注解"));
    }

    @Test
    void airEntityKindWithGroundSymbolWarns() {
        String semantic = "{\"entityKind\":\"air\",\"symbolDefault\":\"sam\"}";
        Result result = validator.validate("t", columns("id"), semantic, List.of(), null);
        assertFalse(result.isRejected());
        assertTrue(hasWarning(result, "语义不匹配"));
    }

    // ── 结构不可得与采样降级 ────────────────────────────────────────

    @Test
    void unreadableStructureSkipsStructureRules() {
        Result result = validator.validate("t", List.of(), null,
                fields("whatever", "{\"role\":\"lng\"}"), null);
        assertFalse(result.isRejected());
        assertFalse(result.isStructureChecked());
        assertTrue(hasWarning(result, "跳过结构一致性校验"));
    }

    @Test
    void samplingIsSkippedWithoutService() {
        String semantic = "{\"role\":\"dimension\",\"values\":{\"本方\":\"blue\"}}";
        Result result = validator.validate("t", columns("faction"), null,
                fields("faction", semantic), "ds_1");
        assertFalse(result.isRejected());
        assertFalse(result.isSampled(), "未接入数据库服务时不得声称完成采样校验");
    }

    // ── 结构指纹 ───────────────────────────────────────────────────

    @Test
    void fingerprintIsStableAndStructureSensitive() {
        String first = validator.fingerprint("t", columns("id", "name"));
        String again = validator.fingerprint("t", columns("id", "name"));
        String changed = validator.fingerprint("t", columns("id", "name", "extra"));
        assertEquals(first, again);
        assertNotEquals(first, changed);
    }
}
