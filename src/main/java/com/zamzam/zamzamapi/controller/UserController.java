package com.zamzam.zamzamapi.controller;

import com.zamzam.zamzamapi.dto.CreateUserRequest;
import com.zamzam.zamzamapi.dto.UserDto;
import com.zamzam.zamzamapi.service.UserService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/users")
public class UserController {
    @Autowired
    private UserService userService;

    @GetMapping
    public List<UserDto> getAllUsers() {
        return userService.getAllUsers();
    }

    @GetMapping("/{id}")
    public UserDto getUser(@PathVariable UUID id) {
        return userService.getUserById(id);
    }

    @PostMapping
    public UserDto createUser(@RequestBody CreateUserRequest request) {
        return userService.createUser(request);
    }

    @DeleteMapping("/{id}")
    public void deleteUser(@PathVariable UUID id) {
        userService.deleteUser(id);
    }
}

