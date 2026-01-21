package com.zamzam.zamzamapi.config;

import org.springframework.stereotype.Component;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

@Component
public class RateLimitConfig {
    private final ConcurrentHashMap<String, AtomicInteger> requestCounts = new ConcurrentHashMap<>();
    private final ConcurrentHashMap<String, Long> lastResetTime = new ConcurrentHashMap<>();

    public boolean isAllowed(String key, int maxRequests, long timeWindowMillis) {
        long currentTime = System.currentTimeMillis();
        
        requestCounts.putIfAbsent(key, new AtomicInteger(0));
        lastResetTime.putIfAbsent(key, currentTime);

        long lastReset = lastResetTime.get(key);
        
        if (currentTime - lastReset > timeWindowMillis) {
            requestCounts.put(key, new AtomicInteger(0));
            lastResetTime.put(key, currentTime);
        }

        AtomicInteger count = requestCounts.get(key);
        return count.incrementAndGet() <= maxRequests;
    }
}