package com.zamzam.zamzamapi.controller;

import com.zamzam.zamzamapi.dto.*;
import com.zamzam.zamzamapi.service.HalaqaService;
import com.zamzam.zamzamapi.exception.ApiException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
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

    @GetMapping("/organization/{id}")
    public List<HalaqaDto> getOrganizationHalaqat(@PathVariable UUID id) {
        return halaqaService.getOrganizationHalaqat(id);
    }

    @GetMapping("/{id}/members")
    public List<HalaqaMemberDto> getHalaqaMembers(@PathVariable UUID id) {
        return halaqaService.getHalaqaMembers(id);
    }

    @PostMapping("/{halaqaId}/member")
    public ResponseEntity<?> addHalaqaMember(@PathVariable UUID halaqaId, @RequestBody AddHalaqaMemberRequest request) {
        try {
        HalaqaMemberDto member = halaqaService.addHalaqaMember(halaqaId, request);
        return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(member);
        } catch (ApiException e) {
            return ResponseEntity.status(e.getStatusCode()).body(e.getMessage());
        }
    }
    @PostMapping
    public ResponseEntity<?> createHalaqa(@RequestBody CreateHalaqaRequest request) {
        try {
        HalaqaDto halaqa = halaqaService.createHalaqa(request);
        return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(halaqa);
        } catch (ApiException e) {
            return ResponseEntity.status(e.getStatusCode()).body(e.getMessage());
        }
    }

    @DeleteMapping("/{id}")
    public void deleteHalaqa(@PathVariable UUID id) {
        halaqaService.deleteHalaqa(id);
    }
}

