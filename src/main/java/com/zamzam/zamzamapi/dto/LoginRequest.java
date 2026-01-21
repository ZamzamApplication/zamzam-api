package com.zamzam.zamzamapi.dto;

import jakarta.validation.constraints.*;

public class LoginRequest {
    @NotBlank(message = "Email is required")
    @Email(message = "Email should be valid")
    public String email;
    
    @NotBlank(message = "Password is required")
    public String password;

    public LoginRequest() {}

    public LoginRequest(String email, String password) {
        this.email = email;
        this.password = password;
    }

}