package com.zamzam.zamzamapi.controller;

import com.zamzam.zamzamapi.dto.CreateUserRequest;
import com.zamzam.zamzamapi.dto.UpdateUserRequest;
import com.zamzam.zamzamapi.dto.UserDto;
import com.zamzam.zamzamapi.dto.OrganizationDto;
import com.zamzam.zamzamapi.dto.PaginatedResponse;
import com.zamzam.zamzamapi.service.UserService;
import com.zamzam.zamzamapi.exception.ApiException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import jakarta.validation.Valid;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/users")
public class UserController {
    @Autowired
    private UserService userService;

    @GetMapping
    public PaginatedResponse<UserDto> getAllUsers(Pageable pageable) {
        return userService.getAllUsers(pageable);
    }

    @GetMapping("/{id}")
    public UserDto getUser(@PathVariable UUID id) {
        return userService.getUserById(id);
    }

    @GetMapping("/{userId}/organizations")
    public List<OrganizationDto> getUserOrganizations(@PathVariable UUID userId) {
        return userService.getOrganizationsForUser(userId);
    }

    @PostMapping
    public ResponseEntity<?> createUser(@Valid @RequestBody CreateUserRequest request) {
        try {
            UserDto user = userService.createUser(request);
            return ResponseEntity.ok(user);
        } catch (ApiException e) {
            return ResponseEntity.status(e.getStatusCode()).body(e.getMessage());
        }
    }

    @PutMapping("/{id}")
    public ResponseEntity<?> updateUser(@PathVariable UUID id, @Valid @RequestBody UpdateUserRequest request) {
        try {
            UserDto user = userService.updateUser(id, request);
            return ResponseEntity.ok(user);
        } catch (ApiException e) {
            return ResponseEntity.status(e.getStatusCode()).body(e.getMessage());
        }
    }

    @DeleteMapping("/{id}")
    public void deleteUser(@PathVariable UUID id) {
        userService.deleteUser(id);
    }
}

