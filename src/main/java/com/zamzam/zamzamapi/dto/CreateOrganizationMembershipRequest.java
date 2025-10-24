package com.zamzam.zamzamapi.dto;

import java.util.UUID;

public class CreateOrganizationMembershipRequest {
    public UUID userId;
    public UUID organizationId;
    public String role;
}
