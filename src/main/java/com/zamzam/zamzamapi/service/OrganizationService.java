package com.zamzam.zamzamapi.service;

import com.zamzam.zamzamapi.dto.*;
import com.zamzam.zamzamapi.entity.Halaqa;
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

    private OrganizationDto toDto(Organization org) {
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

    public void deleteOrganization(UUID id) {
        organizationRepository.deleteById(id);
    }
}

