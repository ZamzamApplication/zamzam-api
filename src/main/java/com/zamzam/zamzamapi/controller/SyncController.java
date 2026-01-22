package com.zamzam.zamzamapi.controller;

import com.zamzam.zamzamapi.entity.User;
import com.zamzam.zamzamapi.repository.UserRepository;
import com.zamzam.zamzamapi.service.SyncService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.Map;
import java.util.UUID;

@RestController
@RequestMapping("/api/sync")
public class SyncController {

    @Autowired
    private SyncService syncService;

    @Autowired
    private UserRepository userRepository;

    @GetMapping
    public ResponseEntity<Map<String, Object>> getSyncData(
            @RequestParam("since") String sinceStr,
            Authentication authentication) {
        LocalDateTime since = LocalDateTime.parse(sinceStr);
        User user = userRepository.findByEmail(authentication.getName());
        UUID userId = user.getId();
        Map<String, Object> data = syncService.getSyncData(since, userId);
        return ResponseEntity.ok(data);
    }

    @PostMapping
    public ResponseEntity<String> syncData(@RequestBody Map<String, Object> syncData) {
        // Implement sync logic
        return ResponseEntity.ok("Sync successful");
    }
}