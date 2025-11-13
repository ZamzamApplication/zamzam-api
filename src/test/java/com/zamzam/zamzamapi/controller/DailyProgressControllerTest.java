package com.zamzam.zamzamapi.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.zamzam.zamzamapi.dto.CreateDailyProgressRequest;
import com.zamzam.zamzamapi.dto.DailyProgressDto;
import com.zamzam.zamzamapi.exception.ApiException;
import com.zamzam.zamzamapi.service.DailyProgressService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.security.test.context.support.WithMockUser;
import org.springframework.test.web.servlet.MockMvc;

import java.time.LocalDate;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;

import static org.hamcrest.Matchers.hasSize;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(DailyProgressController.class)
@AutoConfigureMockMvc(addFilters = false)
@WithMockUser
public class DailyProgressControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private DailyProgressService dailyProgressService;



    @Test
    public void testGetAllProgress() throws Exception {
        List<DailyProgressDto> progressList = Arrays.asList(createSampleProgressDto());
        when(dailyProgressService.getAllProgress()).thenReturn(progressList);

        mockMvc.perform(get("/api/progress"))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$", hasSize(1)));

        verify(dailyProgressService, times(1)).getAllProgress();
    }

    @Test
    public void testGetProgress() throws Exception {
        UUID id = UUID.randomUUID();
        DailyProgressDto progress = createSampleProgressDto();
        progress.id = id;
        when(dailyProgressService.getProgressById(id)).thenReturn(progress);

        mockMvc.perform(get("/api/progress/{id}", id))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.id").exists());

        verify(dailyProgressService, times(1)).getProgressById(id);
    }

    @Test
    public void testGetProgressNotFound() throws Exception {
        UUID id = UUID.randomUUID();
        when(dailyProgressService.getProgressById(id)).thenThrow(new ApiException(404, "Progress not found"));

        mockMvc.perform(get("/api/progress/{id}", id))
                .andExpect(status().isNotFound());

        verify(dailyProgressService, times(1)).getProgressById(id);
    }

    @Test
    public void testCreateProgress() throws Exception {
        CreateDailyProgressRequest request = createSampleCreateRequest();
        DailyProgressDto created = createSampleProgressDto();
        when(dailyProgressService.createProgress(any(CreateDailyProgressRequest.class))).thenReturn(created);

        mockMvc.perform(post("/api/progress")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request))
                        .with(csrf()))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.id").exists());

        verify(dailyProgressService, times(1)).createProgress(any(CreateDailyProgressRequest.class));
    }

    @Test
    public void testCreateProgressValidationError() throws Exception {
        CreateDailyProgressRequest request = new CreateDailyProgressRequest(); // empty
        when(dailyProgressService.createProgress(any(CreateDailyProgressRequest.class))).thenThrow(new ApiException(400, "Validation error"));

        mockMvc.perform(post("/api/progress")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request))
                        .with(csrf()))
                .andExpect(status().isBadRequest());

        verify(dailyProgressService, times(1)).createProgress(any(CreateDailyProgressRequest.class));
    }

    @Test
    public void testDeleteProgress() throws Exception {
        UUID id = UUID.randomUUID();
        doNothing().when(dailyProgressService).deleteProgress(id);

        mockMvc.perform(delete("/api/progress/{id}", id).with(csrf()))
                .andExpect(status().isOk());

        verify(dailyProgressService, times(1)).deleteProgress(id);
    }

    @Test
    public void testDeleteProgressNotFound() throws Exception {
        UUID id = UUID.randomUUID();
        doThrow(new ApiException(404, "Progress not found")).when(dailyProgressService).deleteProgress(id);

        mockMvc.perform(delete("/api/progress/{id}", id).with(csrf()))
                .andExpect(status().isNotFound());

        verify(dailyProgressService, times(1)).deleteProgress(id);
    }

    private DailyProgressDto createSampleProgressDto() {
        DailyProgressDto dto = new DailyProgressDto();
        dto.id = UUID.randomUUID();
        dto.studentId = UUID.randomUUID();
        dto.halaqaId = UUID.randomUUID();
        dto.date = LocalDate.now();
        dto.hifz = "Sample hifz";
        dto.revision = "Sample revision";
        dto.remarks = "Sample remarks";
        dto.rating = 5;
        return dto;
    }

    private CreateDailyProgressRequest createSampleCreateRequest() {
        CreateDailyProgressRequest request = new CreateDailyProgressRequest();
        request.studentId = UUID.randomUUID();
        request.halaqaId = UUID.randomUUID();
        request.date = LocalDate.now();
        request.hifz = "Sample hifz";
        request.revision = "Sample revision";
        request.remarks = "Sample remarks";
        request.rating = 5;
        return request;
    }
}