package com.zamzam.zamzamapi.dto;

import java.time.LocalDateTime;
import java.util.UUID;

public class OrganizationMembershipDto {
    public UUID id;
    public UUID userId;
    public UUID organizationId;
    public String role;
    public LocalDateTime createdAt;
}

