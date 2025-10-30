package com.zamzam.zamzamapi.service;

import com.zamzam.zamzamapi.dto.UserDto;
import com.zamzam.zamzamapi.dto.CreateUserRequest;
import com.zamzam.zamzamapi.entity.User;
import com.zamzam.zamzamapi.repository.UserRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import java.util.*;
import java.util.stream.Collectors;
import java.time.LocalDateTime;

@Service
public class UserService implements UserDetailsService {
    @Autowired
    private UserRepository userRepository;

    @Autowired
    private PasswordEncoder passwordEncoder;

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

    @Override
    public UserDetails loadUserByUsername(String username) throws UsernameNotFoundException {
        User user = userRepository.findByEmail(username);
        if (user == null) {
            throw new UsernameNotFoundException("User not found: " + username);
        }
        return org.springframework.security.core.userdetails.User.builder()
                .username(user.getEmail())
                .password(user.getPasswordHash())
                .roles(user.getRole() != null ? user.getRole().name() : "USER")
                .build();
    }

    public UserDto createUser(CreateUserRequest request) {
        User user = new User();
        user.setName(request.name);
        user.setEmail(request.email);
        user.setPasswordHash(passwordEncoder.encode(request.password));
        user.setRole(request.role != null ? User.Role.valueOf(request.role) : null);
        user.setCreatedAt(LocalDateTime.now());
        user = userRepository.save(user);
        return toDto(user);
    }

    public void deleteUser(UUID id) {
        userRepository.deleteById(id);
    }
}

