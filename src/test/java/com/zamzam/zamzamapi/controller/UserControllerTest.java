package com.zamzam.zamzamapi.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.zamzam.zamzamapi.dto.CreateUserRequest;
import com.zamzam.zamzamapi.dto.OrganizationDto;
import com.zamzam.zamzamapi.dto.UserDto;
import com.zamzam.zamzamapi.exception.ApiException;
import com.zamzam.zamzamapi.exception.GlobalExceptionHandler;
import com.zamzam.zamzamapi.service.UserService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.security.test.context.support.WithMockUser;
import org.springframework.test.web.servlet.MockMvc;

import java.time.LocalDateTime;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import java.util.*;

import static org.hamcrest.Matchers.hasSize;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(UserController.class)
@AutoConfigureMockMvc(addFilters = false)
@WithMockUser
public class UserControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private UserService userService;

    @Autowired
    private ObjectMapper objectMapper;

    @Test
    @WithMockUser
    public void testGetAllUsers() throws Exception {
        List<UserDto> users = Arrays.asList(createSampleUserDto());
        when(userService.getAllUsers()).thenReturn(users);

        mockMvc.perform(get("/api/users"))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$", hasSize(1)));

        verify(userService, times(1)).getAllUsers();
    }

    @Test
    @WithMockUser
    public void testGetUser() throws Exception {
        UUID id = UUID.randomUUID();
        UserDto user = createSampleUserDto();
        user.id = id;
        when(userService.getUserById(id)).thenReturn(user);

        mockMvc.perform(get("/api/users/{id}", id))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.id").value(id.toString()));

        verify(userService, times(1)).getUserById(id);
    }

    @Test
    @WithMockUser
    public void testGetUserNotFound() throws Exception {
        UUID id = UUID.randomUUID();
        when(userService.getUserById(id)).thenThrow(new ApiException(404, "User not found"));

        mockMvc.perform(get("/api/users/{id}", id))
                .andExpect(status().isNotFound());

        verify(userService, times(1)).getUserById(id);
    }

    @Test
    @WithMockUser
    public void testGetUserOrganizations() throws Exception {
        UUID userId = UUID.randomUUID();
        List<OrganizationDto> organizations = Arrays.asList(createSampleOrganizationDto());
        when(userService.getOrganizationsForUser(userId)).thenReturn(organizations);

        mockMvc.perform(get("/api/users/{userId}/organizations", userId))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$", hasSize(1)));

        verify(userService, times(1)).getOrganizationsForUser(userId);
    }

    @Test
    public void testCreateUser() throws Exception {
        CreateUserRequest request = createSampleCreateUserRequest();
        UserDto user = createSampleUserDto();
        when(userService.createUser(any(CreateUserRequest.class))).thenReturn(user);

        mockMvc.perform(post("/api/users")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request))
                        .with(csrf()))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.id").exists());

        verify(userService, times(1)).createUser(any(CreateUserRequest.class));
    }

    @Test
    public void testCreateUserError() throws Exception {
        CreateUserRequest request = createSampleCreateUserRequest();
        when(userService.createUser(any(CreateUserRequest.class))).thenThrow(new ApiException(400, "Validation error"));

        mockMvc.perform(post("/api/users")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request))
                        .with(csrf()))
                .andExpect(status().isBadRequest());

        verify(userService, times(1)).createUser(any(CreateUserRequest.class));
    }

    @Test
    @WithMockUser
    public void testDeleteUser() throws Exception {
        UUID id = UUID.randomUUID();
        doNothing().when(userService).deleteUser(id);

        mockMvc.perform(delete("/api/users/{id}", id).with(csrf()))
                .andExpect(status().isOk());

        verify(userService, times(1)).deleteUser(id);
    }

    @Test
    @WithMockUser
    public void testDeleteUserNotFound() throws Exception {
        UUID id = UUID.randomUUID();
        doThrow(new ApiException(404, "User not found")).when(userService).deleteUser(id);

        mockMvc.perform(delete("/api/users/{id}", id).with(csrf()))
                .andExpect(status().isNotFound());

        verify(userService, times(1)).deleteUser(id);
    }

    private UserDto createSampleUserDto() {
        UserDto dto = new UserDto();
        dto.id = UUID.randomUUID();
        dto.name = "Sample User";
        dto.email = "user@example.com";
        dto.isAdmin = false;
        dto.role = "STUDENT";
        dto.createdAt = LocalDateTime.now();
        dto.childrenIds = new HashSet<>(Arrays.asList(UUID.randomUUID()));
        dto.parentIds = new HashSet<>(Arrays.asList(UUID.randomUUID()));
        dto.halaqatIds = new HashSet<>(Arrays.asList(UUID.randomUUID()));
        return dto;
    }

    private CreateUserRequest createSampleCreateUserRequest() {
        CreateUserRequest request = new CreateUserRequest();
        request.name = "New User";
        request.email = "new@example.com";
        request.password = "password";
        return request;
    }

    private OrganizationDto createSampleOrganizationDto() {
        OrganizationDto dto = new OrganizationDto();
        dto.id = UUID.randomUUID();
        dto.name = "Sample Organization";
        dto.createdById = UUID.randomUUID();
        dto.createdAt = LocalDateTime.now();
        dto.memberIds = new HashSet<>(Arrays.asList(UUID.randomUUID()));
        dto.halaqatIds = new HashSet<>(Arrays.asList(UUID.randomUUID()));
        return dto;
    }
}