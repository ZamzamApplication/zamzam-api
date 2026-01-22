package com.zamzam.zamzamapi.repository;

import com.zamzam.zamzamapi.entity.Halaqa;
import com.zamzam.zamzamapi.entity.Organization;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface HalaqaRepository extends JpaRepository<Halaqa, UUID> {
    Optional<Halaqa> findByNameAndOrganizationId(String name, UUID organizationId);

    @Query("SELECT DISTINCT h FROM Halaqa h WHERE h.organization.id = :organizationId")
    List<Halaqa> findByOrganizationId(@Param("organizationId") UUID organizationId);

    @Query("SELECT h FROM Halaqa h LEFT JOIN FETCH h.students LEFT JOIN FETCH h.teacher WHERE h.id = :id")
    Optional<Halaqa> findByIdWithMembers(@Param("id") UUID id);

    List<Halaqa> findByUpdatedAtAfter(LocalDateTime since);

    @Query("SELECT h FROM Halaqa h WHERE h.updatedAt > :since AND h.organization IN :orgs")
    List<Halaqa> findByUpdatedAtAfterAndOrganizationIn(LocalDateTime since, List<Organization> orgs);
}
