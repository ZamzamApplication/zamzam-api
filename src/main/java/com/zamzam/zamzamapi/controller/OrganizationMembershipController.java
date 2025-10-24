package com.zamzam.zamzamapi.controller;

import com.zamzam.zamzamapi.dto.*;
import com.zamzam.zamzamapi.service.OrganizationMembershipService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;
import java.util.*;

@RestController
@RequestMapping("/api/memberships")
public class OrganizationMembershipController {
    @Autowired
    private OrganizationMembershipService organizationMembershipService;

    @GetMapping
    public List<OrganizationMembershipDto> getAllMemberships() {
        return organizationMembershipService.getAllMemberships();
    }

    @GetMapping("/{id}")
    public OrganizationMembershipDto getMembership(@PathVariable UUID id) {
        return organizationMembershipService.getMembershipById(id);
    }

    @PostMapping
    public OrganizationMembershipDto createMembership(@RequestBody CreateOrganizationMembershipRequest request) {
        return organizationMembershipService.createMembership(request);
    }

    @DeleteMapping("/{id}")
    public void deleteMembership(@PathVariable UUID id) {
        organizationMembershipService.deleteMembership(id);
    }
}

