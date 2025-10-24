package com.zamzam.zamzamapi.service;

import com.zamzam.zamzamapi.dto.*;
import com.zamzam.zamzamapi.entity.Organization;
import com.zamzam.zamzamapi.entity.User;
import com.zamzam.zamzamapi.repository.OrganizationRepository;
import com.zamzam.zamzamapi.repository.UserRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import java.util.*;
import java.util.stream.Collectors;
import java.time.LocalDateTime;

@Service
public class OrganizationService {
    @Autowired
    private OrganizationRepository organizationRepository;
    @Autowired
    private UserRepository userRepository;

    private OrganizationDto toDto(Organization org) {
        OrganizationDto dto = new OrganizationDto();
        dto.id = org.getId();
        dto.name = org.getName();
        dto.createdById = org.getCreatedBy() != null ? org.getCreatedBy().getId() : null;
        dto.createdAt = org.getCreatedAt();
        dto.memberIds = org.getMembers() != null ? org.getMembers().stream().map(m -> m.getId()).collect(Collectors.toSet()) : Set.of();
        dto.halaqatIds = org.getHalaqat() != null ? org.getHalaqat().stream().map(h -> h.getId()).collect(Collectors.toSet()) : Set.of();
        return dto;
    }

    public List<OrganizationDto> getAllOrganizations() {
        return organizationRepository.findAll().stream().map(this::toDto).collect(Collectors.toList());
    }

    public OrganizationDto getOrganizationById(UUID id) {
        return organizationRepository.findById(id).map(this::toDto).orElse(null);
    }

    public OrganizationDto createOrganization(CreateOrganizationRequest request) {
        Organization org = new Organization();
        org.setName(request.name);
        org.setCreatedAt(LocalDateTime.now());
        if (request.createdById != null) {
            userRepository.findById(request.createdById).ifPresent(org::setCreatedBy);
        }
        org = organizationRepository.save(org);
        return toDto(org);
    }

    public void deleteOrganization(UUID id) {
        organizationRepository.deleteById(id);
    }
}

