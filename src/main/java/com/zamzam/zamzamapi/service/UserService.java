package com.zamzam.zamzamapi.service;

import com.zamzam.zamzamapi.dto.UserDto;
import com.zamzam.zamzamapi.dto.CreateUserRequest;
import com.zamzam.zamzamapi.dto.UpdateUserRequest;
import com.zamzam.zamzamapi.dto.OrganizationDto;
import com.zamzam.zamzamapi.entity.User;
import com.zamzam.zamzamapi.entity.OrganizationMembership;
import com.zamzam.zamzamapi.repository.UserRepository;
import com.zamzam.zamzamapi.repository.OrganizationMembershipRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import com.zamzam.zamzamapi.exception.ApiException;
import java.util.*;
import java.util.stream.Collectors;
import java.time.LocalDateTime;

@Service
public class UserService implements UserDetailsService {
    @Autowired
    private UserRepository userRepository;

    @Autowired
    private PasswordEncoder passwordEncoder;

    @Autowired
    private OrganizationMembershipRepository organizationMembershipRepository;

    @Autowired
    private OrganizationService organizationService;

    public UserDto toDto(User user) {
        UserDto dto = new UserDto();
        dto.id = user.getId();
        dto.name = user.getName();
        dto.email = user.getEmail();
        dto.role = user.getIsAdmin() ? "ADMIN" : "USER";
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
                .build();
    }

    public UserDto createUser(CreateUserRequest request) {
        if (userRepository.findByEmail(request.email) != null) {
            throw new ApiException(409, "Email already exists");
        }

        User user = new User();
        user.setName(request.name);
        user.setEmail(request.email);
        user.setPasswordHash(passwordEncoder.encode(request.password));
        user.setIsAdmin(false);
        user.setCreatedAt(LocalDateTime.now());
        user = userRepository.save(user);
        return toDto(user);
    }

    public UserDto updateUser(UUID id, UpdateUserRequest request) {
        User user = userRepository.findById(id).orElseThrow(() -> new ApiException(404, "User not found"));
        if (request.getName() != null) {
            user.setName(request.getName());
        }
        if (request.getEmail() != null) {
            user.setEmail(request.getEmail());
        }
        if (request.getPassword() != null) {
            user.setPasswordHash(passwordEncoder.encode(request.getPassword()));
        }
        userRepository.save(user);
        return toDto(user);
    }

    public void deleteUser(UUID id) {
        userRepository.deleteById(id);
    }

    public List<OrganizationDto> getOrganizationsForUser(UUID userId) {
        List<OrganizationMembership> memberships = organizationMembershipRepository.findByUserId(userId);
        return memberships.stream()
            .map(m -> organizationService.toDto(m.getOrganization()))
            .collect(Collectors.toList());
    }
}

