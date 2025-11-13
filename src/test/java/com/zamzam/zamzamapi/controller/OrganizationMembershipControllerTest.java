package com.zamzam.zamzamapi.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.zamzam.zamzamapi.dto.CreateOrganizationMembershipRequest;
import com.zamzam.zamzamapi.dto.OrganizationMembershipDto;
import com.zamzam.zamzamapi.exception.ApiException;
import com.zamzam.zamzamapi.service.OrganizationMembershipService;
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

@WebMvcTest(OrganizationMembershipController.class)
@WithMockUser
public class OrganizationMembershipControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private OrganizationMembershipService organizationMembershipService;

    @Autowired
    private ObjectMapper objectMapper;

    @Test
    public void testGetAllMemberships() throws Exception {
        List<OrganizationMembershipDto> memberships = Arrays.asList(createSampleMembershipDto());
        when(organizationMembershipService.getAllMemberships()).thenReturn(memberships);

        mockMvc.perform(get("/api/memberships"))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$", hasSize(1)));

        verify(organizationMembershipService, times(1)).getAllMemberships();
    }

    @Test
    public void testGetMembership() throws Exception {
        UUID id = UUID.randomUUID();
        OrganizationMembershipDto membership = createSampleMembershipDto();
        membership.id = id;
        when(organizationMembershipService.getMembershipById(id)).thenReturn(membership);

        mockMvc.perform(get("/api/memberships/{id}", id))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.id").value(id.toString()));

        verify(organizationMembershipService, times(1)).getMembershipById(id);
    }

    @Test
    public void testGetMembershipNotFound() throws Exception {
        UUID id = UUID.randomUUID();
        when(organizationMembershipService.getMembershipById(id)).thenThrow(new ApiException(404, "Membership not found"));

        mockMvc.perform(get("/api/memberships/{id}", id))
                .andExpect(status().isNotFound());

        verify(organizationMembershipService, times(1)).getMembershipById(id);
    }

    @Test
    public void testCreateMembership() throws Exception {
        CreateOrganizationMembershipRequest request = createSampleCreateMembershipRequest();
        OrganizationMembershipDto membership = createSampleMembershipDto();
        when(organizationMembershipService.createMembership(any(CreateOrganizationMembershipRequest.class))).thenReturn(membership);

        mockMvc.perform(post("/api/memberships")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request))
                        .with(csrf()))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.id").exists());

        verify(organizationMembershipService, times(1)).createMembership(any(CreateOrganizationMembershipRequest.class));
    }

    @Test
    public void testCreateMembershipError() throws Exception {
        CreateOrganizationMembershipRequest request = createSampleCreateMembershipRequest();
        when(organizationMembershipService.createMembership(any(CreateOrganizationMembershipRequest.class))).thenThrow(new ApiException(400, "Validation error"));

        mockMvc.perform(post("/api/memberships")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request))
                        .with(csrf()))
                .andExpect(status().isBadRequest());

        verify(organizationMembershipService, times(1)).createMembership(any(CreateOrganizationMembershipRequest.class));
    }

    @Test
    public void testDeleteMembership() throws Exception {
        UUID id = UUID.randomUUID();
        doNothing().when(organizationMembershipService).deleteMembership(id);

        mockMvc.perform(delete("/api/memberships/{id}", id).with(csrf()))
                .andExpect(status().isOk());

        verify(organizationMembershipService, times(1)).deleteMembership(id);
    }

    @Test
    public void testDeleteMembershipNotFound() throws Exception {
        UUID id = UUID.randomUUID();
        doThrow(new ApiException(404, "Membership not found")).when(organizationMembershipService).deleteMembership(id);

        mockMvc.perform(delete("/api/memberships/{id}", id).with(csrf()))
                .andExpect(status().isNotFound());

        verify(organizationMembershipService, times(1)).deleteMembership(id);
    }

    private OrganizationMembershipDto createSampleMembershipDto() {
        OrganizationMembershipDto dto = new OrganizationMembershipDto();
        dto.id = UUID.randomUUID();
        dto.userId = UUID.randomUUID();
        dto.organizationId = UUID.randomUUID();
        dto.role = "MEMBER";
        dto.joinedAt = LocalDateTime.now();
        return dto;
    }

    private CreateOrganizationMembershipRequest createSampleCreateMembershipRequest() {
        CreateOrganizationMembershipRequest request = new CreateOrganizationMembershipRequest();
        request.userId = UUID.randomUUID();
        request.organizationId = UUID.randomUUID();
        request.role = "MEMBER";
        return request;
    }
}