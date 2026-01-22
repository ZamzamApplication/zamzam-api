package com.zamzam.zamzamapi.dto;

import java.time.LocalDateTime;
import java.util.Set;
import java.util.UUID;

public class UserDto {
  public UUID id;
  public String name;
  public String email;
  public Boolean isAdmin;
  public String role;
  public LocalDateTime createdAt;
  public String passwordHash;
  public LocalDateTime lastLoginAt;
  public Set<UUID> childrenIds;
  public Set<UUID> parentIds;
  public Set<UUID> halaqatIds;
  public long version;
}
