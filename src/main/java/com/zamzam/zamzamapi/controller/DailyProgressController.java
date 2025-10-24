package com.zamzam.zamzamapi.controller;

import com.zamzam.zamzamapi.dto.*;
import com.zamzam.zamzamapi.service.DailyProgressService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;
import java.util.*;

@RestController
@RequestMapping("/api/progress")
public class DailyProgressController {
    @Autowired
    private DailyProgressService dailyProgressService;

    @GetMapping
    public List<DailyProgressDto> getAllProgress() {
        return dailyProgressService.getAllProgress();
    }

    @GetMapping("/{id}")
    public DailyProgressDto getProgress(@PathVariable UUID id) {
        return dailyProgressService.getProgressById(id);
    }

    @PostMapping
    public DailyProgressDto createProgress(@RequestBody CreateDailyProgressRequest request) {
        return dailyProgressService.createProgress(request);
    }

    @DeleteMapping("/{id}")
    public void deleteProgress(@PathVariable UUID id) {
        dailyProgressService.deleteProgress(id);
    }
}
