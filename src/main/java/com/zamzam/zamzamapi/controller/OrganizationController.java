package com.zamzam.zamzamapi.controller;

import com.zamzam.zamzamapi.dto.*;
import com.zamzam.zamzamapi.service.OrganizationService;
import com.zamzam.zamzamapi.exception.ApiException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.util.*;

@RestController
@RequestMapping("/api/organizations")
public class OrganizationController {
    @Autowired
    private OrganizationService organizationService;

    @GetMapping
    public List<OrganizationDto> getAllOrganizations() {
        return organizationService.getAllOrganizations();
    }

    @GetMapping("/{id}")
    public OrganizationDto getOrganization(@PathVariable UUID id) {
        return organizationService.getOrganizationById(id);
    }

    @GetMapping("/user/{userId}")
    public List<OrganizationDto> getOrganizationsByUserId(@PathVariable UUID userId) {
        return organizationService.getOrganizationsByUserId(userId);
    }

    @GetMapping("/{orgId}/users")
    public List<UserDto> getOrganizationUsers(@PathVariable UUID orgId) {
        return organizationService.getOrganizationUsers(orgId);
    }

    @PostMapping
    public ResponseEntity<?> createOrganization(@RequestBody CreateOrganizationRequest request) {
        try {
            OrganizationDto org = organizationService.createOrganization(request);
            return ResponseEntity.ok(org);
        } catch (ApiException e) {
            return ResponseEntity.status(e.getStatusCode()).body(e.getMessage());
        }
    }

    @PutMapping("/{id}")
    public ResponseEntity<?> updateOrganization(@PathVariable UUID id, @RequestBody UpdateOrganizationRequest request) {
        try {
            OrganizationDto org = organizationService.updateOrganization(id, request);
            return ResponseEntity.ok(org);
        } catch (ApiException e) {
            return ResponseEntity.status(e.getStatusCode()).body(e.getMessage());
        }
    }

    @DeleteMapping("/{id}")
    public void deleteOrganization(@PathVariable UUID id) {
        organizationService.deleteOrganization(id);
    }
}

