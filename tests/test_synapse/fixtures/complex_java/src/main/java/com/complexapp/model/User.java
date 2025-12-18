package com.complexapp.model;

import com.complexapp.model.enums.UserRole;
import com.complexapp.model.enums.UserStatus;
import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.LocalDate;
import java.util.*;
import java.util.stream.Collectors;

public class User extends BaseEntity<UUID> implements Auditable, PermissionHolder {
    
    @JsonProperty("username")
    private String username;
    
    @JsonProperty("email")
    private String email;
    
    @JsonIgnore
    private String passwordHash;
    
    @JsonProperty("profile")
    private UserProfile profile;
    
    @JsonProperty("roles")
    private Set<UserRole> roles;
    
    @JsonProperty("preferences")
    private UserPreferences preferences;
    
    @JsonProperty("status")
    private UserStatus status;
    
    @JsonProperty("permissions")
    private Set<String> customPermissions;
    
    @JsonProperty("last_login")
    private LocalDateTime lastLogin;
    
    @JsonProperty("login_attempts")
    private int loginAttempts;
    
    @JsonProperty("locked_until")
    private LocalDateTime lockedUntil;
    
    @JsonProperty("two_factor_enabled")
    private boolean twoFactorEnabled;
    
    @JsonProperty("two_factor_secret")
    private String twoFactorSecret;
    
    @JsonProperty("api_key")
    private String apiKey;
    
    @JsonProperty("email_verified")
    private boolean emailVerified;
    
    @JsonProperty("phone_verified")
    private boolean phoneVerified;

    public User() {
        super();
        this.roles = new HashSet<>();
        this.customPermissions = new HashSet<>();
        this.preferences = new UserPreferences();
        this.profile = new UserProfile();
        this.status = UserStatus.PENDING;
        this.loginAttempts = 0;
        this.twoFactorEnabled = false;
        this.emailVerified = false;
        this.phoneVerified = false;
    }

    @Override
    public void validate() throws ValidationException {
        List<String> errors = new ArrayList<>();

        if (username == null || username.trim().isEmpty()) {
            errors.add("Username is required");
        } else if (username.length() < 3 || username.length() > 50) {
            errors.add("Username must be between 3 and 50 characters");
        } else if (!username.matches("^[a-zA-Z0-9_]+$")) {
            errors.add("Username can only contain alphanumeric characters and underscores");
        }

        if (email == null || email.trim().isEmpty()) {
            errors.add("Email is required");
        } else if (!email.matches("^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$")) {
            errors.add("Invalid email format");
        }

        if (roles == null || roles.isEmpty()) {
            errors.add("At least one role is required");
        }

        if (profile != null) {
            try {
                profile.validate();
            } catch (ValidationException e) {
                errors.addAll(Arrays.asList(e.getErrors()));
            }
        }

        if (!errors.isEmpty()) {
            throw new ValidationException(errors);
        }
    }

    public void addRole(UserRole role) {
        this.roles.add(role);
        updateTimestamp();
    }

    public void removeRole(UserRole role) {
        this.roles.remove(role);
        updateTimestamp();
    }

    public boolean hasRole(UserRole role) {
        return roles.contains(role);
    }

    public boolean hasAnyRole(UserRole... roles) {
        return Arrays.stream(roles).anyMatch(this.roles::contains);
    }

    public void addPermission(String permission) {
        this.customPermissions.add(permission);
        updateTimestamp();
    }

    public void removePermission(String permission) {
        this.customPermissions.remove(permission);
        updateTimestamp();
    }

    public boolean hasPermission(String permission) {
        // Check custom permissions first
        if (customPermissions.contains(permission)) {
            return true;
        }

        // Check role-based permissions
        return roles.stream()
                .flatMap(role -> role.getPermissions().stream())
                .anyMatch(p -> p.equals(permission) || p.endsWith("*") && permission.startsWith(p.substring(0, p.length() - 1)));
    }

    public void recordLoginSuccess() {
        this.lastLogin = LocalDateTime.now();
        this.loginAttempts = 0;
        this.lockedUntil = null;
        updateTimestamp();
    }

    public void recordLoginFailure() {
        this.loginAttempts++;
        if (loginAttempts >= 5) {
            this.lockedUntil = LocalDateTime.now().plusHours(1);
        }
        updateTimestamp();
    }

    public boolean isAccountLocked() {
        if (lockedUntil == null) {
            return false;
        }
        if (lockedUntil.isBefore(LocalDateTime.now())) {
            lockedUntil = null;
            loginAttempts = 0;
            return false;
        }
        return true;
    }

    public void generateApiKey() {
        this.apiKey = UUID.randomUUID().toString().replace("-", "") + UUID.randomUUID().toString().replace("-", "");
        updateTimestamp();
    }

    public void revokeApiKey() {
        this.apiKey = null;
        updateTimestamp();
    }

    public boolean isActive() {
        return status == UserStatus.ACTIVE && !isDeleted() && !isAccountLocked();
    }

    public int getAge() {
        if (profile == null || profile.getBirthDate() == null) {
            return 0;
        }
        return LocalDate.now().getYear() - profile.getBirthDate().getYear();
    }

    public Set<String> getAllPermissions() {
        Set<String> allPermissions = new HashSet<>(customPermissions);
        roles.stream()
                .flatMap(role -> role.getPermissions().stream())
                .forEach(allPermissions::add);
        return Collections.unmodifiableSet(allPermissions);
    }

    // Getters and setters
    public String getUsername() { return username; }
    public void setUsername(String username) { this.username = username; }
    public String getEmail() { return email; }
    public void setEmail(String email) { this.email = email; }
    public String getPasswordHash() { return passwordHash; }
    public void setPasswordHash(String passwordHash) { this.passwordHash = passwordHash; }
    public UserProfile getProfile() { return profile; }
    public void setProfile(UserProfile profile) { this.profile = profile; }
    public Set<UserRole> getRoles() { return Collections.unmodifiableSet(roles); }
    public void setRoles(Set<UserRole> roles) { this.roles = new HashSet<>(roles); }
    public UserPreferences getPreferences() { return preferences; }
    public void setPreferences(UserPreferences preferences) { this.preferences = preferences; }
    public UserStatus getStatus() { return status; }
    public void setStatus(UserStatus status) { this.status = status; }
    public LocalDateTime getLastLogin() { return lastLogin; }
    public void setLastLogin(LocalDateTime lastLogin) { this.lastLogin = lastLogin; }
    public int getLoginAttempts() { return loginAttempts; }
    public void setLoginAttempts(int loginAttempts) { this.loginAttempts = loginAttempts; }
    public LocalDateTime getLockedUntil() { return lockedUntil; }
    public void setLockedUntil(LocalDateTime lockedUntil) { this.lockedUntil = lockedUntil; }
    public boolean isTwoFactorEnabled() { return twoFactorEnabled; }
    public void setTwoFactorEnabled(boolean twoFactorEnabled) { this.twoFactorEnabled = twoFactorEnabled; }
    public String getTwoFactorSecret() { return twoFactorSecret; }
    public void setTwoFactorSecret(String twoFactorSecret) { this.twoFactorSecret = twoFactorSecret; }
    public String getApiKey() { return apiKey; }
    public boolean isEmailVerified() { return emailVerified; }
    public void setEmailVerified(boolean emailVerified) { this.emailVerified = emailVerified; }
    public boolean isPhoneVerified() { return phoneVerified; }
    public void setPhoneVerified(boolean phoneVerified) { this.phoneVerified = phoneVerified; }
}