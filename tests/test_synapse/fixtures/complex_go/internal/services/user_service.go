package services

import (
	"context"
	"fmt"
	"regexp"
	"strings"
	"sync"
	"time"

	"complexapp/internal/models"
	"complexapp/internal/repository"

	"golang.org/x/crypto/bcrypt"
)

// UserService handles user-related business logic
type UserService struct {
	userRepo     repository.Repository[*models.User, string]
	cache        repository.Cache[string, *models.User]
	emailService EmailService
	validator    *UserValidator
	mu           sync.RWMutex
	onlineUsers  map[string]time.Time
}

type EmailService interface {
	SendEmail(ctx context.Context, to, subject, body string) error
	SendVerificationEmail(ctx context.Context, user *models.User, token string) error
	SendPasswordResetEmail(ctx context.Context, user *models.User, token string) error
}

type UserValidator struct {
	emailRegex    *regexp.Regexp
	usernameRegex *regexp.Regexp
}

func NewUserValidator() *UserValidator {
	return &UserValidator{
		emailRegex:    regexp.MustCompile(`^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$`),
		usernameRegex: regexp.MustCompile(`^[a-zA-Z0-9_]{3,20}$`),
	}
}

func (v *UserValidator) ValidateEmail(email string) error {
	if !v.emailRegex.MatchString(email) {
		return fmt.Errorf("invalid email format")
	}
	return nil
}

func (v *UserValidator) ValidateUsername(username string) error {
	if !v.usernameRegex.MatchString(username) {
		return fmt.Errorf("username must be 3-20 characters, alphanumeric and underscores only")
	}
	return nil
}

func (v *UserValidator) ValidatePassword(password string) error {
	if len(password) < 8 {
		return fmt.Errorf("password must be at least 8 characters")
	}
	if !regexp.MustCompile(`[A-Z]`).MatchString(password) {
		return fmt.Errorf("password must contain at least one uppercase letter")
	}
	if !regexp.MustCompile(`[a-z]`).MatchString(password) {
		return fmt.Errorf("password must contain at least one lowercase letter")
	}
	if !regexp.MustCompile(`[0-9]`).MatchString(password) {
		return fmt.Errorf("password must contain at least one digit")
	}
	return nil
}

func NewUserService(
	userRepo repository.Repository[*models.User, string],
	cache repository.Cache[string, *models.User],
	emailService EmailService,
) *UserService {
	return &UserService{
		userRepo:     userRepo,
		cache:        cache,
		emailService: emailService,
		validator:    NewUserValidator(),
		onlineUsers:  make(map[string]time.Time),
	}
}

// CreateUser creates a new user with validation and password hashing
func (s *UserService) CreateUser(ctx context.Context, user *models.User, password string) error {
	// Validate user data
	if err := s.validator.ValidateEmail(user.Email); err != nil {
		return fmt.Errorf("email validation failed: %w", err)
	}
	if err := s.validator.ValidateUsername(user.Username); err != nil {
		return fmt.Errorf("username validation failed: %w", err)
	}
	if err := s.validator.ValidatePassword(password); err != nil {
		return fmt.Errorf("password validation failed: %w", err)
	}

	// Check if user already exists
	existingUser, err := s.findByEmail(ctx, user.Email)
	if err == nil && existingUser != nil {
		return fmt.Errorf("user with email %s already exists", user.Email)
	}

	// Hash password
	hashedPassword, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return fmt.Errorf("failed to hash password: %w", err)
	}
	user.PasswordHash = string(hashedPassword)

	// Set default values
	user.Status = models.StatusPending
	user.Roles = []models.UserRole{models.RoleUser}
	user.CreatedAt = time.Now()
	user.UpdatedAt = time.Now()

	// Create user
	if err := s.userRepo.Create(ctx, user); err != nil {
		return fmt.Errorf("failed to create user: %w", err)
	}

	// Send verification email
	verificationToken := s.generateVerificationToken()
	if err := s.emailService.SendVerificationEmail(ctx, user, verificationToken); err != nil {
		// Log error but don't fail user creation
		fmt.Printf("Failed to send verification email: %v\n", err)
	}

	return nil
}

// AuthenticateUser authenticates a user with email and password
func (s *UserService) AuthenticateUser(ctx context.Context, email, password string) (*models.User, error) {
	user, err := s.findByEmail(ctx, email)
	if err != nil {
		return nil, fmt.Errorf("authentication failed: %w", err)
	}

	if user.Status != models.StatusActive {
		return nil, fmt.Errorf("user account is not active")
	}

	if err := bcrypt.CompareHashAndPassword([]byte(user.PasswordHash), []byte(password)); err != nil {
		return nil, fmt.Errorf("invalid password")
	}

	// Update last login time
	user.UpdatedAt = time.Now()
	if err := s.userRepo.Update(ctx, user); err != nil {
		fmt.Printf("Failed to update user last login: %v\n", err)
	}

	// Clear password hash before returning
	user.PasswordHash = ""

	return user, nil
}

// UpdateUserProfile updates user profile information
func (s *UserService) UpdateUserProfile(ctx context.Context, userID string, profile models.UserProfile) error {
	user, err := s.userRepo.GetByID(ctx, userID)
	if err != nil {
		return fmt.Errorf("user not found: %w", err)
	}

	// Validate profile data
	if profile.Email != "" && profile.Email != user.Email {
		if err := s.validator.ValidateEmail(profile.Email); err != nil {
			return fmt.Errorf("invalid email: %w", err)
		}
		// Check if email is already taken
		if existingUser, err := s.findByEmail(ctx, profile.Email); err == nil && existingUser.ID != userID {
			return fmt.Errorf("email already taken")
		}
		user.Email = profile.Email
	}

	user.Profile = profile
	user.UpdatedAt = time.Now()

	if err := s.userRepo.Update(ctx, user); err != nil {
		return fmt.Errorf("failed to update user: %w", err)
	}

	// Invalidate cache
	s.cache.Delete(userID)

	return nil
}

// ChangePassword changes user password
func (s *UserService) ChangePassword(ctx context.Context, userID, currentPassword, newPassword string) error {
	user, err := s.userRepo.GetByID(ctx, userID)
	if err != nil {
		return fmt.Errorf("user not found: %w", err)
	}

	// Verify current password
	if err := bcrypt.CompareHashAndPassword([]byte(user.PasswordHash), []byte(currentPassword)); err != nil {
		return fmt.Errorf("current password is incorrect")
	}

	// Validate new password
	if err := s.validator.ValidatePassword(newPassword); err != nil {
		return fmt.Errorf("new password validation failed: %w", err)
	}

	// Hash new password
	hashedPassword, err := bcrypt.GenerateFromPassword([]byte(newPassword), bcrypt.DefaultCost)
	if err != nil {
		return fmt.Errorf("failed to hash new password: %w", err)
	}

	user.PasswordHash = string(hashedPassword)
	user.UpdatedAt = time.Now()

	if err := s.userRepo.Update(ctx, user); err != nil {
		return fmt.Errorf("failed to update password: %w", err)
	}

	// Invalidate cache
	s.cache.Delete(userID)

	return nil
}

// AssignRole assigns a role to a user
func (s *UserService) AssignRole(ctx context.Context, userID string, role models.UserRole) error {
	user, err := s.userRepo.GetByID(ctx, userID)
	if err != nil {
		return fmt.Errorf("user not found: %w", err)
	}

	if !user.HasRole(role) {
		user.AddRole(role)
		user.UpdatedAt = time.Now()

		if err := s.userRepo.Update(ctx, user); err != nil {
			return fmt.Errorf("failed to assign role: %w", err)
		}

		s.cache.Delete(userID)
	}

	return nil
}

// RemoveRole removes a role from a user
func (s *UserService) RemoveRole(ctx context.Context, userID string, role models.UserRole) error {
	user, err := s.userRepo.GetByID(ctx, userID)
	if err != nil {
		return fmt.Errorf("user not found: %w", err)
	}

	if user.HasRole(role) {
		user.RemoveRole(role)
		user.UpdatedAt = time.Now()

		if err := s.userRepo.Update(ctx, user); err != nil {
			return fmt.Errorf("failed to remove role: %w", err)
		}

		s.cache.Delete(userID)
	}

	return nil
}

// SearchUsers searches for users based on criteria
func (s *UserService) SearchUsers(ctx context.Context, criteria UserSearchCriteria) ([]*models.User, error) {
	// This is a simplified implementation - in real app, you'd use a proper search index
	users, err := s.userRepo.List(ctx, criteria.Limit, criteria.Offset)
	if err != nil {
		return nil, fmt.Errorf("failed to search users: %w", err)
	}

	var results []*models.User
	for _, user := range users {
		if s.matchesCriteria(user, criteria) {
			// Clear sensitive data
			user.PasswordHash = ""
			results = append(results, user)
		}
	}

	return results, nil
}

type UserSearchCriteria struct {
	Query    string
	Status   models.UserStatus
	Role     models.UserRole
	MinAge   int
	MaxAge   int
	Location string
	Limit    int
	Offset   int
}

func (s *UserService) matchesCriteria(user *models.User, criteria UserSearchCriteria) bool {
	if criteria.Status != "" && user.Status != criteria.Status {
		return false
	}

	if criteria.Role != "" && !user.HasRole(criteria.Role) {
		return false
	}

	if criteria.Query != "" {
		query := strings.ToLower(criteria.Query)
		matches := strings.Contains(strings.ToLower(user.Username), query) ||
			strings.Contains(strings.ToLower(user.Email), query) ||
			strings.Contains(strings.ToLower(user.Profile.FirstName), query) ||
			strings.Contains(strings.ToLower(user.Profile.LastName), query)
		if !matches {
			return false
		}
	}

	return true
}

// MarkUserOnline marks a user as online
func (s *UserService) MarkUserOnline(userID string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.onlineUsers[userID] = time.Now()
}

// MarkUserOffline marks a user as offline
func (s *UserService) MarkUserOffline(userID string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.onlineUsers, userID)
}

// GetOnlineUsers returns currently online users
func (s *UserService) GetOnlineUsers() []string {
	s.mu.RLock()
	defer s.mu.RUnlock()

	var users []string
	for userID, lastSeen := range s.onlineUsers {
		if time.Since(lastSeen) < 5*time.Minute {
			users = append(users, userID)
		}
	}
	return users
}

// CleanupOnlineUsers removes stale online user entries
func (s *UserService) CleanupOnlineUsers() {
	s.mu.Lock()
	defer s.mu.Unlock()

	for userID, lastSeen := range s.onlineUsers {
		if time.Since(lastSeen) > 10*time.Minute {
			delete(s.onlineUsers, userID)
		}
	}
}

// Helper methods
func (s *UserService) findByEmail(ctx context.Context, email string) (*models.User, error) {
	// Check cache first
	if user, found := s.cache.Get(email); found {
		return user, nil
	}

	// In real implementation, you'd have a repository method for this
	// For now, we'll search through all users
	users, err := s.userRepo.List(ctx, 1000, 0)
	if err != nil {
		return nil, err
	}

	for _, user := range users {
		if user.Email == email {
			s.cache.Set(user.ID, user, 5*time.Minute)
			return user, nil
		}
	}

	return nil, fmt.Errorf("user not found")
}

func (s *UserService) generateVerificationToken() string {
	return fmt.Sprintf("%d", time.Now().UnixNano())
}
