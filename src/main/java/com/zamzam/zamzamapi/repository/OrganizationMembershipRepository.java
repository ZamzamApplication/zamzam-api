package com.zamzam.zamzamapi.repository;

import com.zamzam.zamzamapi.entity.OrganizationMembership;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import java.util.List;
import java.util.UUID;

public interface OrganizationMembershipRepository extends JpaRepository<OrganizationMembership, UUID> {

    @Query("SELECT m FROM OrganizationMembership m WHERE m.organization.id = :organizationId")
    List<OrganizationMembership> findByOrganizationId(UUID organizationId);

    List<OrganizationMembership> findByUserId(UUID userId);
}

