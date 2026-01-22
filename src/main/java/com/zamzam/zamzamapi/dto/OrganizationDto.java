package com.zamzam.zamzamapi.dto;

import java.time.LocalDateTime;
import java.util.Set;
import java.util.UUID;

public class OrganizationDto {
  public UUID id;
  public String name;
  public UUID createdById;
  public LocalDateTime createdAt;
  public Set<UUID> memberIds;
  public Set<UUID> halaqatIds;
  public long version;
}
