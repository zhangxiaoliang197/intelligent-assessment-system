package com.assessment.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 语义注解校验器的 golden 用例测试。
 *
 * 用例文件 {@code tests/fixtures/semantic_cases.json} 与 Python 侧
 * {@code python/interactive-page-service/tests/test_semantic_validator.py} 共用，
 * 两侧断言同一份通过/拒绝结论，用于证明两端校验实现不漂移。
 */
class SemanticSchemaValidatorTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static SemanticSchemaValidator validator;
    private static JsonNode cases;

    @BeforeAll
    static void setUp() throws Exception {
        validator = new SemanticSchemaValidator();
        validator.init();
        cases = MAPPER.readTree(Files.readString(locateCases()));
    }

    /** 从当前工作目录向上查找用例文件（兼容从模块目录或仓库根运行测试）。 */
    private static Path locateCases() {
        Path dir = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        for (Path candidate = dir; candidate != null; candidate = candidate.getParent()) {
            Path file = candidate.resolve("tests").resolve("fixtures").resolve("semantic_cases.json");
            if (Files.exists(file)) {
                return file;
            }
        }
        throw new IllegalStateException("未找到 tests/fixtures/semantic_cases.json");
    }

    @Test
    void schemaShouldBeLoaded() {
        assertTrue(validator.isAvailable(),
                "语义 schema 未加载成功：" + validator.getUnavailableReason());
        assertTrue(validator.rawSchema().contains("entityKind"),
                "schema 原文应可下发给 Python 侧");
    }

    @Test
    void datasetGoldenCases() {
        assertCases("dataset");
    }

    @Test
    void fieldGoldenCases() {
        assertCases("field");
    }

    private void assertCases(String section) {
        JsonNode list = cases.get(section);
        assertTrue(list != null && list.size() > 0, "用例文件缺少 " + section + " 分组");
        for (JsonNode item : list) {
            String name = item.get("name").asText();
            boolean expected = item.get("valid").asBoolean();
            String value = item.get("value").toString();
            List<String> errors = "dataset".equals(section)
                    ? validator.validateDataset(value)
                    : validator.validateField(value);
            assertEquals(expected, errors.isEmpty(),
                    "用例「" + name + "」判定与预期不符，错误明细=" + errors);
        }
    }

    @Test
    void blankAndInvalidJsonShouldBeTreatedAsUnconfiguredOrRejected() {
        // 空值与空白视为"未配置"，不产生错误（消费侧回退到 businessMeaning）
        assertTrue(validator.validateField("").isEmpty());
        assertTrue(validator.validateField(null).isEmpty());
        assertTrue(validator.validateDataset("   ").isEmpty());
        // 非法 JSON 必须报错，不能静默通过
        assertEquals(1, validator.validateField("{不是 json").size());
        assertEquals(1, validator.validateDataset("[1,2]").size());
    }
}
