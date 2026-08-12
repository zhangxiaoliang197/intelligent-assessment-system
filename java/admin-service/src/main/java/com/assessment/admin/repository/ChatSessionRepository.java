package com.assessment.admin.repository;

import com.assessment.admin.model.ChatSession;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

/**
 * 聊天会话 Repository。
 */
public interface ChatSessionRepository extends JpaRepository<ChatSession, String> {

    List<ChatSession> findByUserIdAndTypeOrderByLastActiveAtDesc(String userId, String type);

    List<ChatSession> findByUserIdOrderByLastActiveAtDesc(String userId);
}
