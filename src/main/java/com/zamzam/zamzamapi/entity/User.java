package com.zamzam.zamzamapi.entity;

import jakarta.persistence.*;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.*;

@Entity
@Table(name = "users")
@Data
public class User {
    @Id
    @GeneratedValue
    private UUID id;

    private String name;
    @Column(unique = true)
    private String email;
    private String passwordHash;

    private Boolean isAdmin;

    private LocalDateTime createdAt;

    public enum Role {
        SYSTEM_ADMIN, ORG_ADMIN, TEACHER, STUDENT, PARENT
    }

    @OneToMany(mappedBy = "user")
    private Set<OrganizationMembership> memberships = new HashSet<>();

    @ManyToMany
    @JoinTable(
            name = "parents",
            joinColumns = @JoinColumn(name = "parent_id"),
            inverseJoinColumns = @JoinColumn(name = "student_id")
    )
    private Set<User> children = new HashSet<>();

    @ManyToMany(mappedBy = "children")
    private Set<User> parents = new HashSet<>();

    @ManyToMany(mappedBy = "students")
    private Set<Halaqa> halaqat = new HashSet<>();

}
