package com.zamzam.zamzamapi.dto;

public class UpdateOrganizationRequest {
    private String name;

    public UpdateOrganizationRequest() {}

    public UpdateOrganizationRequest(String name) {
        this.name = name;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }
}