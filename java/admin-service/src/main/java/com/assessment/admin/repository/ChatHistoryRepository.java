package com.assessment.admin.repository;

import com.assessment.admin.model.ChatHistory;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

/**
 * 聊天历史索引 Repository。
 */
public interface ChatHistoryRepository extends JpaRepository<ChatHistory, String> {

    Optional<ChatHistory> findBySessionId(String sessionId);

    List<ChatHistory> findByUserIdAndTypeOrderByCreateTimeDesc(String userId, String type);

    List<ChatHistory> findByUserIdOrderByCreateTimeDesc(String userId);

    void deleteBySessionId(String sessionId);
}
