package com.complexapp.model;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;

public class UserProfile implements Validatable {
    
    @JsonProperty("first_name")
    private String firstName;
    
    @JsonProperty("last_name")
    private String lastName;
    
    @JsonProperty("avatar_url")
    private String avatarUrl;
    
    @JsonProperty("bio")
    private String bio;
    
    @JsonProperty("birth_date")
    private LocalDate birthDate;
    
    @JsonProperty("location")
    private String location;
    
    @JsonProperty("website")
    private String website;
    
    @JsonProperty("phone")
    private String phone;
    
    @JsonProperty("social_links")
    private Map<String, String> socialLinks;
    
    @JsonProperty("preferences")
    private Map<String, Object> preferences;

    public UserProfile() {
        this.socialLinks = new HashMap<>();
        this.preferences = new HashMap<>();
    }

    @Override
    public void validate() throws ValidationException {
        if (firstName != null && firstName.length() > 100) {
            throw new ValidationException("First name cannot exceed 100 characters");
        }
        if (lastName != null && lastName.length() > 100) {
            throw new ValidationException("Last name cannot exceed 100 characters");
        }
        if (bio != null && bio.length() > 1000) {
            throw new ValidationException("Bio cannot exceed 1000 characters");
        }
        if (website != null && !website.matches("^https?://.*")) {
            throw new ValidationException("Website must be a valid URL");
        }
        if (phone != null && !phone.matches("^\\+?[1-9]\\d{1,14}$")) {
            throw new ValidationException("Phone number must be in international format");
        }
    }

    public String getFullName() {
        if (firstName == null && lastName == null) {
            return null;
        }
        if (firstName == null) {
            return lastName;
        }
        if (lastName == null) {
            return firstName;
        }
        return firstName + " " + lastName;
    }

    public int getAge() {
        if (birthDate == null) {
            return 0;
        }
        return LocalDate.now().getYear() - birthDate.getYear();
    }

    public void addSocialLink(String platform, String url) {
        socialLinks.put(platform, url);
    }

    public void removeSocialLink(String platform) {
        socialLinks.remove(platform);
    }

    public void setPreference(String key, Object value) {
        preferences.put(key, value);
    }

    public Object getPreference(String key) {
        return preferences.get(key);
    }

    // Getters and setters
    public String getFirstName() { return firstName; }
    public void setFirstName(String firstName) { this.firstName = firstName; }
    public String getLastName() { return lastName; }
    public void setLastName(String lastName) { this.lastName = lastName; }
    public String getAvatarUrl() { return avatarUrl; }
    public void setAvatarUrl(String avatarUrl) { this.avatarUrl = avatarUrl; }
    public String getBio() { return bio; }
    public void setBio(String bio) { this.bio = bio; }
    public LocalDate getBirthDate() { return birthDate; }
    public void setBirthDate(LocalDate birthDate) { this.birthDate = birthDate; }
    public String getLocation() { return location; }
    public void setLocation(String location) { this.location = location; }
    public String getWebsite() { return website; }
    public void setWebsite(String website) { this.website = website; }
    public String getPhone() { return phone; }
    public void setPhone(String phone) { this.phone = phone; }
    public Map<String, String> getSocialLinks() { return socialLinks; }
    public void setSocialLinks(Map<String, String> socialLinks) { this.socialLinks = socialLinks; }
    public Map<String, Object> getPreferences() { return preferences; }
    public void setPreferences(Map<String, Object> preferences) { this.preferences = preferences; }
}