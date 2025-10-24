package com.zamzam.zamzamapi.dto;

import java.time.LocalDateTime;
import java.util.Set;
import java.util.UUID;

public class HalaqaDto {
    public UUID id;
    public String name;
    public UUID organizationId;
    public UUID teacherId;
    public LocalDateTime createdAt;
    public Set<UUID> studentIds;
}

