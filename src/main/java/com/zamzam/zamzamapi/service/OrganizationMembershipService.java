package com.zamzam.zamzamapi.service;

import com.zamzam.zamzamapi.dto.*;
import com.zamzam.zamzamapi.entity.OrganizationMembership;
import com.zamzam.zamzamapi.entity.Organization;
import com.zamzam.zamzamapi.entity.User;
import com.zamzam.zamzamapi.repository.OrganizationMembershipRepository;
import com.zamzam.zamzamapi.repository.OrganizationRepository;
import com.zamzam.zamzamapi.repository.UserRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import java.util.*;
import java.util.stream.Collectors;
import java.time.LocalDateTime;

@Service
public class OrganizationMembershipService {
    @Autowired
    private OrganizationMembershipRepository organizationMembershipRepository;
    @Autowired
    private UserRepository userRepository;
    @Autowired
    private OrganizationRepository organizationRepository;

    private OrganizationMembershipDto toDto(OrganizationMembership m) {
        OrganizationMembershipDto dto = new OrganizationMembershipDto();
        dto.id = m.getId();
        dto.userId = m.getUser() != null ? m.getUser().getId() : null;
        dto.organizationId = m.getOrganization() != null ? m.getOrganization().getId() : null;
        dto.role = m.getRole() != null ? m.getRole().name() : null;
        dto.joinedAt = m.getJoinedAt();
        return dto;
    }

    public List<OrganizationMembershipDto> getAllMemberships() {
        return organizationMembershipRepository.findAll().stream().map(this::toDto).collect(Collectors.toList());
    }
    public OrganizationMembershipDto getMembershipById(UUID id) {
        return organizationMembershipRepository.findById(id).map(this::toDto).orElse(null);
    }

    public OrganizationMembershipDto createMembership(CreateOrganizationMembershipRequest request) {
        OrganizationMembership m = new OrganizationMembership();
        if (request.userId == null) {
            throw new IllegalArgumentException("User ID must be provided.");
        }
        if (request.organizationId == null) {
            throw new IllegalArgumentException("Organization ID must be provided.");
        }

        organizationRepository.findById(request.organizationId).ifPresent(m::setOrganization);
        userRepository.findById(request.userId).ifPresent(m::setUser);
        m.setRole(request.role != null ? OrganizationMembership.Role.valueOf(request.role) : null);
        m.setJoinedAt(LocalDateTime.now());
        m = organizationMembershipRepository.save(m);
        return toDto(m);
    }

    public void deleteMembership(UUID id) {
        organizationMembershipRepository.deleteById(id);
    }
}

