package com.zamzam.zamzamapi.repository;

import com.zamzam.zamzamapi.entity.Halaqa;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.UUID;

public interface HalaqaRepository extends JpaRepository<Halaqa, UUID> {
}