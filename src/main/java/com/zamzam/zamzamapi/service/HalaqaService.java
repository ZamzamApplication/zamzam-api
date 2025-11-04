package com.zamzam.zamzamapi.service;

import com.zamzam.zamzamapi.dto.*;
import com.zamzam.zamzamapi.entity.Halaqa;
import com.zamzam.zamzamapi.entity.Organization;
import com.zamzam.zamzamapi.entity.User;
import com.zamzam.zamzamapi.repository.HalaqaRepository;
import com.zamzam.zamzamapi.repository.OrganizationRepository;
import com.zamzam.zamzamapi.repository.UserRepository;
import com.zamzam.zamzamapi.exception.ApiException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import java.util.*;
import java.util.stream.Collectors;
import java.time.LocalDateTime;

@Service
public class HalaqaService {
    @Autowired
    private HalaqaRepository halaqaRepository;
    @Autowired
    private OrganizationRepository organizationRepository;
    @Autowired
    private UserRepository userRepository;

    private HalaqaDto toDto(Halaqa h) {
        HalaqaDto dto = new HalaqaDto();
        dto.id = h.getId();
        dto.name = h.getName();
        dto.organizationId = h.getOrganization() != null ? h.getOrganization().getId() : null;
        dto.teacherId = h.getTeacher() != null ? h.getTeacher().getId() : null;
        dto.createdAt = h.getCreatedAt();
        dto.studentIds = h.getStudents() != null ? h.getStudents().stream().map(User::getId).collect(Collectors.toSet()) : Set.of();
        return dto;
    }

    public List<HalaqaDto> getAllHalaqat() {
        return halaqaRepository.findAll().stream().map(this::toDto).collect(Collectors.toList());
    }

    public HalaqaDto getHalaqaById(UUID id) {
        return halaqaRepository.findById(id).map(this::toDto).orElse(null);
    }

    public List<HalaqaMemberDto> getHalaqaMembers(UUID id) {
        Halaqa h = halaqaRepository.findByIdWithMembers(id).orElse(null);
        if (h == null) {
            throw new ApiException(404, "Halaqa with id '" + id + "' not found.");
        }
        List<HalaqaMemberDto> members = new ArrayList<>();
        if (h.getTeacher() != null) {
            HalaqaMemberDto teacherDto = new HalaqaMemberDto();
            teacherDto.id = h.getTeacher().getId();
            teacherDto.name = h.getTeacher().getName();
            teacherDto.role = "TEACHER";
            members.add(teacherDto);
        }
        if (h.getStudents() != null) {
            for (User student : h.getStudents()) {
                HalaqaMemberDto studentDto = new HalaqaMemberDto();
                studentDto.id = student.getId();
                studentDto.name = student.getName();
                studentDto.role = "STUDENT";
                members.add(studentDto);
            }
        }
        return members;
    }

    public HalaqaMemberDto addHalaqaMember(UUID halaqaId, AddHalaqaMemberRequest request) {
        Halaqa h = halaqaRepository.findById(halaqaId).orElse(null);
        if (h == null) {
            throw new ApiException(404, "Halaqa with id '" + halaqaId + "' not found.");
        }
        User user = userRepository.findById(request.userId).orElse(null);
        if (user == null) {
            throw new ApiException(404, "User with id '" + request.userId+ "' not found.");
        }
        if (request.role.equals("STUDENT")) {
            if (h.getStudents() == null) {
                h.setStudents(new HashSet<>());
            }
            if (h.getStudents().contains(user)) {
                throw new ApiException(400, "User with id '" + request.userId+ "' is already a student in this halaqa.");
            }
            h.getStudents().add(user);
        } else if (request.role.equals("TEACHER")) {
            h.setTeacher(user);
        } else {
            throw new ApiException(400, "Invalid role '" + request.role + "'. Must be 'STUDENT' or 'TEACHER'.");
        }
        halaqaRepository.save(h);
        HalaqaMemberDto memberDto = new HalaqaMemberDto();
        memberDto.id = user.getId();
        memberDto.name = user.getName();
        memberDto.role = request.role;
        return memberDto;
    }

    public HalaqaDto createHalaqa(CreateHalaqaRequest request) {
        if (request.organizationId == null) {
            throw new ApiException(400, "Organization ID must be provided.");
        }
        if (request.teacherId == null) {
            throw new ApiException(400, "Teacher ID must be provided.");
        }
        if (halaqaRepository.findByNameAndOrganizationId(request.name, request.organizationId).isPresent()) {
            throw new ApiException(400, "Halaqa with name '" + request.name + "' already exists in the organization.");
        }
        Halaqa h = new Halaqa();
        h.setName(request.name);
        h.setCreatedAt(LocalDateTime.now());
        userRepository.findById(request.teacherId).ifPresent(h::setTeacher);
        organizationRepository.findById(request.organizationId).ifPresent(h::setOrganization);
        h = halaqaRepository.save(h);
        return toDto(h);
    }

    public List<HalaqaDto> getOrganizationHalaqat(UUID organizationId) {
        return halaqaRepository.findByOrganizationId(organizationId).stream().map(this::toDto).collect(Collectors.toList());
    }

    public void deleteHalaqa(UUID id) {
        halaqaRepository.deleteById(id);
    }

}

