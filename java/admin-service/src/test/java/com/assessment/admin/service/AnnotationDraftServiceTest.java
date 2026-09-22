package com.assessment.admin.service;

import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 注解草稿服务测试：值域判定规则（决策 E4 —— 编造的值域必须标红且禁止批量通过）。
 *
 * 判定强度按"采样是否可能被截断"分层：样本即全集时才判硬错误，样本达到上限则降级为告警，
 * 避免"合法值只是没进 TOP-N"造成永远无法通过。
 *
 * 被测服务以 {@code null} 注入依赖（与 {@link AnnotationValidatorTest} 同风格），
 * 只覆盖不依赖数据库与模型的纯规则；生成/审核的端到端行为由联调阶段验证。
 */
class AnnotationDraftServiceTest {

    private final AnnotationDraftService service =
            new AnnotationDraftService(null, null, null, null, null, null, null, null);

    /** 采样上限为 30（application.yml 默认），达到即视为可能被截断。 */
    private static List<String> sampleOf(int size) {
        List<String> values = new ArrayList<>();
        for (int i = 0; i < size; i++) {
            values.add("v" + i);
        }
        return values;
    }

    @Test
    void fabricatedValueIsFlagged() {
        // 真实数据里只有"本方/对方"，模型却给出了"第三方"→ 判为编造
        String draft = "{\"role\":\"dimension\",\"values\":{\"本方\":\"blue\",\"第三方\":\"red\"}}";
        List<String> issues = service.validateValueDomain("归属", draft, List.of("本方", "对方")).issues();

        assertEquals(1, issues.size());
        assertTrue(issues.get(0).contains("第三方"), "应指出具体编造的值：" + issues.get(0));
        assertTrue(issues.get(0).contains("疑似编造"), "应标明疑似编造：" + issues.get(0));
    }

    @Test
    void synonymsAreCheckedToo() {
        String draft = "{\"role\":\"dimension\",\"synonyms\":{\"敌军\":\"red\"}}";
        List<String> issues = service.validateValueDomain("归属", draft, List.of("本方", "对方")).issues();

        assertEquals(1, issues.size());
        assertTrue(issues.get(0).contains("synonyms"), "应指出是哪个键出的问题：" + issues.get(0));
    }

    @Test
    void realValuesPass() {
        String draft = "{\"role\":\"dimension\",\"values\":{\"本方\":\"blue\",\"对方\":\"red\"}}";
        assertTrue(service.validateValueDomain("归属", draft, List.of("本方", "对方")).issues().isEmpty());
    }

    @Test
    void samplingUnavailableDoesNotBlock() {
        // 采样失败（列未取到值）时不拦，避免误伤：宁可少拦，也不阻断人工审核
        String draft = "{\"role\":\"dimension\",\"values\":{\"本方\":\"blue\"}}";
        assertTrue(service.validateValueDomain("归属", draft, List.of()).issues().isEmpty());
        assertTrue(service.validateValueDomain("归属", draft, null).issues().isEmpty());
    }

    @Test
    void truncatedSampleDegradesToWarning() {
        // 采样达到上限（30）说明 LIMIT 生效，表里可能还有更多取值：
        // 此时注解外的值只能告警，否则"存在但没进 TOP-N 的合法值"会永远无法通过
        String draft = "{\"role\":\"dimension\",\"values\":{\"罕见取值\":\"heavy\"}}";
        AnnotationDraftService.DomainCheck check =
                service.validateValueDomain("状态", draft, sampleOf(30));

        assertTrue(check.issues().isEmpty(), "截断样本不应判硬错误");
        assertEquals(1, check.warnings().size());
        assertTrue(check.warnings().get(0).contains("未覆盖"), check.warnings().get(0));
        assertTrue(check.warnings().get(0).contains("罕见取值"), check.warnings().get(0));
    }

    @Test
    void fullSampleStillHardBlocks() {
        // 未达上限 ⇒ 样本即全集 ⇒ 仍按硬错误处理（防编造的核心不能丢）
        String draft = "{\"role\":\"dimension\",\"values\":{\"不存在\":\"blue\"}}";
        AnnotationDraftService.DomainCheck check =
                service.validateValueDomain("归属", draft, sampleOf(5));

        assertEquals(1, check.issues().size());
        assertTrue(check.warnings().isEmpty());
    }

    @Test
    void comparisonIgnoresCaseAndSpaces() {
        // 数据库 CHAR 尾空格 / 大小写差异不应误判为编造
        String draft = "{\"role\":\"dimension\",\"values\":{\"本方\":\"blue\"}}";
        assertTrue(service.validateValueDomain("归属", draft, List.of(" 本方 ")).issues().isEmpty());

        String draft2 = "{\"role\":\"dimension\",\"values\":{\"BLUE\":\"blue\"}}";
        assertTrue(service.validateValueDomain("归属", draft2, List.of("blue")).issues().isEmpty());
    }

    @Test
    void statusOnlyDraftWithoutValuesPasses() {
        String draft = "{\"role\":\"status\"}";
        assertTrue(service.validateValueDomain("状态", draft, List.of("在役", "战损")).issues().isEmpty());
    }

    @Test
    void emptyPlaceholdersArePrunedNested() {
        // 模型常用 [] / "" 表示"没有这一项"：必须递归剔除，否则会被 schema 的
        // minItems / minLength 判成硬错误，掩盖真正的建议
        Map<String, Object> raw = new LinkedHashMap<>();
        raw.put("entityKind", "air");
        raw.put("trackGroupKey", List.of());
        raw.put("eventTimeColumn", "");
        raw.put("geometry", new LinkedHashMap<>(Map.of("lngColumn", "home_lng", "radiusColumn", "")));
        raw.put("emptyList", List.of(Map.of()));

        Object pruned = AnnotationDraftService.pruneEmpty(raw);

        assertTrue(pruned instanceof Map, "剔除空值后仍应是对象");
        @SuppressWarnings("unchecked")
        Map<String, Object> cleaned = (Map<String, Object>) pruned;
        assertEquals("air", cleaned.get("entityKind"));
        assertFalse(cleaned.containsKey("trackGroupKey"), "空数组应被剔除");
        assertFalse(cleaned.containsKey("eventTimeColumn"), "空串应被剔除");
        assertFalse(cleaned.containsKey("emptyList"), "只含空对象的数组应被剔除");
        @SuppressWarnings("unchecked")
        Map<String, Object> geometry = (Map<String, Object>) cleaned.get("geometry");
        assertEquals("home_lng", geometry.get("lngColumn"));
        assertFalse(geometry.containsKey("radiusColumn"), "嵌套空串应被剔除");
    }

    @Test
    void allEmptyValuesCollapseToNull() {
        assertNull(AnnotationDraftService.pruneEmpty(new LinkedHashMap<>(Map.of("a", ""))));
        assertNull(AnnotationDraftService.pruneEmpty(List.of("", List.of(), Map.of())));
    }
}
