package com.zamzam.zamzamapi.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.zamzam.zamzamapi.dto.*;
import com.zamzam.zamzamapi.exception.ApiException;
import com.zamzam.zamzamapi.exception.GlobalExceptionHandler;
import com.zamzam.zamzamapi.service.HalaqaService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
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

@WebMvcTest(HalaqaController.class)
@Import(GlobalExceptionHandler.class)
@WithMockUser
public class HalaqaControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private HalaqaService halaqaService;

    @Autowired
    private ObjectMapper objectMapper;

    @Test
    public void testGetAllHalaqat() throws Exception {
        List<HalaqaDto> halaqat = Arrays.asList(createSampleHalaqaDto());
        when(halaqaService.getAllHalaqat()).thenReturn(halaqat);

        mockMvc.perform(get("/api/halaqat"))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$", hasSize(1)));

        verify(halaqaService, times(1)).getAllHalaqat();
    }

    @Test
    public void testGetHalaqa() throws Exception {
        UUID id = UUID.randomUUID();
        HalaqaDto halaqa = createSampleHalaqaDto();
        halaqa.id = id;
        when(halaqaService.getHalaqaById(id)).thenReturn(halaqa);

        mockMvc.perform(get("/api/halaqat/{id}", id))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.id").exists());

        verify(halaqaService, times(1)).getHalaqaById(id);
    }

    @Test
    public void testGetHalaqaNotFound() throws Exception {
        UUID id = UUID.randomUUID();
        when(halaqaService.getHalaqaById(id)).thenThrow(new ApiException(404, "Halaqa not found"));

        mockMvc.perform(get("/api/halaqat/{id}", id))
                .andExpect(status().isNotFound());

        verify(halaqaService, times(1)).getHalaqaById(id);
    }

    @Test
    public void testGetOrganizationHalaqat() throws Exception {
        UUID orgId = UUID.randomUUID();
        List<HalaqaDto> halaqat = Arrays.asList(createSampleHalaqaDto());
        when(halaqaService.getOrganizationHalaqat(orgId)).thenReturn(halaqat);

        mockMvc.perform(get("/api/halaqat/organization/{id}", orgId))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$", hasSize(1)));

        verify(halaqaService, times(1)).getOrganizationHalaqat(orgId);
    }

    @Test
    public void testGetHalaqaMembers() throws Exception {
        UUID id = UUID.randomUUID();
        List<HalaqaMemberDto> members = Arrays.asList(createSampleHalaqaMemberDto());
        when(halaqaService.getHalaqaMembers(id)).thenReturn(members);

        mockMvc.perform(get("/api/halaqat/{id}/members", id))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$", hasSize(1)));

        verify(halaqaService, times(1)).getHalaqaMembers(id);
    }

    @Test
    public void testAddHalaqaMember() throws Exception {
        UUID halaqaId = UUID.randomUUID();
        AddHalaqaMemberRequest request = createSampleAddMemberRequest();
        HalaqaMemberDto member = createSampleHalaqaMemberDto();
        when(halaqaService.addHalaqaMember(any(UUID.class), any(AddHalaqaMemberRequest.class))).thenReturn(member);

        mockMvc.perform(post("/api/halaqat/{halaqaId}/member", halaqaId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request))
                        .with(csrf()))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.id").exists());

        verify(halaqaService, times(1)).addHalaqaMember(any(UUID.class), any(AddHalaqaMemberRequest.class));
    }

    @Test
    public void testAddHalaqaMemberError() throws Exception {
        UUID halaqaId = UUID.randomUUID();
        AddHalaqaMemberRequest request = createSampleAddMemberRequest();
        when(halaqaService.addHalaqaMember(any(UUID.class), any(AddHalaqaMemberRequest.class))).thenThrow(new ApiException(400, "Error adding member"));

        mockMvc.perform(post("/api/halaqat/{halaqaId}/member", halaqaId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request))
                        .with(csrf()))
                .andExpect(status().isBadRequest());

        verify(halaqaService, times(1)).addHalaqaMember(any(UUID.class), any(AddHalaqaMemberRequest.class));
    }

    @Test
    public void testCreateHalaqa() throws Exception {
        CreateHalaqaRequest request = createSampleCreateHalaqaRequest();
        HalaqaDto halaqa = createSampleHalaqaDto();
        when(halaqaService.createHalaqa(any(CreateHalaqaRequest.class))).thenReturn(halaqa);

        mockMvc.perform(post("/api/halaqat")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request))
                        .with(csrf()))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.id").exists());

        verify(halaqaService, times(1)).createHalaqa(any(CreateHalaqaRequest.class));
    }

    @Test
    public void testCreateHalaqaError() throws Exception {
        CreateHalaqaRequest request = createSampleCreateHalaqaRequest();
        when(halaqaService.createHalaqa(any(CreateHalaqaRequest.class))).thenThrow(new ApiException(400, "Validation error"));

        mockMvc.perform(post("/api/halaqat")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request))
                        .with(csrf()))
                .andExpect(status().isBadRequest());

        verify(halaqaService, times(1)).createHalaqa(any(CreateHalaqaRequest.class));
    }

    @Test
    public void testDeleteHalaqa() throws Exception {
        UUID id = UUID.randomUUID();
        doNothing().when(halaqaService).deleteHalaqa(id);

        mockMvc.perform(delete("/api/halaqat/{id}", id).with(csrf()))
                .andExpect(status().isOk());

        verify(halaqaService, times(1)).deleteHalaqa(id);
    }

    @Test
    public void testDeleteHalaqaNotFound() throws Exception {
        UUID id = UUID.randomUUID();
        doThrow(new ApiException(404, "Halaqa not found")).when(halaqaService).deleteHalaqa(id);

        mockMvc.perform(delete("/api/halaqat/{id}", id).with(csrf()))
                .andExpect(status().isNotFound());

        verify(halaqaService, times(1)).deleteHalaqa(id);
    }

    private HalaqaDto createSampleHalaqaDto() {
        HalaqaDto dto = new HalaqaDto();
        dto.id = UUID.randomUUID();
        dto.name = "Sample Halaqa";
        dto.organizationId = UUID.randomUUID();
        dto.teacherId = UUID.randomUUID();
        dto.createdAt = LocalDateTime.now();
        dto.studentIds = new HashSet<>(Arrays.asList(UUID.randomUUID()));
        return dto;
    }

    private CreateHalaqaRequest createSampleCreateHalaqaRequest() {
        CreateHalaqaRequest request = new CreateHalaqaRequest();
        request.name = "New Halaqa";
        request.organizationId = UUID.randomUUID();
        request.teacherId = UUID.randomUUID();
        return request;
    }

    private AddHalaqaMemberRequest createSampleAddMemberRequest() {
        AddHalaqaMemberRequest request = new AddHalaqaMemberRequest();
        request.userId = UUID.randomUUID();
        request.role = "STUDENT";
        return request;
    }

    private HalaqaMemberDto createSampleHalaqaMemberDto() {
        HalaqaMemberDto dto = new HalaqaMemberDto();
        dto.id = UUID.randomUUID();
        dto.name = "Member Name";
        dto.role = "STUDENT";
        return dto;
    }
}