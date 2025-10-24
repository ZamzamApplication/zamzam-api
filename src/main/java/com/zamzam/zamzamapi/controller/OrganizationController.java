package com.zamzam.zamzamapi.controller;

import com.zamzam.zamzamapi.dto.*;
import com.zamzam.zamzamapi.service.OrganizationService;
import org.springframework.beans.factory.annotation.Autowired;
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

    @PostMapping
    public OrganizationDto createOrganization(@RequestBody CreateOrganizationRequest request) {
        return organizationService.createOrganization(request);
    }

    @DeleteMapping("/{id}")
    public void deleteOrganization(@PathVariable UUID id) {
        organizationService.deleteOrganization(id);
    }
}

