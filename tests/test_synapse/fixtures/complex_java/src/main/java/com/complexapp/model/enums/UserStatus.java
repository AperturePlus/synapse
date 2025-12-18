package com.complexapp.model.enums;

public enum UserStatus {
    PENDING("Account pending verification"),
    ACTIVE("Account is active"),
    INACTIVE("Account is inactive"),
    SUSPENDED("Account is suspended"),
    LOCKED("Account is locked due to security"),
    DELETED("Account is marked as deleted");

    private final String description;

    UserStatus(String description) {
        this.description = description;
    }

    public String getDescription() {
        return description;
    }

    public boolean isActive() {
        return this == ACTIVE;
    }

    public boolean canLogin() {
        return this == ACTIVE || this == PENDING;
    }
}