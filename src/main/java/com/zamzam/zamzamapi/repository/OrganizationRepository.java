package com.zamzam.zamzamapi.repository;

import com.zamzam.zamzamapi.entity.Organization;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.UUID;

public interface OrganizationRepository extends JpaRepository<Organization, UUID> {
}

