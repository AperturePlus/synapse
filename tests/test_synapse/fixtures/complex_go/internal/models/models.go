package models

import (
	"fmt"
	"time"
)

// BaseModel provides common fields for all models
type BaseModel struct {
	ID        string     `json:"id"`
	CreatedAt time.Time  `json:"created_at"`
	UpdatedAt time.Time  `json:"updated_at"`
	DeletedAt *time.Time `json:"deleted_at,omitempty"`
}

// User represents a user in the system
type User struct {
	BaseModel
	Username     string                 `json:"username"`
	Email        string                 `json:"email"`
	PasswordHash string                 `json:"-"`
	Profile      UserProfile            `json:"profile"`
	Roles        []UserRole             `json:"roles"`
	Preferences  UserPreferences        `json:"preferences"`
	Status       UserStatus             `json:"status"`
	Metadata     map[string]interface{} `json:"metadata"`
}

type UserProfile struct {
	FirstName   string            `json:"first_name"`
	LastName    string            `json:"last_name"`
	AvatarURL   string            `json:"avatar_url"`
	Bio         string            `json:"bio"`
	BirthDate   *time.Time        `json:"birth_date,omitempty"`
	Location    string            `json:"location"`
	Website     string            `json:"website"`
	SocialLinks map[string]string `json:"social_links"`
}

type UserRole string

const (
	RoleAdmin     UserRole = "admin"
	RoleUser      UserRole = "user"
	RoleModerator UserRole = "moderator"
	RoleGuest     UserRole = "guest"
)

type UserPreferences struct {
	Theme              string          `json:"theme"`
	Language           string          `json:"language"`
	EmailNotifications bool            `json:"email_notifications"`
	PushNotifications  bool            `json:"push_notifications"`
	PrivacySettings    map[string]bool `json:"privacy_settings"`
}

type UserStatus string

const (
	StatusActive    UserStatus = "active"
	StatusInactive  UserStatus = "inactive"
	StatusSuspended UserStatus = "suspended"
	StatusPending   UserStatus = "pending"
)

// Product represents a product in the e-commerce system
type Product struct {
	BaseModel
	SKU            string                 `json:"sku"`
	Name           string                 `json:"name"`
	Description    string                 `json:"description"`
	Price          float64                `json:"price"`
	Currency       string                 `json:"currency"`
	Category       ProductCategory        `json:"category"`
	Inventory      ProductInventory       `json:"inventory"`
	Images         []ProductImage         `json:"images"`
	Specifications map[string]interface{} `json:"specifications"`
	Reviews        []ProductReview        `json:"reviews"`
	Tags           []string               `json:"tags"`
	Vendor         *Vendor                `json:"vendor,omitempty"`
}

type ProductCategory struct {
	ID          string   `json:"id"`
	Name        string   `json:"name"`
	Description string   `json:"description"`
	ParentID    *string  `json:"parent_id,omitempty"`
	Path        string   `json:"path"`
	Attributes  []string `json:"attributes"`
}

type ProductInventory struct {
	Quantity        int       `json:"quantity"`
	Reserved        int       `json:"reserved"`
	Available       int       `json:"available"`
	ReorderPoint    int       `json:"reorder_point"`
	ReorderQuantity int       `json:"reorder_quantity"`
	WarehouseID     string    `json:"warehouse_id"`
	LastRestocked   time.Time `json:"last_restocked"`
}

type ProductImage struct {
	ID        string `json:"id"`
	URL       string `json:"url"`
	AltText   string `json:"alt_text"`
	Position  int    `json:"position"`
	IsPrimary bool   `json:"is_primary"`
}

type ProductReview struct {
	ID        string    `json:"id"`
	UserID    string    `json:"user_id"`
	Rating    int       `json:"rating"`
	Title     string    `json:"title"`
	Content   string    `json:"content"`
	Verified  bool      `json:"verified"`
	CreatedAt time.Time `json:"created_at"`
	Helpful   int       `json:"helpful"`
}

// Order represents a customer order
type Order struct {
	BaseModel
	OrderNumber     string                 `json:"order_number"`
	UserID          string                 `json:"user_id"`
	Status          OrderStatus            `json:"status"`
	Subtotal        float64                `json:"subtotal"`
	Tax             float64                `json:"tax"`
	Shipping        float64                `json:"shipping"`
	Discount        float64                `json:"discount"`
	Total           float64                `json:"total"`
	Currency        string                 `json:"currency"`
	Items           []OrderItem            `json:"items"`
	ShippingAddress Address                `json:"shipping_address"`
	BillingAddress  Address                `json:"billing_address"`
	PaymentMethod   PaymentMethod          `json:"payment_method"`
	TrackingInfo    *TrackingInfo          `json:"tracking_info,omitempty"`
	Notes           string                 `json:"notes"`
	Metadata        map[string]interface{} `json:"metadata"`
}

type OrderStatus string

const (
	OrderStatusPending    OrderStatus = "pending"
	OrderStatusProcessing OrderStatus = "processing"
	OrderStatusShipped    OrderStatus = "shipped"
	OrderStatusDelivered  OrderStatus = "delivered"
	OrderStatusCancelled  OrderStatus = "cancelled"
	OrderStatusRefunded   OrderStatus = "refunded"
)

type OrderItem struct {
	ID        string                 `json:"id"`
	ProductID string                 `json:"product_id"`
	SKU       string                 `json:"sku"`
	Name      string                 `json:"name"`
	Quantity  int                    `json:"quantity"`
	UnitPrice float64                `json:"unit_price"`
	Discount  float64                `json:"discount"`
	Total     float64                `json:"total"`
	Metadata  map[string]interface{} `json:"metadata"`
}

type Address struct {
	FirstName  string `json:"first_name"`
	LastName   string `json:"last_name"`
	Company    string `json:"company"`
	Street     string `json:"street"`
	City       string `json:"city"`
	State      string `json:"state"`
	PostalCode string `json:"postal_code"`
	Country    string `json:"country"`
	Phone      string `json:"phone"`
	Email      string `json:"email"`
}

type PaymentMethod struct {
	Type        string                 `json:"type"`
	Provider    string                 `json:"provider"`
	LastFour    string                 `json:"last_four,omitempty"`
	ExpiryMonth int                    `json:"expiry_month,omitempty"`
	ExpiryYear  int                    `json:"expiry_year,omitempty"`
	Details     map[string]interface{} `json:"details"`
}

type TrackingInfo struct {
	Carrier        string    `json:"carrier"`
	TrackingNumber string    `json:"tracking_number"`
	URL            string    `json:"url"`
	Status         string    `json:"status"`
	UpdatedAt      time.Time `json:"updated_at"`
}

// Vendor represents a product vendor
type Vendor struct {
	BaseModel
	Name           string       `json:"name"`
	Email          string       `json:"email"`
	Phone          string       `json:"phone"`
	Address        Address      `json:"address"`
	TaxID          string       `json:"tax_id"`
	Status         VendorStatus `json:"status"`
	CommissionRate float64      `json:"commission_rate"`
	PayoutSchedule string       `json:"payout_schedule"`
}

type VendorStatus string

const (
	VendorStatusActive    VendorStatus = "active"
	VendorStatusInactive  VendorStatus = "inactive"
	VendorStatusPending   VendorStatus = "pending"
	VendorStatusSuspended VendorStatus = "suspended"
)

// Validation methods
func (u *User) Validate() error {
	if u.Username == "" {
		return fmt.Errorf("username is required")
	}
	if u.Email == "" {
		return fmt.Errorf("email is required")
	}
	if len(u.Roles) == 0 {
		return fmt.Errorf("at least one role is required")
	}
	return nil
}

func (p *Product) Validate() error {
	if p.SKU == "" {
		return fmt.Errorf("SKU is required")
	}
	if p.Name == "" {
		return fmt.Errorf("name is required")
	}
	if p.Price < 0 {
		return fmt.Errorf("price cannot be negative")
	}
	if p.Inventory.Quantity < 0 {
		return fmt.Errorf("inventory quantity cannot be negative")
	}
	return nil
}

func (o *Order) Validate() error {
	if o.UserID == "" {
		return fmt.Errorf("user ID is required")
	}
	if len(o.Items) == 0 {
		return fmt.Errorf("order must have at least one item")
	}
	if o.Total != o.Subtotal+o.Tax+o.Shipping-o.Discount {
		return fmt.Errorf("total amount calculation is incorrect")
	}
	return nil
}

// Business logic methods
func (o *Order) CalculateTotals() {
	o.Subtotal = 0
	for _, item := range o.Items {
		o.Subtotal += item.Total
	}
	o.Total = o.Subtotal + o.Tax + o.Shipping - o.Discount
}

func (p *Product) UpdateInventory(quantity int, operation string) error {
	switch operation {
	case "add":
		p.Inventory.Quantity += quantity
		p.Inventory.Available += quantity
	case "subtract":
		if p.Inventory.Available < quantity {
			return fmt.Errorf("insufficient inventory available")
		}
		p.Inventory.Quantity -= quantity
		p.Inventory.Available -= quantity
	case "reserve":
		if p.Inventory.Available < quantity {
			return fmt.Errorf("insufficient inventory available")
		}
		p.Inventory.Reserved += quantity
		p.Inventory.Available -= quantity
	case "release":
		if p.Inventory.Reserved < quantity {
			return fmt.Errorf("cannot release more than reserved")
		}
		p.Inventory.Reserved -= quantity
		p.Inventory.Available += quantity
	default:
		return fmt.Errorf("invalid inventory operation: %s", operation)
	}
	p.Inventory.LastRestocked = time.Now()
	return nil
}

func (u *User) HasRole(role UserRole) bool {
	for _, r := range u.Roles {
		if r == role {
			return true
		}
	}
	return false
}

func (u *User) AddRole(role UserRole) {
	if !u.HasRole(role) {
		u.Roles = append(u.Roles, role)
	}
}

func (u *User) RemoveRole(role UserRole) {
	for i, r := range u.Roles {
		if r == role {
			u.Roles = append(u.Roles[:i], u.Roles[i+1:]...)
			break
		}
	}
}
