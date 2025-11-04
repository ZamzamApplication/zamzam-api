package com.zamzam.zamzamapi.controller;

import com.zamzam.zamzamapi.dto.*;
import com.zamzam.zamzamapi.service.HalaqaService;
import com.zamzam.zamzamapi.exception.ApiException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
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
    public ResponseEntity<?> createHalaqa(@RequestBody CreateHalaqaRequest request) {
        try {
            HalaqaDto halaqa = halaqaService.createHalaqa(request);
            return ResponseEntity.ok(halaqa);
        } catch (ApiException e) {
            return ResponseEntity.status(e.getStatusCode()).body(e.getMessage());
        }
    }

    @DeleteMapping("/{id}")
    public void deleteHalaqa(@PathVariable UUID id) {
        halaqaService.deleteHalaqa(id);
    }
}

