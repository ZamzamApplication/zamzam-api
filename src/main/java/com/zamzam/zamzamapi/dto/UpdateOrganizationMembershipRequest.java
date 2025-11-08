package com.zamzam.zamzamapi.dto;

public class UpdateOrganizationMembershipRequest {
    private String role;

    public UpdateOrganizationMembershipRequest() {}

    public UpdateOrganizationMembershipRequest(String role) {
        this.role = role;
    }

    public String getRole() {
        return role;
    }

    public void setRole(String role) {
        this.role = role;
    }
}