package com.zamzam.zamzamapi.service;

import com.zamzam.zamzamapi.dto.*;
import com.zamzam.zamzamapi.entity.Organization;
import com.zamzam.zamzamapi.entity.OrganizationMembership;
import com.zamzam.zamzamapi.entity.User;
import com.zamzam.zamzamapi.repository.OrganizationRepository;
import com.zamzam.zamzamapi.repository.UserRepository;
import com.zamzam.zamzamapi.exception.ApiException;
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

    public OrganizationDto toDto(Organization org) {
        OrganizationDto dto = new OrganizationDto();
        dto.id = org.getId();
        dto.name = org.getName();
        dto.createdById = org.getCreatedBy() != null ? org.getCreatedBy().getId() : null;
        dto.createdAt = org.getCreatedAt();
        return dto;
    }

    public List<OrganizationDto> getAllOrganizations() {
        return organizationRepository.findAll().stream().map(this::toDto).collect(Collectors.toList());
    }

    public OrganizationDto getOrganizationById(UUID id) {
        return organizationRepository.findById(id).map(this::toDto).orElse(null);
    }

    public List<OrganizationDto> getOrganizationsByUserId(UUID userId) {
        User user = userRepository.findById(userId).orElse(null);
        if (user == null) {
            throw new ApiException(404, "User with id '" + userId + "' not found.");
        }
        List<Organization> orgs = organizationRepository.getByUserId(userId);

        return orgs.stream().map(this::toDto).collect(Collectors.toList());
    }

    public OrganizationDto createOrganization(CreateOrganizationRequest request) {
        if (organizationRepository.findByName(request.name).isPresent()) {
            throw new ApiException(400, "Organization with name '" + request.name + "' already exists.");
        }
        Organization org = new Organization();
        org.setName(request.name);
        org.setCreatedAt(LocalDateTime.now());
        if (request.createdById != null) {
            userRepository.findById(request.createdById).ifPresent(org::setCreatedBy);
        }
        org = organizationRepository.save(org);
        return toDto(org);
    }

    public OrganizationDto updateOrganization(UUID id, UpdateOrganizationRequest request) {
        Organization org = organizationRepository.findById(id).orElseThrow(() -> new ApiException(404, "Organization not found"));
        if (request.getName() != null) {
            org.setName(request.getName());
        }
        organizationRepository.save(org);
        return toDto(org);
    }

    public void deleteOrganization(UUID id) {
        organizationRepository.deleteById(id);
    }
}

