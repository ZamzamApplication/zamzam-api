package com.zamzam.zamzamapi.repository;

import com.zamzam.zamzamapi.entity.DailyProgress;
import com.zamzam.zamzamapi.entity.Organization;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

public interface DailyProgressRepository extends JpaRepository<DailyProgress, UUID> {

    List<DailyProgress> findByHalaqaId(UUID halaqaId);

    List<DailyProgress> findByStudentId(UUID studentId);
    List<DailyProgress> findByUpdatedAtAfter(LocalDateTime since);

    @Query("SELECT p FROM DailyProgress p JOIN p.halaqa h WHERE p.updatedAt > :since AND h.organization IN :orgs")
    List<DailyProgress> findByUpdatedAtAfterAndHalaqaOrganizationIn(LocalDateTime since, List<Organization> orgs);
}

