package com.assessment.admin.controller;

import com.assessment.admin.model.Dataset;
import com.assessment.admin.model.EvaluationSkill;
import com.assessment.admin.repository.DatabaseConfigRepository;
import com.assessment.admin.repository.DatasetRepository;
import com.assessment.admin.repository.EvaluationSkillRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.dao.DataIntegrityViolationException;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class EvaluationSkillControllerTest {

    @Mock
    private EvaluationSkillRepository skillRepository;
    @Mock
    private DatasetRepository datasetRepository;
    @Mock
    private DatabaseConfigRepository databaseRepository;

    private EvaluationSkillController controller;

    @BeforeEach
    void setUp() {
        controller = new EvaluationSkillController(
                skillRepository,
                datasetRepository,
                databaseRepository,
                new ObjectMapper()
        );
    }

    @Test
    void createNormalisesDatasetIdentityAndPersistsDependencyPolicies() {
        Dataset dataset = dataset("dataset-one", "Server dataset", "database-one", "allowed_table");
        when(databaseRepository.existsById("database-one")).thenReturn(true);
        when(skillRepository.findByDatabaseIdOrderByCreateTimeAsc("database-one")).thenReturn(List.of());
        when(datasetRepository.findById("dataset-one")).thenReturn(Optional.of(dataset));
        when(skillRepository.existsById("skill-fixed01")).thenReturn(false);
        when(skillRepository.saveAndFlush(any(EvaluationSkill.class))).thenAnswer(call -> call.getArgument(0));

        Map<String, Object> body = Map.of(
                "id", "skill-fixed01",
                "name", "Ordered check",
                "description", "Execute in order",
                "databaseId", "database-one",
                "steps", List.of(Map.of(
                        "datasetId", "dataset-one",
                        "datasetName", "Stale client name",
                        "instruction", "Use the previous result",
                        "dependsOnPrevious", true,
                        "onDependencyFailure", "stop",
                        "requireNonEmpty", true,
                        "onEmpty", "skip"
                ))
        );

        Map<String, Object> response = controller.create(body).getBody();
        assertTrue(Boolean.TRUE.equals(response.get("success")));
        @SuppressWarnings("unchecked")
        Map<String, Object> skill = (Map<String, Object>) response.get("skill");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> steps = (List<Map<String, Object>>) skill.get("steps");
        assertEquals("skill-fixed01", skill.get("id"));
        assertEquals("Server dataset", steps.get(0).get("datasetName"));
        assertEquals("stop", steps.get(0).get("onDependencyFailure"));
        assertEquals("skip", steps.get(0).get("onEmpty"));
        assertTrue(Boolean.TRUE.equals(skill.get("valid")));
    }

    @Test
    void createRejectsCaseInsensitiveDuplicateNameWithinDatabase() {
        EvaluationSkill existing = new EvaluationSkill();
        existing.setId("skill-existing");
        existing.setName("Same Name");
        existing.setDatabaseId("database-one");
        existing.setStepsJson("[]");
        when(databaseRepository.existsById("database-one")).thenReturn(true);
        when(skillRepository.findByDatabaseIdOrderByCreateTimeAsc("database-one"))
                .thenReturn(List.of(existing));

        Map<String, Object> response = controller.create(Map.of(
                "name", " same name ",
                "databaseId", "database-one",
                "steps", List.of(Map.of("datasetId", "dataset-one", "instruction", "Query"))
        )).getBody();

        assertFalse(Boolean.TRUE.equals(response.get("success")));
        assertEquals("当前数据源下已存在同名 Skill", response.get("message"));
    }

    @Test
    void corruptedStepsAreExplicitlyMarkedInvalidInsteadOfSilentlyExecutingNormally() {
        EvaluationSkill corrupted = new EvaluationSkill();
        corrupted.setId("skill-corrupt");
        corrupted.setName("Corrupt");
        corrupted.setDatabaseId("database-one");
        corrupted.setStepsJson("{not-json");
        when(skillRepository.findById("skill-corrupt")).thenReturn(Optional.of(corrupted));

        Map<String, Object> response = controller.get("skill-corrupt").getBody();
        @SuppressWarnings("unchecked")
        Map<String, Object> skill = (Map<String, Object>) response.get("skill");
        assertFalse(Boolean.TRUE.equals(skill.get("valid")));
        assertTrue(String.valueOf(skill.get("validationMessage")).contains("损坏"));
    }

    @Test
    void persistenceSchemaFailureIsNotMisreportedAsDuplicateName() {
        Dataset dataset = dataset("dataset-one", "Server dataset", "database-one", "allowed_table");
        when(databaseRepository.existsById("database-one")).thenReturn(true);
        when(skillRepository.findByDatabaseIdOrderByCreateTimeAsc("database-one")).thenReturn(List.of());
        when(datasetRepository.findById("dataset-one")).thenReturn(Optional.of(dataset));
        when(skillRepository.saveAndFlush(any(EvaluationSkill.class))).thenThrow(
                new DataIntegrityViolationException(
                        "could not execute statement",
                        new RuntimeException("Data too long for column 'steps_json'"))
        );

        Map<String, Object> response = controller.create(Map.of(
                "name", "Schema failure",
                "databaseId", "database-one",
                "steps", List.of(Map.of("datasetId", "dataset-one", "instruction", "Query"))
        )).getBody();

        assertFalse(Boolean.TRUE.equals(response.get("success")));
        assertTrue(String.valueOf(response.get("message")).contains("表结构或约束异常"));
        assertFalse(String.valueOf(response.get("message")).contains("同名"));
    }

    private static Dataset dataset(String id, String name, String databaseId, String tableName) {
        Dataset dataset = new Dataset();
        dataset.setId(id);
        dataset.setName(name);
        dataset.setDatabaseId(databaseId);
        dataset.setTableName(tableName);
        return dataset;
    }
}
