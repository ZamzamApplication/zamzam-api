package com.zamzam.zamzamapi.repository;

import com.zamzam.zamzamapi.entity.OrganizationMembership;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.UUID;

public interface OrganizationMembershipRepository extends JpaRepository<OrganizationMembership, UUID> {
}

