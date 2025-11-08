package com.zamzam.zamzamapi.dto;

public class UpdateHalaqaRequest {
    private String name;

    public UpdateHalaqaRequest() {}

    public UpdateHalaqaRequest(String name) {
        this.name = name;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }
}