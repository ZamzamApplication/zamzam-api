package com.zamzam.zamzamapi.service;

import com.zamzam.zamzamapi.dto.*;
import com.zamzam.zamzamapi.entity.*;
import com.zamzam.zamzamapi.repository.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.orm.ObjectOptimisticLockingFailureException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Service
public class SyncService {

  @Autowired
  private UserRepository userRepository;

  @Autowired
  private OrganizationRepository organizationRepository;

  @Autowired
  private OrganizationMembershipRepository membershipRepository;

  @Autowired
  private HalaqaRepository halaqaRepository;

  @Autowired
  private DailyProgressRepository progressRepository;

  @Autowired
  private UserService userService;

  @Autowired
  private OrganizationService organizationService;

  @Autowired
  private OrganizationMembershipService membershipService;

  @Autowired
  private HalaqaService halaqaService;

  @Autowired
  private DailyProgressService progressService;

  @Transactional(readOnly = true)
  public Map<String, Object> getSyncData(LocalDateTime since, UUID userId) {
    Map<String, Object> data = new HashMap<>();

    List<Organization> userOrgs = organizationRepository.getByUserId(userId);

    data.put("users", userRepository.findByUpdatedAtAfter(since).stream().map(userService::toDto).toList());
    data.put("organizations", organizationRepository.findByUpdatedAtAfterAndUserId(since, userId).stream()
        .map(organizationService::toDto).toList());
    data.put("memberships", membershipRepository.findByUpdatedAtAfterAndOrganizationIn(since, userOrgs).stream()
        .map(membershipService::toDto).toList());
    data.put("halaqat", halaqaRepository.findByUpdatedAtAfterAndOrganizationIn(since, userOrgs).stream()
        .map(halaqaService::toDto).toList());
    data.put("progress", progressRepository.findByUpdatedAtAfterAndHalaqaOrganizationIn(since, userOrgs).stream()
        .map(progressService::toDto).toList());

    return data;
  }

  @Transactional
  public void syncData(Map<String, Object> data) {
    // TODO implement the function to handle sync for all entities with conflict
    // resolution
    // Sync users
    // for (UserDto dto : users) {
    // try {
    // if (dto.id != null) {
    // User existing = userRepository.findById(dto.id).orElse(null);
    // if (existing != null) {
    // // Update
    // existing.setName(dto.name);
    // existing.setEmail(dto.email);
    // existing.setPasswordHash(dto.passwordHash);
    // existing.setIsAdmin(dto.isAdmin);
    // existing.setLastLoginAt(dto.lastLoginAt);
    // userRepository.save(existing);
    // }
    // } else {
    // // Create
    // CreateUserRequest req = new CreateUserRequest();
    // req.name = dto.name;
    // req.email = dto.email;
    // req.password = dto.passwordHash; // Assuming password is hashed
    // userService.createUser(req);
    // }
    // } catch (ObjectOptimisticLockingFailureException e) {
    // // Handle conflict
    // throw new RuntimeException("Conflict in user sync: " + dto.id);
    // }
    // }

    // Similarly for other entities, but for brevity, assume similar logic
    // In practice, implement for each entity with conflict handling
  }
}
