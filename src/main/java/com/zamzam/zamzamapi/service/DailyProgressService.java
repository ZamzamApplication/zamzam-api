package com.zamzam.zamzamapi.service;

import com.zamzam.zamzamapi.dto.*;
import com.zamzam.zamzamapi.entity.DailyProgress;
import com.zamzam.zamzamapi.entity.Halaqa;
import com.zamzam.zamzamapi.entity.User;
import com.zamzam.zamzamapi.repository.DailyProgressRepository;
import com.zamzam.zamzamapi.repository.HalaqaRepository;
import com.zamzam.zamzamapi.repository.UserRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import java.util.*;
import java.util.stream.Collectors;


@Service
public class DailyProgressService {
    @Autowired
    private DailyProgressRepository dailyProgressRepository;
    @Autowired
    private UserRepository userRepository;
    @Autowired
    private HalaqaRepository halaqaRepository;

    private DailyProgressDto toDto(DailyProgress dp) {
        DailyProgressDto dto = new DailyProgressDto();
        dto.id = dp.getId();
        dto.studentId = dp.getStudent() != null ? dp.getStudent().getId() : null;
        dto.halaqaId = dp.getHalaqa() != null ? dp.getHalaqa().getId() : null;
        dto.date = dp.getDate();
        dto.hifz = dp.getHifz();
        dto.revision = dp.getRevision();
        dto.remarks = dp.getRemarks();
        dto.rating = dp.getRating();
        return dto;
    }

    public List<DailyProgressDto> getAllProgress() {
        return dailyProgressRepository.findAll().stream().map(this::toDto).collect(Collectors.toList());
    }

    public DailyProgressDto getProgressById(UUID id) {
        return dailyProgressRepository.findById(id).map(this::toDto).orElse(null);
    }

    public DailyProgressDto createProgress(CreateDailyProgressRequest request) {
        DailyProgress dp = new DailyProgress();
        if (request.studentId == null) {
            throw new RuntimeException("Student ID is required");
        }
        if (request.halaqaId == null) {
            throw new RuntimeException("Halaqa ID is required");
        }
        userRepository.findById(request.studentId).ifPresent(dp::setStudent);
        halaqaRepository.findById(request.halaqaId).ifPresent(dp::setHalaqa);
        dp.setDate(request.date);
        dp.setHifz(request.hifz);
        dp.setRevision(request.revision);
        dp.setRemarks(request.remarks);
        dp.setRating(request.rating);
        dp = dailyProgressRepository.save(dp);
        return toDto(dp);
    }

    public DailyProgressDto updateProgress(UUID id, UpdateDailyProgressRequest request) {
        DailyProgress dp = dailyProgressRepository.findById(id).orElseThrow(() -> new RuntimeException("Progress not found"));
        if (request.getHifz() != null) {
            dp.setHifz(request.getHifz());
        }
        if (request.getRevision() != null) {
            dp.setRevision(request.getRevision());
        }
        if (request.getRemarks() != null) {
            dp.setRemarks(request.getRemarks());
        }
        if (request.getRating() != null) {
            dp.setRating(request.getRating());
        }
        dailyProgressRepository.save(dp);
        return toDto(dp);
    }

    public void deleteProgress(UUID id) {
        dailyProgressRepository.deleteById(id);
    }

    public List<DailyProgressDto> getProgressByHalaqaId(UUID halaqaId, Integer limit) {
        List<DailyProgress> progresses = dailyProgressRepository.findByHalaqaId(halaqaId);
        if (limit == null) {
            return progresses.stream().map(this::toDto).collect(Collectors.toList());
        }
        // Group by student and take the last 'limit' per student
        Map<UUID, List<DailyProgress>> grouped = progresses.stream()
                .filter(dp -> dp.getStudent() != null)
                .collect(Collectors.groupingBy(dp -> dp.getStudent().getId()));
        List<DailyProgress> limited = new ArrayList<>();
        for (List<DailyProgress> studentProgress : grouped.values()) {
            studentProgress.sort((a, b) -> b.getDate().compareTo(a.getDate())); // Descending date
            limited.addAll(studentProgress.subList(0, Math.min(limit, studentProgress.size())));
        }
        return limited.stream().map(this::toDto).collect(Collectors.toList());
    }

    public List<DailyProgressDto> getProgressByStudentId(UUID studentId) {
        return dailyProgressRepository.findByStudentId(studentId).stream().map(this::toDto).collect(Collectors.toList());
    }
}
