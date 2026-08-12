package com.assessment.admin.repository;

import com.assessment.admin.model.ChatMessage;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

/**
 * 聊天消息 Repository。
 */
public interface ChatMessageRepository extends JpaRepository<ChatMessage, String> {

    List<ChatMessage> findBySessionIdOrderBySequenceNumAsc(String sessionId);

    List<ChatMessage> findBySessionIdOrderBySequenceNumDesc(String sessionId);

    int countBySessionId(String sessionId);

    void deleteBySessionId(String sessionId);
}
