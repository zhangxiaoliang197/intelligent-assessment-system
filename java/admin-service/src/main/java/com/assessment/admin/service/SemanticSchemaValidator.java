package com.assessment.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;
import com.networknt.schema.ValidationMessage;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * 领域语义注解（semantic_json）的格式校验器。
 *
 * 设计口径：
 * 1. 格式规范只存一份 {@code resources/semantic-schema.json}（JSON Schema 2020-12），
 *    由 {@code /api/admin/export/for-llm} 随元数据下发给 Python 侧复用，避免两端各存一份漂移；
 * 2. 校验失败返回中文条目列表（含字段路径），由调用方决定是拦截保存还是仅告警；
 * 3. schema 未能加载时 {@link #isAvailable()} 为假、校验返回空列表，调用方须向用户提示
 *    "本次未校验"——禁止静默放行（历史缺陷：无注解即静默跳过）。
 */
@Service
public class SemanticSchemaValidator {

    private static final Logger logger = LoggerFactory.getLogger(SemanticSchemaValidator.class);

    /** 规范文件路径（classpath） */
    private static final String SCHEMA_RESOURCE = "semantic-schema.json";
    /** 数据集级子模式引用 */
    private static final String DATASET_REF = "datasetSemantic";
    /** 字段级子模式引用 */
    private static final String FIELD_REF = "fieldSemantic";

    private final ObjectMapper mapper = new ObjectMapper();

    private JsonSchema datasetSchema;
    private JsonSchema fieldSchema;
    private String rawSchema = "";
    private String unavailableReason = "";

    @PostConstruct
    public void init() {
        try (InputStream in = SemanticSchemaValidator.class.getClassLoader()
                .getResourceAsStream(SCHEMA_RESOURCE)) {
            if (in == null) {
                unavailableReason = "classpath 下未找到 " + SCHEMA_RESOURCE;
                logger.error("语义注解校验器不可用：{}", unavailableReason);
                return;
            }
            JsonNode root = mapper.readTree(in);
            rawSchema = mapper.writerWithDefaultPrettyPrinter().writeValueAsString(root);
            JsonSchemaFactory factory = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012);
            datasetSchema = factory.getSchema(subSchemaNode(root, DATASET_REF));
            fieldSchema = factory.getSchema(subSchemaNode(root, FIELD_REF));
            logger.info("语义注解校验器已就绪（schema {} 字节）", rawSchema.length());
        } catch (Exception e) {
            unavailableReason = e.getClass().getSimpleName() + ": " + e.getMessage();
            datasetSchema = null;
            fieldSchema = null;
            logger.error("语义注解校验器不可用：{}", unavailableReason, e);
        }
    }

    /**
     * 构造子模式节点：把 {@code $ref} 指向根 schema 内的 {@code $defs} 条目，
     * 并带上 {@code $defs} 以便本地引用可解析。
     */
    private JsonNode subSchemaNode(JsonNode root, String defName) {
        com.fasterxml.jackson.databind.node.ObjectNode node = mapper.createObjectNode();
        node.put("$ref", "#/$defs/" + defName);
        node.set("$defs", root.get("$defs"));
        return node;
    }

    /** 校验器是否可用（schema 是否成功加载）。 */
    public boolean isAvailable() {
        return datasetSchema != null && fieldSchema != null;
    }

    /** 不可用原因（可用时为空串），供接口向用户提示。 */
    public String getUnavailableReason() {
        return unavailableReason;
    }

    /** 规范文件原文（供元数据接口下发给 Python 侧，保持两端同一份）。 */
    public String rawSchema() {
        return rawSchema;
    }

    /** 校验数据集级语义，返回中文错误条目（空列表表示通过）。 */
    public List<String> validateDataset(String json) {
        return validate(datasetSchema, json, "数据集级语义");
    }

    /** 校验字段级语义，返回中文错误条目（空列表表示通过）。 */
    public List<String> validateField(String json) {
        return validate(fieldSchema, json, "字段级语义");
    }

    private List<String> validate(JsonSchema schema, String json, String label) {
        List<String> errors = new ArrayList<>();
        if (schema == null) {
            return errors;
        }
        if (json == null || json.isBlank()) {
            // 未配置语义是合法状态：消费侧回退到 businessMeaning 解析
            return errors;
        }
        JsonNode instance;
        try {
            instance = mapper.readTree(json);
        } catch (Exception e) {
            errors.add(label + "不是合法 JSON：" + e.getMessage());
            return errors;
        }
        if (instance == null || instance.isNull()) {
            return errors;
        }
        if (!instance.isObject()) {
            errors.add(label + "必须是 JSON 对象");
            return errors;
        }
        Set<ValidationMessage> messages = schema.validate(instance);
        for (ValidationMessage m : messages) {
            errors.add(label + " " + m.getMessage());
        }
        return errors;
    }
}
