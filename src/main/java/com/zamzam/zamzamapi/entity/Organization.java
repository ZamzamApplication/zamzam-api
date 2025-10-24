package com.zamzam.zamzamapi.entity;

import jakarta.persistence.*;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.*;

@Entity
@Table(name = "organizations")
@Data
public class Organization {
    @Id
    @GeneratedValue
    private UUID id;

    private String name;
    @ManyToOne
    private User createdBy;

    private LocalDateTime createdAt;

    @OneToMany(mappedBy = "organization")
    private Set<OrganizationMembership> members = new HashSet<>();

    @OneToMany(mappedBy = "organization")
    private Set<Halaqa> halaqat = new HashSet<>();

    // Getters and setters
}