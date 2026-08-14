package com.assessment.admin.repository;

import com.assessment.admin.model.ChatContext;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.transaction.annotation.Transactional;

import java.util.Optional;

/**
 * LLM 上下文 Repository。
 */
public interface ChatContextRepository extends JpaRepository<ChatContext, ChatContext.ChatContextId> {

    Optional<ChatContext> findBySessionIdAndContextType(String sessionId, String contextType);

    @Modifying
    @Transactional
    @Query("DELETE FROM ChatContext c WHERE c.sessionId = :sessionId")
    void deleteBySessionId(String sessionId);
}
