package com.zamzam.zamzamapi.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.zamzam.zamzamapi.dto.CreateOrganizationRequest;
import com.zamzam.zamzamapi.dto.OrganizationDto;
import com.zamzam.zamzamapi.exception.ApiException;
import com.zamzam.zamzamapi.service.OrganizationService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.security.test.context.support.WithMockUser;
import org.springframework.test.web.servlet.MockMvc;

import java.time.LocalDateTime;
import java.util.*;

import static org.hamcrest.Matchers.hasSize;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(OrganizationController.class)
@WithMockUser
public class OrganizationControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private OrganizationService organizationService;

    @Autowired
    private ObjectMapper objectMapper;

    @Test
    public void testGetAllOrganizations() throws Exception {
        List<OrganizationDto> organizations = Arrays.asList(createSampleOrganizationDto());
        when(organizationService.getAllOrganizations()).thenReturn(organizations);

        mockMvc.perform(get("/api/organizations"))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$", hasSize(1)));

        verify(organizationService, times(1)).getAllOrganizations();
    }

    @Test
    public void testGetOrganization() throws Exception {
        UUID id = UUID.randomUUID();
        OrganizationDto organization = createSampleOrganizationDto();
        organization.id = id;
        when(organizationService.getOrganizationById(id)).thenReturn(organization);

        mockMvc.perform(get("/api/organizations/{id}", id))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.id").value(id.toString()));

        verify(organizationService, times(1)).getOrganizationById(id);
    }

    @Test
    public void testGetOrganizationNotFound() throws Exception {
        UUID id = UUID.randomUUID();
        when(organizationService.getOrganizationById(id)).thenThrow(new ApiException(404, "Organization not found"));

        mockMvc.perform(get("/api/organizations/{id}", id))
                .andExpect(status().isNotFound());

        verify(organizationService, times(1)).getOrganizationById(id);
    }

    @Test
    public void testGetOrganizationsByUserId() throws Exception {
        UUID userId = UUID.randomUUID();
        List<OrganizationDto> organizations = Arrays.asList(createSampleOrganizationDto());
        when(organizationService.getOrganizationsByUserId(userId)).thenReturn(organizations);

        mockMvc.perform(get("/api/organizations/user/{userId}", userId))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$", hasSize(1)));

        verify(organizationService, times(1)).getOrganizationsByUserId(userId);
    }

    @Test
    public void testCreateOrganization() throws Exception {
        CreateOrganizationRequest request = createSampleCreateOrganizationRequest();
        OrganizationDto organization = createSampleOrganizationDto();
        when(organizationService.createOrganization(any(CreateOrganizationRequest.class))).thenReturn(organization);

        mockMvc.perform(post("/api/organizations")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request))
                        .with(csrf()))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.id").exists());

        verify(organizationService, times(1)).createOrganization(any(CreateOrganizationRequest.class));
    }

    @Test
    public void testCreateOrganizationError() throws Exception {
        CreateOrganizationRequest request = createSampleCreateOrganizationRequest();
        when(organizationService.createOrganization(any(CreateOrganizationRequest.class))).thenThrow(new ApiException(400, "Validation error"));

        mockMvc.perform(post("/api/organizations")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request))
                        .with(csrf()))
                .andExpect(status().isBadRequest());

        verify(organizationService, times(1)).createOrganization(any(CreateOrganizationRequest.class));
    }

    @Test
    public void testDeleteOrganization() throws Exception {
        UUID id = UUID.randomUUID();
        doNothing().when(organizationService).deleteOrganization(id);

        mockMvc.perform(delete("/api/organizations/{id}", id).with(csrf()))
                .andExpect(status().isOk());

        verify(organizationService, times(1)).deleteOrganization(id);
    }

    @Test
    public void testDeleteOrganizationNotFound() throws Exception {
        UUID id = UUID.randomUUID();
        doThrow(new ApiException(404, "Organization not found")).when(organizationService).deleteOrganization(id);

        mockMvc.perform(delete("/api/organizations/{id}", id).with(csrf()))
                .andExpect(status().isNotFound());

        verify(organizationService, times(1)).deleteOrganization(id);
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

    private CreateOrganizationRequest createSampleCreateOrganizationRequest() {
        CreateOrganizationRequest request = new CreateOrganizationRequest();
        request.name = "New Organization";
        request.createdById = UUID.randomUUID();
        return request;
    }
}