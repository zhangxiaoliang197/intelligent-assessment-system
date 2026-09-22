package com.assessment.admin.service;

import com.assessment.admin.model.AnnotationDraft;
import com.assessment.admin.model.Dataset;
import com.assessment.admin.model.FieldAnnotation;
import com.assessment.admin.model.LlmConfig;
import com.assessment.admin.repository.AnnotationDraftRepository;
import com.assessment.admin.repository.DatasetRepository;
import com.assessment.admin.repository.FieldAnnotationRepository;
import com.assessment.admin.service.AnnotationValidator.FieldSemantic;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;

/**
 * 语义注解草稿服务：LLM 生成 → 三层校验 → 人工审核 → 通过后才写入正式注解。
 *
 * 硬约束（详见 .trae/documents/admin-注解AI草稿与数据集分层显示方案.md §3.1）：
 * 1. 草稿与正式注解物理隔离，未通过审核前运行期完全不可见；
 * 2. 生成即校验：格式（semantic-schema）+ 结构（AnnotationValidator R1–R7）+ 值域（必须来自真实采样值）；
 * 3. 值域编造 → 记入 issues（硬错误），禁止批量通过，只能人工改写或驳回；
 * 4. approve 是唯一生效路径，且走与手工保存同口径的校验并触发 ipage 缓存失效；
 * 5. 全程记录 model / prompt 指纹 / token 用量 / 审核人与意见。
 */
@Service
public class AnnotationDraftService {

    private static final Logger logger = LoggerFactory.getLogger(AnnotationDraftService.class);

    private static final String SCOPE_FIELD = "field";
    private static final String SCOPE_DATASET = "dataset";
    private static final String STATUS_DRAFT = "draft";
    private static final String STATUS_APPROVED = "approved";
    private static final String STATUS_REJECTED = "rejected";
    private static final String STATUS_SUPERSEDED = "superseded";

    /** 与 semantic-schema.json 对齐的角色取值（写进提示词，避免模型自造角色） */
    private static final String ROLE_HINT =
            "id/name/time/lng/lat/radius/seq/measure/dimension/status/altitude/speed/heading";
    private static final String SYMBOL_HINT =
            "fighter/awacs/recon/bomber/base/sam/radar/coastal/flag/depot/fuel/anchor/runway/tower/"
                    + "boom/cross/magnifier/ring/dot";
    private static final String STATUS_KEY_HINT = "destroyed/miss/critical/heavy/light";

    private static final Pattern SAFE_IDENT =
            Pattern.compile("^[A-Za-z_\\u4e00-\\u9fa5][A-Za-z0-9_$\\u4e00-\\u9fa5]*$");

    private static final String SYSTEM_PROMPT = """
            你是数据资产语义标注助手。任务：根据一张物理表的字段信息，为"有明确语义"的字段产出结构化注解 JSON，
            并在线索充分时给出数据集级语义。只输出 JSON 对象，不要任何解释文字、不要 markdown 代码块。

            字段级可用键（与系统 schema 严格一致）：
            - role（字段角色）：%s
            - symbol（象形符号，可选）：%s
            - unit（单位，可选，如 km / km/h / m）
            - values（原始值 → 规范值映射，可选）："键"必须是真实取值样例中的原始文本；
              阵营类字段（取值形如 红方/蓝方/我方/敌方）的"规范值"只能用 blue（我方/红方）与 red（敌方/蓝方），
              不要自造 friendly / enemy 等其它词；status 类规范值见下方规则 2
            - synonyms（别名 → 规范值映射，可选）

            硬性规则：
            1. 只输出你确有把握的列；没有线索的列不要出现在结果里（宁缺勿滥）。
            2. role=status 时，values 的规范值只能是 %s。
            3. values/synonyms 的"键"必须是给定的真实取值样例里出现过的原始文本，严禁编造；
               role=dimension 的列若样例里看不出"取值→语义"的对应关系，就不要给 values。
            4. 不要输出 businessMeaning 之类自然语言说明（那部分由人工维护）。
            5. 数据集级语义只在线索充分时给出（例如成对经纬度列、或"实体编号+序号+时间"的航迹表）；
               无线索就输出空对象。
            6. 每个字段可附 "reason"（一句话中文理由，便于人工审核，最长 60 字）。

            输出结构：
            {
              "columns": [
                {"columnName": "home_lng", "role": "lng", "unit": "", "symbol": "",
                 "values": {}, "synonyms": {}, "reason": "列名与样例均为经纬度"}
              ],
              "datasetSemantic": {
                "entityKind": "air|ground_facility|base|other",
                "symbolDefault": "", "trackGroupKey": ["..."], "eventTimeColumn": "",
                "geometry": {"lngColumn": "...", "latColumn": "...", "radiusColumn": "..."}
              }
            }
            """.formatted(ROLE_HINT, SYMBOL_HINT, STATUS_KEY_HINT);

    private final LlmChatClient llmChatClient;
    private final DatasetRepository datasetRepo;
    private final FieldAnnotationRepository fieldAnnotationRepo;
    private final AnnotationDraftRepository draftRepo;
    private final SemanticSchemaValidator schemaValidator;
    private final AnnotationValidator annotationValidator;
    private final SqlExecutionService sqlExecutionService;
    private final IpPageCacheInvalidator cacheInvalidator;
    private final ObjectMapper mapper = new ObjectMapper();

    @Value("${annotation.draft.enabled:false}")
    private boolean enabled = false;
    @Value("${annotation.draft.max-columns:40}")
    private int maxColumns = 40;
    @Value("${annotation.draft.sample-columns:20}")
    private int sampleColumns = 20;
    @Value("${annotation.draft.sample-values:30}")
    private int sampleValues = 30;
    @Value("${annotation.draft.fewshot-datasets:3}")
    private int fewShotDatasets = 3;
    @Value("${annotation.draft.max-batches:3}")
    private int maxBatches = 3;

    public AnnotationDraftService(LlmChatClient llmChatClient,
                                  DatasetRepository datasetRepo,
                                  FieldAnnotationRepository fieldAnnotationRepo,
                                  AnnotationDraftRepository draftRepo,
                                  SemanticSchemaValidator schemaValidator,
                                  AnnotationValidator annotationValidator,
                                  SqlExecutionService sqlExecutionService,
                                  IpPageCacheInvalidator cacheInvalidator) {
        this.llmChatClient = llmChatClient;
        this.datasetRepo = datasetRepo;
        this.fieldAnnotationRepo = fieldAnnotationRepo;
        this.draftRepo = draftRepo;
        this.schemaValidator = schemaValidator;
        this.annotationValidator = annotationValidator;
        this.sqlExecutionService = sqlExecutionService;
        this.cacheInvalidator = cacheInvalidator;
    }

    public boolean isEnabled() {
        return enabled;
    }

    // ──────────────────────────────────────────────────────────────────
    // 生成
    // ──────────────────────────────────────────────────────────────────

    /**
     * 为指定数据集生成一批注解草稿。
     *
     * @param datasetId 数据集 ID
     * @param actor     操作人（写入 created_by）
     * @return {batchId, total, items, summary, notes}
     */
    public Map<String, Object> generate(String datasetId, String actor) {
        requireEnabled();
        Dataset ds = datasetRepo.findById(datasetId)
                .orElseThrow(() -> new IllegalStateException("数据集不存在"));
        LlmConfig config = llmChatClient.activeConfig()
                .orElseThrow(() -> new IllegalStateException(
                        "未找到可用的大模型配置，请先在「大模型配置」中设置并启用"));
        if (!schemaValidator.isAvailable()) {
            throw new IllegalStateException("语义格式规范不可用（" + schemaValidator.getUnavailableReason()
                    + "），已拒绝生成以免产出无法校验的草稿");
        }

        List<FieldAnnotation> existing = fieldAnnotationRepo.findByDatasetId(datasetId);
        List<String> columns = resolveColumns(ds, existing);
        if (columns.isEmpty()) {
            throw new IllegalStateException("该数据集没有可用字段信息，请先在「表结构」中读取并保存字段");
        }

        List<String> notes = new ArrayList<>();
        Map<String, List<String>> sampled = sampleValues(ds, columns, notes);
        String fewShot = buildFewShot(ds, datasetId);
        String batchId = "ad_" + UUID.randomUUID().toString().substring(0, 8);
        String promptHash = sha256(SYSTEM_PROMPT);

        // 超出单次列数上限时按批切分，最多 maxBatches 批（避免一次生成把 token 打满）
        List<List<String>> chunks = chunk(columns, Math.max(5, maxColumns));
        if (chunks.size() > maxBatches) {
            notes.add("字段数较多，本次只生成前 " + (maxBatches * Math.max(5, maxColumns))
                    + " 个字段的草稿，其余请再次生成");
            chunks = chunks.subList(0, maxBatches);
        }

        List<AnnotationDraft> saved = new ArrayList<>();
        for (List<String> chunk : chunks) {
            String userPrompt = buildUserPrompt(ds, chunk, existing, sampled, fewShot);
            String content = llmChatClient.chat(config, SYSTEM_PROMPT, userPrompt, true);
            JsonNode root = parseJson(content);
            if (root == null) {
                notes.add("模型返回内容无法解析为 JSON，该批已跳过");
                continue;
            }
            saved.addAll(persistFieldDrafts(ds, root.path("columns"), existing, columns, sampled,
                    batchId, promptHash, config.getModel(), actor));
            AnnotationDraft datasetDraft = persistDatasetDraft(ds, root.path("datasetSemantic"),
                    existing, columns, batchId, promptHash, config.getModel(), actor);
            if (datasetDraft != null) {
                saved.add(datasetDraft);
            }
        }

        logger.info("注解草稿生成完成 dataset={} batch={} 条数={}", datasetId, batchId, saved.size());
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("batchId", batchId);
        result.put("total", saved.size());
        result.put("items", saved);
        result.put("notes", notes);
        result.put("sampledColumns", sampled.keySet());
        return result;
    }

    // ──────────────────────────────────────────────────────────────────
    // 查询 / 修改 / 审核
    // ──────────────────────────────────────────────────────────────────

    public List<AnnotationDraft> list(String datasetId, String status) {
        String want = status == null ? "" : status.trim();
        return want.isEmpty()
                ? draftRepo.findByDatasetIdOrderByCreateTimeDesc(datasetId)
                : draftRepo.findByDatasetIdAndStatusOrderByCreateTimeDesc(datasetId, want);
    }

    public Map<String, Object> summary(String datasetId) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("draft", draftRepo.countByDatasetIdAndStatus(datasetId, STATUS_DRAFT));
        map.put("approved", draftRepo.countByDatasetIdAndStatus(datasetId, STATUS_APPROVED));
        map.put("rejected", draftRepo.countByDatasetIdAndStatus(datasetId, STATUS_REJECTED));
        map.put("enabled", enabled);
        return map;
    }

    /** 人工修改草稿内容：改完重新跑三层校验（格式/结构/值域）。 */
    public AnnotationDraft updateDraft(String draftId, String draftJson, String actor) {
        AnnotationDraft draft = draftRepo.findById(draftId)
                .orElseThrow(() -> new IllegalStateException("草稿不存在"));
        if (!STATUS_DRAFT.equals(draft.getStatus())) {
            throw new IllegalStateException("该草稿当前状态为 " + draft.getStatus() + "，不可修改");
        }
        Dataset ds = datasetRepo.findById(draft.getDatasetId())
                .orElseThrow(() -> new IllegalStateException("数据集不存在"));
        draft.setDraftJson(draftJson);
        draft.setSource("manual");
        draft.setCreatedBy(actor);
        revalidate(draft, ds);
        return draftRepo.save(draft);
    }

    /** 通过单条草稿：走与手工保存同口径的校验后写入正式注解。 */
    public Map<String, Object> approve(String draftId, String actor) {
        return approve(draftId, actor, false, "");
    }

    /**
     * 通过单条草稿（支持带理由的"强制通过"）。
     *
     * 常规路径下，只要草稿存在硬错误（如真实数据中不存在的值域）就拒绝生效；
     * {@code force=true} 时允许管理员在**已确认值合法**（例如该取值确实存在但未进入采样）
     * 的前提下带理由强制通过——单条、需填理由、全程留痕，整批通过仍不接受带硬错误的条目。
     *
     * @param draftId 草稿 ID
     * @param actor   审核人
     * @param force   是否强制通过（忽略硬错误）
     * @param remark  强制理由（force=true 时必填）
     * @return 生效结果
     */
    public Map<String, Object> approve(String draftId, String actor, boolean force, String remark) {
        AnnotationDraft draft = draftRepo.findById(draftId)
                .orElseThrow(() -> new IllegalStateException("草稿不存在"));
        if (!STATUS_DRAFT.equals(draft.getStatus())) {
            throw new IllegalStateException("该草稿当前状态为 " + draft.getStatus() + "，无需再次审核");
        }
        List<String> issues = readList(draft.getIssuesJson());
        String forceRemark = "";
        if (!issues.isEmpty()) {
            if (!force) {
                throw new IllegalStateException("该草稿存在硬错误，请先修正或驳回；"
                        + "若确认取值合法（例如未被采样覆盖），可填写理由后强制通过："
                        + String.join("；", issues));
            }
            if (remark == null || remark.isBlank()) {
                throw new IllegalStateException("强制通过必须填写理由（说明为何判定该取值合法）");
            }
            forceRemark = "【强制通过】" + remark.trim();
        }
        Dataset ds = datasetRepo.findById(draft.getDatasetId())
                .orElseThrow(() -> new IllegalStateException("数据集不存在"));

        String applyMessage = SCOPE_DATASET.equals(draft.getScope())
                ? applyDatasetDraft(ds, draft)
                : applyFieldDraft(ds, draft);

        draft.setStatus(STATUS_APPROVED);
        draft.setReviewedBy(actor);
        draft.setReviewedAt(LocalDateTime.now());
        if (!forceRemark.isEmpty()) {
            // 强制通过必须留痕：理由与当时的硬错误一并记录，便于事后追溯
            draft.setReviewRemark(forceRemark + "（原硬错误：" + String.join("；", issues) + "）");
        }
        draftRepo.save(draft);
        logger.info("注解草稿已通过 draft={} dataset={} 范围={} 强制={}",
                draftId, ds.getId(), draft.getScope(), !forceRemark.isEmpty());
        return Map.of("success", true,
                "message", "草稿已生效" + applyMessage + (forceRemark.isEmpty() ? "" : "（强制通过）"));
    }

    public Map<String, Object> reject(String draftId, String remark, String actor) {
        AnnotationDraft draft = draftRepo.findById(draftId)
                .orElseThrow(() -> new IllegalStateException("草稿不存在"));
        if (!STATUS_DRAFT.equals(draft.getStatus())) {
            throw new IllegalStateException("该草稿当前状态为 " + draft.getStatus() + "，无需再次审核");
        }
        draft.setStatus(STATUS_REJECTED);
        draft.setReviewedBy(actor);
        draft.setReviewedAt(LocalDateTime.now());
        draft.setReviewRemark(remark == null ? "" : remark);
        draftRepo.save(draft);
        return Map.of("success", true, "message", "草稿已驳回");
    }

    /**
     * 整批通过：跳过带硬错误的条目（值域编造等），返回实际通过数与跳过明细。
     * 不允许"连硬错误一起通过"——这是值域防编造的最后一道闸。
     */
    public Map<String, Object> approveBatch(String batchId, String actor) {
        List<AnnotationDraft> drafts = draftRepo.findByBatchId(batchId);
        int approved = 0;
        List<String> skipped = new ArrayList<>();
        for (AnnotationDraft draft : drafts) {
            if (!STATUS_DRAFT.equals(draft.getStatus())) {
                continue;
            }
            if (!readList(draft.getIssuesJson()).isEmpty()) {
                skipped.add(describe(draft) + "：" + String.join("；", readList(draft.getIssuesJson())));
                continue;
            }
            try {
                approve(draft.getId(), actor);
                approved += 1;
            } catch (Exception e) {
                skipped.add(describe(draft) + "：" + e.getMessage());
            }
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("success", true);
        result.put("approved", approved);
        result.put("skipped", skipped);
        result.put("message", "已通过 " + approved + " 条"
                + (skipped.isEmpty() ? "" : "，跳过 " + skipped.size() + " 条（存在硬错误或校验未通过）"));
        return result;
    }

    public Map<String, Object> rejectBatch(String batchId, String remark, String actor) {
        List<AnnotationDraft> drafts = draftRepo.findByBatchId(batchId);
        int rejected = 0;
        for (AnnotationDraft draft : drafts) {
            if (STATUS_DRAFT.equals(draft.getStatus())) {
                draft.setStatus(STATUS_REJECTED);
                draft.setReviewedBy(actor);
                draft.setReviewedAt(LocalDateTime.now());
                draft.setReviewRemark(remark == null ? "" : remark);
                draftRepo.save(draft);
                rejected += 1;
            }
        }
        return Map.of("success", true, "rejected", rejected, "message", "已驳回 " + rejected + " 条草稿");
    }

    /** 按驳回意见重生成单条草稿（旧的置 superseded）。 */
    public AnnotationDraft regenerate(String draftId, String actor) {
        requireEnabled();
        AnnotationDraft old = draftRepo.findById(draftId)
                .orElseThrow(() -> new IllegalStateException("草稿不存在"));
        Dataset ds = datasetRepo.findById(old.getDatasetId())
                .orElseThrow(() -> new IllegalStateException("数据集不存在"));
        LlmConfig config = llmChatClient.activeConfig()
                .orElseThrow(() -> new IllegalStateException("未找到可用的大模型配置"));

        List<FieldAnnotation> existing = fieldAnnotationRepo.findByDatasetId(old.getDatasetId());
        List<String> columns = resolveColumns(ds, existing);
        List<String> notes = new ArrayList<>();
        Map<String, List<String>> sampled = sampleValues(ds, columns, notes);

        String feedback = "上一版被驳回，原因：" + Objects.toString(old.getReviewRemark(), "未填写")
                + "。请据此修正后重新给出该" + (SCOPE_DATASET.equals(old.getScope()) ? "数据集级语义" : "字段的语义");
        if (SCOPE_FIELD.equals(old.getScope())) {
            String userPrompt = buildUserPrompt(ds, List.of(old.getColumnName()), existing, sampled, "")
                    + "\n\n【额外要求】" + feedback;
            String content = llmChatClient.chat(config, SYSTEM_PROMPT, userPrompt, true);
            JsonNode root = parseJson(content);
            JsonNode columnsNode = root == null ? null : root.path("columns");
            List<AnnotationDraft> created = persistFieldDrafts(ds, columnsNode, existing, columns, sampled,
                    old.getBatchId(), sha256(SYSTEM_PROMPT), config.getModel(), actor);
            if (created.isEmpty()) {
                throw new IllegalStateException("重生成未产出有效草稿，请稍后重试");
            }
            old.setStatus(STATUS_SUPERSEDED);
            draftRepo.save(old);
            return created.get(0);
        }
        String userPrompt = buildUserPrompt(ds, columns, existing, sampled, "")
                + "\n\n【额外要求】" + feedback + "（只需输出 datasetSemantic）";
        String content = llmChatClient.chat(config, SYSTEM_PROMPT, userPrompt, true);
        AnnotationDraft created = persistDatasetDraft(ds, parseJson(content) == null
                        ? null : parseJson(content).path("datasetSemantic"),
                existing, columns, old.getBatchId(), sha256(SYSTEM_PROMPT), config.getModel(), actor);
        if (created == null) {
            throw new IllegalStateException("重生成未产出有效草稿，请稍后重试");
        }
        old.setStatus(STATUS_SUPERSEDED);
        draftRepo.save(old);
        return created;
    }

    /** 丢弃整批草稿。 */
    public int discardBatch(String batchId) {
        List<AnnotationDraft> drafts = draftRepo.findByBatchId(batchId);
        draftRepo.deleteAll(drafts);
        return drafts.size();
    }

    // ──────────────────────────────────────────────────────────────────
    // 生效（与手工保存同口径）
    // ──────────────────────────────────────────────────────────────────

    private String applyFieldDraft(Dataset ds, AnnotationDraft draft) {
        List<Map<String, Object>> tableColumns = structureOf(ds);
        List<FieldSemantic> merged = mergedFields(ds.getId(), draft.getColumnName(), draft.getDraftJson());
        List<String> errors = schemaValidator.validateField(draft.getDraftJson());
        if (!errors.isEmpty()) {
            throw new IllegalStateException("格式校验未通过：" + String.join("；", errors));
        }
        AnnotationValidator.Result check = annotationValidator.validate(
                ds.getTableName(), tableColumns, ds.getSemanticJson(), merged, null);
        if (check.isRejected()) {
            throw new IllegalStateException("结构校验未通过：" + String.join("；", check.getErrors()));
        }
        FieldAnnotation target = fieldAnnotationRepo.findByDatasetId(ds.getId()).stream()
                .filter(item -> Objects.equals(item.getColumnName(), draft.getColumnName()))
                .findFirst()
                .orElseGet(() -> {
                    FieldAnnotation created = new FieldAnnotation();
                    created.setId("fa_" + UUID.randomUUID().toString().substring(0, 8));
                    created.setDatasetId(ds.getId());
                    created.setTableName(ds.getTableName());
                    created.setColumnName(draft.getColumnName());
                    return created;
                });
        target.setSemanticJson(draft.getDraftJson());
        fieldAnnotationRepo.save(target);
        recordFingerprint(ds, check);
        return "（字段 " + draft.getColumnName() + "）";
    }

    private String applyDatasetDraft(Dataset ds, AnnotationDraft draft) {
        List<String> errors = schemaValidator.validateDataset(draft.getDraftJson());
        if (!errors.isEmpty()) {
            throw new IllegalStateException("格式校验未通过：" + String.join("；", errors));
        }
        List<Map<String, Object>> tableColumns = structureOf(ds);
        AnnotationValidator.Result check = annotationValidator.validate(
                ds.getTableName(), tableColumns, draft.getDraftJson(),
                toFieldSemantics(fieldAnnotationRepo.findByDatasetId(ds.getId())), null);
        if (check.isRejected()) {
            throw new IllegalStateException("结构校验未通过：" + String.join("；", check.getErrors()));
        }
        ds.setSemanticJson(draft.getDraftJson());
        recordFingerprint(ds, check);
        return "（数据集级语义）";
    }

    private void recordFingerprint(Dataset ds, AnnotationValidator.Result check) {
        if (check.isStructureChecked()) {
            ds.setAnnotationValidatedAt(LocalDateTime.now());
            ds.setAnnotationStructureFingerprint(check.getStructureFingerprint());
        }
        datasetRepo.save(ds);
        String invalidateError = cacheInvalidator.invalidate(
                ds.getDatabaseId(), List.of(Objects.toString(ds.getTableName(), "")));
        if (invalidateError != null) {
            logger.warn("草稿生效后缓存失效失败 dataset={}: {}", ds.getId(), invalidateError);
        }
    }

    // ──────────────────────────────────────────────────────────────────
    // 草稿落库与三层校验
    // ──────────────────────────────────────────────────────────────────

    private List<AnnotationDraft> persistFieldDrafts(Dataset ds, JsonNode columnsNode,
                                                     List<FieldAnnotation> existing,
                                                     List<String> allColumns,
                                                     Map<String, List<String>> sampled,
                                                     String batchId, String promptHash,
                                                     String model, String actor) {
        List<AnnotationDraft> created = new ArrayList<>();
        if (columnsNode == null || !columnsNode.isArray()) {
            return created;
        }
        Set<String> known = new LinkedHashSet<>(allColumns);
        for (JsonNode item : columnsNode) {
            String columnName = item.path("columnName").asText("").trim();
            if (columnName.isEmpty() || !known.contains(columnName)) {
                logger.warn("草稿忽略了不存在的列: {}", columnName);
                continue;
            }
            Map<String, Object> semantic = new LinkedHashMap<>();
            for (String key : List.of("role", "symbol", "unit", "values", "synonyms")) {
                JsonNode value = item.get(key);
                if (value != null && !value.isNull()
                        && !(value.isObject() && value.size() == 0)
                        && !(value.isTextual() && value.asText().isBlank())) {
                    semantic.put(key, mapper.convertValue(value, Object.class));
                }
            }
            if (semantic.isEmpty()) {
                continue;
            }
            String draftJson = writeJson(semantic);
            supersede(ds.getId(), columnName);
            AnnotationDraft draft = new AnnotationDraft();
            draft.setId("adr_" + UUID.randomUUID().toString().substring(0, 8));
            draft.setDatasetId(ds.getId());
            draft.setTableName(ds.getTableName());
            draft.setBatchId(batchId);
            draft.setScope(SCOPE_FIELD);
            draft.setColumnName(columnName);
            draft.setDraftJson(draftJson);
            draft.setStatus(STATUS_DRAFT);
            draft.setSource("llm");
            draft.setModel(model);
            draft.setPromptHash(promptHash);
            draft.setSampledJson(writeJson(sampled.getOrDefault(columnName, List.of())));
            draft.setCreatedBy(actor);
            revalidate(draft, ds);
            created.add(draftRepo.save(draft));
        }
        return created;
    }

    private AnnotationDraft persistDatasetDraft(Dataset ds, JsonNode node, List<FieldAnnotation> existing,
                                               List<String> allColumns, String batchId, String promptHash,
                                               String model, String actor) {
        if (node == null || !node.isObject() || node.size() == 0) {
            return null;
        }
        Map<String, Object> semantic = mapper.convertValue(node, Map.class);
        // 递归剔除空值（空串/空数组/空对象）：模型常用 [] 或 "" 表示"没有这一项"，
        // 若原样保留会被 schema 的 minItems/minLength 判成硬错误，反而掩盖真正的建议。
        Object pruned = pruneEmpty(semantic);
        if (!(pruned instanceof Map<?, ?> prunedMap) || prunedMap.isEmpty()) {
            return null;
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> cleaned = (Map<String, Object>) prunedMap;
        supersede(ds.getId(), null);
        AnnotationDraft draft = new AnnotationDraft();
        draft.setId("adr_" + UUID.randomUUID().toString().substring(0, 8));
        draft.setDatasetId(ds.getId());
        draft.setTableName(ds.getTableName());
        draft.setBatchId(batchId);
        draft.setScope(SCOPE_DATASET);
        draft.setDraftJson(writeJson(cleaned));
        draft.setStatus(STATUS_DRAFT);
        draft.setSource("llm");
        draft.setModel(model);
        draft.setPromptHash(promptHash);
        draft.setCreatedBy(actor);
        revalidate(draft, ds);
        return draftRepo.save(draft);
    }

    /**
     * 递归剔除空值：空串、空数组、空对象一律视为"模型没有给出这一项"。
     *
     * 模型习惯用 {@code "trackGroupKey": []} 或 {@code "radiusColumn": ""} 表示"无"，
     * 若原样保留会被 semantic-schema 的 minItems / minLength 判成硬错误。
     *
     * @param value 任意 JSON 值
     * @return 去掉空值后的值；整体为空时返回 {@code null}
     */
    static Object pruneEmpty(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof String text) {
            return text.isBlank() ? null : text;
        }
        if (value instanceof List<?> list) {
            List<Object> kept = new ArrayList<>();
            for (Object item : list) {
                Object pruned = pruneEmpty(item);
                if (pruned != null) {
                    kept.add(pruned);
                }
            }
            return kept.isEmpty() ? null : kept;
        }
        if (value instanceof Map<?, ?> map) {
            Map<String, Object> kept = new LinkedHashMap<>();
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                Object pruned = pruneEmpty(entry.getValue());
                if (pruned != null) {
                    kept.put(String.valueOf(entry.getKey()), pruned);
                }
            }
            return kept.isEmpty() ? null : kept;
        }
        return value;
    }

    /** 同列/数据集级历史草稿置为 superseded，避免审核队列里堆积过期版本。 */
    private void supersede(String datasetId, String columnName) {
        List<AnnotationDraft> actives = draftRepo.findByDatasetIdAndStatus(datasetId, STATUS_DRAFT);
        for (AnnotationDraft item : actives) {
            boolean sameColumn = Objects.equals(item.getColumnName(), columnName);
            boolean sameScope = columnName == null
                    ? SCOPE_DATASET.equals(item.getScope())
                    : SCOPE_FIELD.equals(item.getScope());
            if (sameColumn && sameScope) {
                item.setStatus(STATUS_SUPERSEDED);
                draftRepo.save(item);
            }
        }
    }

    /** 三层校验：格式 → 结构 → 值域（值域编造进 issues，禁止批量通过）。 */
    private void revalidate(AnnotationDraft draft, Dataset ds) {
        List<String> issues = new ArrayList<>();
        List<String> warnings = new ArrayList<>();

        if (SCOPE_DATASET.equals(draft.getScope())) {
            issues.addAll(schemaValidator.validateDataset(draft.getDraftJson()));
            List<Map<String, Object>> tableColumns = structureOf(ds);
            AnnotationValidator.Result check = annotationValidator.validate(
                    ds.getTableName(), tableColumns, draft.getDraftJson(),
                    toFieldSemantics(fieldAnnotationRepo.findByDatasetId(ds.getId())), null);
            issues.addAll(check.getErrors());
            warnings.addAll(check.getWarnings());
        } else {
            issues.addAll(schemaValidator.validateField(draft.getDraftJson()));
            DomainCheck domain = validateValueDomain(draft.getColumnName(), draft.getDraftJson(),
                    readList(draft.getSampledJson()));
            issues.addAll(domain.issues());
            warnings.addAll(domain.warnings());
            List<Map<String, Object>> tableColumns = structureOf(ds);
            List<FieldSemantic> merged = mergedFields(ds.getId(), draft.getColumnName(), draft.getDraftJson());
            AnnotationValidator.Result check = annotationValidator.validate(
                    ds.getTableName(), tableColumns, ds.getSemanticJson(), merged, null);
            issues.addAll(check.getErrors());
            warnings.addAll(check.getWarnings());
        }
        draft.setIssuesJson(writeJson(issues));
        draft.setWarningsJson(writeJson(warnings));
    }

    /**
     * 值域校验（决策 E4，已按"采样可能不完整"重新设计）。
     *
     * 判定强度取决于**采样是否可能被截断**：
     * - 值数 < 上限：样本即全集，声明外的值确实不存在 → {@code issues}（硬错误，禁批量通过）；
     * - 值数达到上限：可能只是没进 TOP-N 的合法值 → {@code warnings}（告警，允许人工判断后通过）。
     *
     * 比较时做归一化（trim + 忽略大小写），避免 CHAR 尾空格、大小写差异造成误判。
     * 包级可见以便单测直接覆盖这条规则（见 AnnotationDraftServiceTest）。
     */
    DomainCheck validateValueDomain(String columnName, String draftJson, List<String> sampled) {
        List<String> issues = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        if (sampled == null || sampled.isEmpty()) {
            return new DomainCheck(issues, warnings);
        }
        JsonNode node = parseJson(draftJson);
        if (node == null) {
            return new DomainCheck(issues, warnings);
        }
        Set<String> real = new LinkedHashSet<>();
        for (String value : sampled) {
            real.add(normalizeValue(value));
        }
        // 样本条数达到上限 ⇒ 采样 SQL 的 LIMIT 生效，表里可能还有更多取值
        boolean mayBeTruncated = sampled.size() >= Math.max(5, sampleValues);
        for (String key : List.of("values", "synonyms")) {
            JsonNode map = node.get(key);
            if (map == null || !map.isObject()) {
                continue;
            }
            List<String> outside = new ArrayList<>();
            map.fieldNames().forEachRemaining(name -> {
                if (!real.contains(normalizeValue(name))) {
                    outside.add(name);
                }
            });
            if (outside.isEmpty()) {
                continue;
            }
            if (mayBeTruncated) {
                warnings.add("字段 " + columnName + " 的 " + key + " 含本次采样未覆盖的值："
                        + String.join("、", outside) + "（该列取值较多，仅比对了出现频次最高的 "
                        + sampled.size() + " 个，请人工确认这些值是否真实存在）");
            } else {
                issues.add("字段 " + columnName + " 的 " + key + " 出现真实数据中不存在的值："
                        + String.join("、", outside) + "（疑似编造，请核对或删除该映射）");
            }
        }
        return new DomainCheck(issues, warnings);
    }

    /** 值域比对前的归一化：去首尾空白 + 忽略大小写（空值原样返回）。 */
    private static String normalizeValue(String value) {
        return value == null ? "" : value.trim().toLowerCase(Locale.ROOT);
    }

    /** 值域校验结果：硬错误（禁批量通过）与告警（可人工判断后通过）分开返回。 */
    record DomainCheck(List<String> issues, List<String> warnings) {
    }

    // ──────────────────────────────────────────────────────────────────
    // 提示词与上下文
    // ──────────────────────────────────────────────────────────────────

    private String buildUserPrompt(Dataset ds, List<String> columns, List<FieldAnnotation> existing,
                                   Map<String, List<String>> sampled, String fewShot) {
        StringBuilder sb = new StringBuilder();
        sb.append("数据表：").append(Objects.toString(ds.getTableName(), ""))
                .append("（数据集：").append(Objects.toString(ds.getName(), "")).append("）\n");
        if (fewShot != null && !fewShot.isBlank()) {
            sb.append("\n【同库已生效注解样例（供风格参考）】\n").append(fewShot).append('\n');
        }
        sb.append("\n【待标注字段】\n");
        for (String column : columns) {
            FieldAnnotation meta = existing.stream()
                    .filter(item -> Objects.equals(item.getColumnName(), column))
                    .findFirst().orElse(null);
            String comment = meta == null ? "" : Objects.toString(meta.getBusinessMeaning(),
                    Objects.toString(meta.getColumnComment(), ""));
            List<String> values = sampled.get(column);
            sb.append("- ").append(column)
                    .append(" | 类型=").append(meta == null ? "" : Objects.toString(meta.getColumnType(), ""))
                    .append(" | 注释=").append(comment);
            if (values != null && !values.isEmpty()) {
                sb.append(" | 真实取值样例=").append(String.join("、", values));
            }
            sb.append('\n');
        }
        sb.append("\n请输出 JSON（只包含确有把握的字段；示例值中的原始文本可用于 values 的键）。");
        return sb.toString();
    }

    /** 同数据源下已生效的结构化注解，最多 fewShotDatasets 个数据集 × 每表 3 列。 */
    private String buildFewShot(Dataset ds, String excludeDatasetId) {
        if (ds.getDatabaseId() == null || ds.getDatabaseId().isBlank()) {
            return "";
        }
        List<String> lines = new ArrayList<>();
        int used = 0;
        for (Dataset other : datasetRepo.findByDatabaseId(ds.getDatabaseId())) {
            if (used >= fewShotDatasets || Objects.equals(other.getId(), excludeDatasetId)) {
                continue;
            }
            int picked = 0;
            for (FieldAnnotation item : fieldAnnotationRepo.findByDatasetId(other.getId())) {
                String semantic = Objects.toString(item.getSemanticJson(), "").trim();
                if (semantic.isEmpty() || "{}".equals(semantic)) {
                    continue;
                }
                lines.add("- " + other.getTableName() + "." + item.getColumnName() + " → " + semantic);
                picked += 1;
                if (picked >= 3) {
                    break;
                }
            }
            if (picked > 0) {
                used += 1;
            }
        }
        return String.join("\n", lines);
    }

    /** 采样：只取非敏感、标识符合法、且能读到的列；失败列直接跳过（不阻断生成）。 */
    private Map<String, List<String>> sampleValues(Dataset ds, List<String> columns, List<String> notes) {
        Map<String, List<String>> sampled = new LinkedHashMap<>();
        Set<String> sensitive = new LinkedHashSet<>();
        for (String item : Objects.toString(ds.getSensitiveColumns(), "").split(",")) {
            if (!item.isBlank()) {
                sensitive.add(item.trim().toLowerCase(Locale.ROOT));
            }
        }
        int done = 0;
        for (String column : columns) {
            if (done >= sampleColumns) {
                notes.add("只对前 " + sampleColumns + " 个字段做了取值采样（其余列的值域未校验）");
                break;
            }
            if (!SAFE_IDENT.matcher(column).matches() || sensitive.contains(column.toLowerCase(Locale.ROOT))) {
                continue;
            }
            String table = Objects.toString(ds.getTableName(), "");
            if (!SAFE_IDENT.matcher(table).matches()) {
                break;
            }
            String sql = "SELECT " + column + " AS v, COUNT(*) AS c FROM " + table
                    + " GROUP BY " + column + " ORDER BY c DESC LIMIT " + Math.max(5, sampleValues);
            try {
                Map<String, Object> payload = sqlExecutionService.executeSql(ds.getId(), sql);
                if (payload == null || !Boolean.TRUE.equals(payload.get("success"))) {
                    continue;
                }
                List<String> values = new ArrayList<>();
                if (payload.get("rows") instanceof List<?> rows) {
                    for (Object row : rows) {
                        if (row instanceof Map<?, ?> map) {
                            Object value = map.get("v");
                            if (value != null && !value.toString().isBlank()) {
                                values.add(value.toString());
                            }
                        }
                    }
                }
                if (!values.isEmpty()) {
                    sampled.put(column, values);
                    done += 1;
                }
            } catch (Exception e) {
                logger.debug("采样跳过 {}: {}", column, e.getMessage());
            }
        }
        return sampled;
    }

    // ──────────────────────────────────────────────────────────────────
    // 结构 / 字段工具
    // ──────────────────────────────────────────────────────────────────

    /** 真实列清单：优先 live schema，退回已有字段注解行，再退回调用方传入的列。 */
    private List<String> resolveColumns(Dataset ds, List<FieldAnnotation> existing) {
        List<String> live = new ArrayList<>();
        if (ds.getDatabaseId() != null && !ds.getDatabaseId().isBlank()) {
            live = sqlExecutionService.listColumnsOnDatabase(ds.getDatabaseId(), ds.getTableName());
        }
        if (live != null && !live.isEmpty()) {
            return live;
        }
        List<String> fromAnnotations = new ArrayList<>();
        for (FieldAnnotation item : existing) {
            if (item.getColumnName() != null && !item.getColumnName().isBlank()) {
                fromAnnotations.add(item.getColumnName());
            }
        }
        return fromAnnotations;
    }

    /** AnnotationValidator 需要的表结构视图：只需列名（结构规则按列名校验）。 */
    private List<Map<String, Object>> structureOf(Dataset ds) {
        List<FieldAnnotation> existing = fieldAnnotationRepo.findByDatasetId(ds.getId());
        List<Map<String, Object>> columns = new ArrayList<>();
        for (String column : resolveColumns(ds, existing)) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("columnName", column);
            columns.add(item);
        }
        return columns;
    }

    /** 现有字段注解 + 本次草稿覆盖后的全量（用于结构校验，避免重复 role 等冲突漏判）。 */
    private List<FieldSemantic> mergedFields(String datasetId, String overrideColumn, String overrideJson) {
        List<FieldSemantic> merged = new ArrayList<>();
        boolean replaced = false;
        for (FieldAnnotation item : fieldAnnotationRepo.findByDatasetId(datasetId)) {
            if (overrideColumn != null && Objects.equals(item.getColumnName(), overrideColumn)) {
                merged.add(new FieldSemantic(item.getColumnName(), overrideJson));
                replaced = true;
            } else {
                merged.add(new FieldSemantic(item.getColumnName(), item.getSemanticJson()));
            }
        }
        if (overrideColumn != null && !replaced) {
            merged.add(new FieldSemantic(overrideColumn, overrideJson));
        }
        return merged;
    }

    private List<FieldSemantic> toFieldSemantics(List<FieldAnnotation> fields) {
        List<FieldSemantic> out = new ArrayList<>();
        for (FieldAnnotation item : fields) {
            out.add(new FieldSemantic(item.getColumnName(), item.getSemanticJson()));
        }
        return out;
    }

    // ──────────────────────────────────────────────────────────────────
    // 基础工具
    // ──────────────────────────────────────────────────────────────────

    private void requireEnabled() {
        if (!enabled) {
            throw new IllegalStateException(
                    "注解草稿生成已关闭（annotation.draft.enabled=false），请先在配置中开启");
        }
    }

    private JsonNode parseJson(String text) {
        if (text == null || text.isBlank()) {
            return null;
        }
        String cleaned = text.trim();
        // 容错：模型偶尔会包 markdown 代码块
        if (cleaned.startsWith("```")) {
            cleaned = cleaned.replaceAll("^```[a-zA-Z]*\\s*", "").replaceAll("```\\s*$", "");
        }
        try {
            return mapper.readTree(cleaned);
        } catch (Exception e) {
            logger.warn("模型输出不是合法 JSON: {}", e.getMessage());
            return null;
        }
    }

    private String writeJson(Object value) {
        try {
            return mapper.writeValueAsString(value);
        } catch (Exception e) {
            return "[]";
        }
    }

    @SuppressWarnings("unchecked")
    private List<String> readList(String json) {
        if (json == null || json.isBlank()) {
            return new ArrayList<>();
        }
        try {
            Object parsed = mapper.readValue(json, Object.class);
            if (parsed instanceof List<?> list) {
                List<String> out = new ArrayList<>();
                for (Object item : list) {
                    out.add(Objects.toString(item, ""));
                }
                return out;
            }
        } catch (Exception ignored) {
            // 非数组内容按单条处理
        }
        return new ArrayList<>(List.of(json));
    }

    private static List<List<String>> chunk(List<String> source, int size) {
        List<List<String>> chunks = new ArrayList<>();
        for (int i = 0; i < source.size(); i += size) {
            chunks.add(new ArrayList<>(source.subList(i, Math.min(source.size(), i + size))));
        }
        return chunks;
    }

    private static String describe(AnnotationDraft draft) {
        return SCOPE_DATASET.equals(draft.getScope())
                ? "数据集级语义" : "字段 " + Objects.toString(draft.getColumnName(), "");
    }

    private static String sha256(String text) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest(Objects.toString(text, "").getBytes(StandardCharsets.UTF_8));
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
