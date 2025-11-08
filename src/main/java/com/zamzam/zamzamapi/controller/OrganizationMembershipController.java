package com.zamzam.zamzamapi.controller;

import com.zamzam.zamzamapi.dto.*;
import com.zamzam.zamzamapi.service.OrganizationMembershipService;
import com.zamzam.zamzamapi.exception.ApiException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
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
    public ResponseEntity<?> createMembership(@RequestBody CreateOrganizationMembershipRequest request) {
        try {
            OrganizationMembershipDto membership = organizationMembershipService.createMembership(request);
            return ResponseEntity.ok(membership);
        } catch (ApiException e) {
            return ResponseEntity.status(e.getStatusCode()).body(e.getMessage());
        }
    }

    @PutMapping("/{id}")
    public ResponseEntity<?> updateMembership(@PathVariable UUID id, @RequestBody UpdateOrganizationMembershipRequest request) {
        try {
            OrganizationMembershipDto membership = organizationMembershipService.updateMembership(id, request);
            return ResponseEntity.ok(membership);
        } catch (ApiException e) {
            return ResponseEntity.status(e.getStatusCode()).body(e.getMessage());
        }
    }

    @DeleteMapping("/{id}")
    public void deleteMembership(@PathVariable UUID id) {
        organizationMembershipService.deleteMembership(id);
    }
}

