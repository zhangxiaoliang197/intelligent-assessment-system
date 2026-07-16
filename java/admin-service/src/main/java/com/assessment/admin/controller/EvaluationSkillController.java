package com.assessment.admin.controller;

import com.assessment.admin.model.Dataset;
import com.assessment.admin.model.EvaluationSkill;
import com.assessment.admin.repository.DatabaseConfigRepository;
import com.assessment.admin.repository.DatasetRepository;
import com.assessment.admin.repository.EvaluationSkillRepository;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/**
 * 评估 Skill 的数据库持久化接口。
 *
 * qa-service 仍负责执行编排；这里负责持久化和第二层数据集归属校验，
 * 从而让多个 qa-service worker 共享同一份、具备唯一约束的数据。
 */
@RestController
@RequestMapping("/api/admin/evaluation/skills")
public class EvaluationSkillController {

    private static final Logger log = LoggerFactory.getLogger(EvaluationSkillController.class);
    private static final int MAX_STEPS = 20;
    private static final DateTimeFormatter TIME_FORMAT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final EvaluationSkillRepository skillRepository;
    private final DatasetRepository datasetRepository;
    private final DatabaseConfigRepository databaseRepository;
    private final ObjectMapper objectMapper;

    public EvaluationSkillController(
            EvaluationSkillRepository skillRepository,
            DatasetRepository datasetRepository,
            DatabaseConfigRepository databaseRepository,
            ObjectMapper objectMapper) {
        this.skillRepository = skillRepository;
        this.datasetRepository = datasetRepository;
        this.databaseRepository = databaseRepository;
        this.objectMapper = objectMapper;
    }

    @GetMapping
    public ResponseEntity<Map<String, Object>> list(
            @RequestParam(name = "databaseId", required = false, defaultValue = "") String databaseId) {
        List<EvaluationSkill> entities = databaseId.isBlank()
                ? skillRepository.findAll()
                : skillRepository.findByDatabaseIdOrderByCreateTimeAsc(databaseId.trim());
        List<Map<String, Object>> skills = entities.stream().map(this::toResponse).toList();
        return ResponseEntity.ok(Map.of("success", true, "skills", skills, "total", skills.size()));
    }

    @GetMapping("/{skillId}")
    public ResponseEntity<Map<String, Object>> get(@PathVariable String skillId) {
        return skillRepository.findById(skillId)
                .map(skill -> ResponseEntity.ok(Map.of("success", true, "skill", toResponse(skill))))
                .orElseGet(() -> ResponseEntity.ok(error("Skill 不存在")));
    }

    @PostMapping
    public ResponseEntity<Map<String, Object>> create(@RequestBody Map<String, Object> body) {
        try {
            ValidatedSkill validated = validate(body, "");
            EvaluationSkill skill = new EvaluationSkill();
            String requestedId = text(body.get("id")).trim();
            if (!requestedId.isEmpty()) {
                if (!requestedId.matches("skill-[A-Za-z0-9_-]{1,25}")) {
                    throw new IllegalArgumentException("Skill ID 格式不正确");
                }
                if (skillRepository.existsById(requestedId)) {
                    throw new IllegalArgumentException("Skill ID 已存在");
                }
                skill.setId(requestedId);
            } else {
                skill.setId("skill-" + UUID.randomUUID().toString().replace("-", "").substring(0, 8));
            }
            apply(skill, validated);
            EvaluationSkill saved = skillRepository.saveAndFlush(skill);
            return ResponseEntity.ok(Map.of("success", true, "skill", toResponse(saved)));
        } catch (IllegalArgumentException ex) {
            return ResponseEntity.ok(error(ex.getMessage()));
        } catch (DataIntegrityViolationException ex) {
            return ResponseEntity.ok(handlePersistenceFailure("创建", ex));
        }
    }

    @PutMapping("/{skillId}")
    public ResponseEntity<Map<String, Object>> update(
            @PathVariable String skillId,
            @RequestBody Map<String, Object> body) {
        Optional<EvaluationSkill> existing = skillRepository.findById(skillId);
        if (existing.isEmpty()) return ResponseEntity.ok(error("Skill 不存在"));
        try {
            ValidatedSkill validated = validate(body, skillId);
            EvaluationSkill skill = existing.get();
            apply(skill, validated);
            EvaluationSkill saved = skillRepository.saveAndFlush(skill);
            return ResponseEntity.ok(Map.of("success", true, "skill", toResponse(saved)));
        } catch (IllegalArgumentException ex) {
            return ResponseEntity.ok(error(ex.getMessage()));
        } catch (DataIntegrityViolationException ex) {
            return ResponseEntity.ok(handlePersistenceFailure("更新", ex));
        }
    }

    @DeleteMapping("/{skillId}")
    public ResponseEntity<Map<String, Object>> delete(@PathVariable String skillId) {
        if (!skillRepository.existsById(skillId)) return ResponseEntity.ok(error("Skill 不存在"));
        skillRepository.deleteById(skillId);
        return ResponseEntity.ok(Map.of("success", true, "message", "Skill 已删除"));
    }

    private ValidatedSkill validate(Map<String, Object> body, String excludeId) {
        String name = text(body.get("name")).trim();
        String description = text(body.get("description")).trim();
        String databaseId = text(body.get("databaseId")).trim();

        if (name.isEmpty()) throw new IllegalArgumentException("请输入 Skill 名称");
        if (name.length() > 100) throw new IllegalArgumentException("Skill 名称不能超过 100 个字符");
        if (description.length() > 1000) throw new IllegalArgumentException("执行目标不能超过 1000 个字符");
        if (databaseId.isEmpty()) throw new IllegalArgumentException("请先选择数据源");
        if (!databaseRepository.existsById(databaseId)) throw new IllegalArgumentException("数据源不存在");

        boolean duplicate = skillRepository.findByDatabaseIdOrderByCreateTimeAsc(databaseId).stream()
                .anyMatch(item -> !item.getId().equals(excludeId)
                        && item.getName().trim().toLowerCase(Locale.ROOT)
                        .equals(name.toLowerCase(Locale.ROOT)));
        if (duplicate) throw new IllegalArgumentException("当前数据源下已存在同名 Skill");

        Object rawSteps = body.get("steps");
        if (!(rawSteps instanceof List<?> stepList) || stepList.isEmpty()) {
            throw new IllegalArgumentException("Skill 至少需要一个数据集查询步骤");
        }
        if (stepList.size() > MAX_STEPS) {
            throw new IllegalArgumentException("单个 Skill 最多支持 " + MAX_STEPS + " 个查询步骤");
        }

        List<Map<String, Object>> normalisedSteps = new ArrayList<>();
        for (int i = 0; i < stepList.size(); i++) {
            int stepNumber = i + 1;
            Object rawStep = stepList.get(i);
            if (!(rawStep instanceof Map<?, ?> step)) {
                throw new IllegalArgumentException("第 " + stepNumber + " 步格式不正确");
            }
            String datasetId = text(step.get("datasetId")).trim();
            String instruction = text(step.get("instruction")).trim();
            Dataset dataset = datasetRepository.findById(datasetId)
                    .orElseThrow(() -> new IllegalArgumentException("第 " + stepNumber + " 步的数据集不存在"));
            if (!databaseId.equals(dataset.getDatabaseId())) {
                throw new IllegalArgumentException("第 " + stepNumber + " 步的数据集不属于当前数据源");
            }
            if (dataset.getTableName() == null || dataset.getTableName().isBlank()) {
                throw new IllegalArgumentException("第 " + stepNumber + " 步的数据集未关联物理表");
            }
            if (instruction.isEmpty()) throw new IllegalArgumentException("请填写第 " + stepNumber + " 步的查询指令");
            if (instruction.length() > 2000) {
                throw new IllegalArgumentException("第 " + stepNumber + " 步的查询指令不能超过 2000 个字符");
            }

            Map<String, Object> normalised = new LinkedHashMap<>();
            normalised.put("datasetId", datasetId);
            normalised.put("datasetName", dataset.getName() == null || dataset.getName().isBlank()
                    ? datasetId : dataset.getName());
            normalised.put("instruction", instruction);
            copyBoolean(step, normalised, "dependsOnPrevious");
            copyBoolean(step, normalised, "requireNonEmpty");
            copyPolicy(step, normalised, "onDependencyFailure");
            copyPolicy(step, normalised, "onEmpty");
            normalisedSteps.add(normalised);
        }

        return new ValidatedSkill(name, description, databaseId, normalisedSteps);
    }

    private void apply(EvaluationSkill entity, ValidatedSkill skill) {
        entity.setName(skill.name());
        entity.setDescription(skill.description());
        entity.setDatabaseId(skill.databaseId());
        try {
            entity.setStepsJson(objectMapper.writeValueAsString(skill.steps()));
        } catch (Exception ex) {
            throw new IllegalArgumentException("Skill 步骤序列化失败");
        }
    }

    private Map<String, Object> toResponse(EvaluationSkill entity) {
        List<Map<String, Object>> steps;
        boolean valid = true;
        String validationMessage = "";
        try {
            steps = objectMapper.readValue(
                    entity.getStepsJson(),
                    new TypeReference<List<Map<String, Object>>>() {}
            );
        } catch (Exception ex) {
            steps = List.of();
            valid = false;
            validationMessage = "Skill 步骤数据损坏，请重新编辑并保存";
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", entity.getId());
        result.put("name", entity.getName());
        result.put("description", entity.getDescription() == null ? "" : entity.getDescription());
        result.put("databaseId", entity.getDatabaseId());
        result.put("steps", steps);
        result.put("valid", valid && !steps.isEmpty());
        result.put("validationMessage", steps.isEmpty() && validationMessage.isEmpty()
                ? "Skill 没有有效查询步骤，请重新编辑并保存" : validationMessage);
        result.put("version", entity.getVersion());
        result.put("createdAt", entity.getCreateTime() == null ? "" : entity.getCreateTime().format(TIME_FORMAT));
        result.put("updatedAt", entity.getUpdateTime() == null ? "" : entity.getUpdateTime().format(TIME_FORMAT));
        return result;
    }

    private static Map<String, Object> error(String message) {
        return Map.of("success", false, "message", message == null ? "操作失败" : message);
    }

    private Map<String, Object> handlePersistenceFailure(
            String operation,
            DataIntegrityViolationException exception) {
        String details = deepestMessage(exception).toLowerCase(Locale.ROOT);
        if (details.contains("uk_eval_skill_database_name")
                || details.contains("duplicate entry")
                || details.contains("duplicate key")) {
            return error("当前数据源下已存在同名 Skill");
        }
        log.error("{} Skill 时发生数据库约束或表结构异常", operation, exception);
        return error("Skill 保存失败：数据库表结构或约束异常，请查看 Admin 服务日志");
    }

    private static String deepestMessage(Throwable throwable) {
        String message = "";
        Throwable current = throwable;
        while (current != null) {
            if (current.getMessage() != null) message = current.getMessage();
            current = current.getCause();
        }
        return message;
    }

    private static String text(Object value) {
        return value == null ? "" : String.valueOf(value);
    }

    private static void copyBoolean(Map<?, ?> source, Map<String, Object> target, String key) {
        Object value = source.get(key);
        if (value instanceof Boolean) target.put(key, value);
    }

    private static void copyPolicy(Map<?, ?> source, Map<String, Object> target, String key) {
        String value = text(source.get(key)).trim().toLowerCase(Locale.ROOT);
        if (List.of("stop", "skip", "continue").contains(value)) target.put(key, value);
    }

    private record ValidatedSkill(
            String name,
            String description,
            String databaseId,
            List<Map<String, Object>> steps) {}
}
