package com.zamzam.zamzamapi.repository;

import com.zamzam.zamzamapi.entity.Organization;
import com.zamzam.zamzamapi.entity.OrganizationMembership;
import com.zamzam.zamzamapi.entity.User;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

public interface OrganizationRepository extends JpaRepository<Organization, UUID> {

    Optional<Organization> findByName(String name);
    @Query("SELECT m FROM Organization o JOIN o.members m WHERE o.id = :organizationId")
    List<OrganizationMembership> findMembershipsByOrganizationId(UUID organizationId);

    @Query("SELECT DISTINCT o FROM Organization o LEFT JOIN o.members m WHERE m.user.id = :userId OR o.createdBy.id = :userId")
    List<Organization> getByUserId(@Param("userId") UUID userId);
}

