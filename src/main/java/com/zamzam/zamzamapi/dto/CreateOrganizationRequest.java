package com.zamzam.zamzamapi.dto;

import jakarta.validation.constraints.*;
import java.util.UUID;

public class CreateOrganizationRequest {
    @NotBlank(message = "Organization name is required")
    @Size(min = 2, max = 200, message = "Organization name must be between 2 and 200 characters")
    public String name;
    
    @NotNull(message = "Creator ID is required")
    public UUID createdById;
}
