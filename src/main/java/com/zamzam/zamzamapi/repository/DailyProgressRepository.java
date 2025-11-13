package com.zamzam.zamzamapi.repository;

import com.zamzam.zamzamapi.entity.DailyProgress;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;
import java.time.LocalDateTime;
import java.util.Collection;
import java.util.UUID;

public interface DailyProgressRepository extends JpaRepository<DailyProgress, UUID> {

    List<DailyProgress> findByHalaqaId(UUID halaqaId);

    List<DailyProgress> findByStudentId(UUID studentId);
}

