package com.zamzam.zamzamapi.service;

import com.zamzam.zamzamapi.dto.UserDto;
import com.zamzam.zamzamapi.dto.CreateUserRequest;
import com.zamzam.zamzamapi.entity.User;
import com.zamzam.zamzamapi.repository.UserRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import java.util.*;
import java.util.stream.Collectors;
import java.time.LocalDateTime;

@Service
public class UserService {
    @Autowired
    private UserRepository userRepository;

    private UserDto toDto(User user) {
        UserDto dto = new UserDto();
        dto.id = user.getId();
        dto.name = user.getName();
        dto.email = user.getEmail();
        dto.role = user.getRole() != null ? user.getRole().name() : null;
        dto.createdAt = user.getCreatedAt();
        dto.childrenIds = user.getChildren() != null ? user.getChildren().stream().map(User::getId).collect(Collectors.toSet()) : Set.of();
        dto.parentIds = user.getParents() != null ? user.getParents().stream().map(User::getId).collect(Collectors.toSet()) : Set.of();
        dto.halaqatIds = user.getHalaqat() != null ? user.getHalaqat().stream().map(h -> h.getId()).collect(Collectors.toSet()) : Set.of();
        return dto;
    }

    public List<UserDto> getAllUsers() {
        return userRepository.findAll().stream().map(this::toDto).collect(Collectors.toList());
    }

    public UserDto getUserById(UUID id) {
        return userRepository.findById(id).map(this::toDto).orElse(null);
    }

    public UserDto createUser(CreateUserRequest request) {
        User user = new User();
        user.setName(request.name);
        user.setEmail(request.email);
        user.setPasswordHash(request.password); // In production, hash the password!
        user.setRole(request.role != null ? User.Role.valueOf(request.role) : null);
        user.setCreatedAt(LocalDateTime.now());
        user = userRepository.save(user);
        return toDto(user);
    }

    public void deleteUser(UUID id) {
        userRepository.deleteById(id);
    }
}

