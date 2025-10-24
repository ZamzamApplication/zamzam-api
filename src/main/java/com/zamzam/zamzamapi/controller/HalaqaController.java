package com.zamzam.zamzamapi.controller;

import com.zamzam.zamzamapi.dto.*;
import com.zamzam.zamzamapi.service.HalaqaService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;
import java.util.*;

@RestController
@RequestMapping("/api/halaqat")
public class HalaqaController {
    @Autowired
    private HalaqaService halaqaService;

    @GetMapping
    public List<HalaqaDto> getAllHalaqat() {
        return halaqaService.getAllHalaqat();
    }

    @GetMapping("/{id}")
    public HalaqaDto getHalaqa(@PathVariable UUID id) {
        return halaqaService.getHalaqaById(id);
    }

    @PostMapping
    public HalaqaDto createHalaqa(@RequestBody CreateHalaqaRequest request) {
        return halaqaService.createHalaqa(request);
    }

    @DeleteMapping("/{id}")
    public void deleteHalaqa(@PathVariable UUID id) {
        halaqaService.deleteHalaqa(id);
    }
}

