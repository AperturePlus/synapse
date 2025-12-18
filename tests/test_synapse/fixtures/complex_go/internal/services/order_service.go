package services

import (
	"context"
	"fmt"
	"sync"
	"time"

	"complexapp/internal/models"
	"complexapp/internal/repository"
)

// OrderService handles order-related business logic
type OrderService struct {
	orderRepo      repository.Repository[*models.Order, string]
	productRepo    repository.Repository[*models.Product, string]
	userService    *UserService
	paymentService PaymentService
	inventoryMu    sync.Mutex
}

type PaymentService interface {
	ProcessPayment(ctx context.Context, order *models.Order) error
	RefundPayment(ctx context.Context, orderID string, amount float64) error
	GetPaymentStatus(ctx context.Context, orderID string) (string, error)
}

func NewOrderService(
	orderRepo repository.Repository[*models.Order, string],
	productRepo repository.Repository[*models.Product, string],
	userService *UserService,
	paymentService PaymentService,
) *OrderService {
	return &OrderService{
		orderRepo:      orderRepo,
		productRepo:    productRepo,
		userService:    userService,
		paymentService: paymentService,
	}
}

// CreateOrder creates a new order with inventory validation
func (s *OrderService) CreateOrder(ctx context.Context, order *models.Order) error {
	// Validate order
	if err := order.Validate(); err != nil {
		return fmt.Errorf("order validation failed: %w", err)
	}

	// Check if user exists and is active
	user, err := s.userService.userRepo.GetByID(ctx, order.UserID)
	if err != nil {
		return fmt.Errorf("user not found: %w", err)
	}
	if user.Status != models.StatusActive {
		return fmt.Errorf("user account is not active")
	}

	// Validate and reserve inventory for all items
	s.inventoryMu.Lock()
	defer s.inventoryMu.Unlock()

	for i, item := range order.Items {
		product, err := s.productRepo.GetByID(ctx, item.ProductID)
		if err != nil {
			return fmt.Errorf("product %s not found: %w", item.ProductID, err)
		}

		if product.Inventory.Available < item.Quantity {
			return fmt.Errorf("insufficient inventory for product %s", product.Name)
		}

		// Reserve inventory
		if err := product.UpdateInventory(item.Quantity, "reserve"); err != nil {
			return fmt.Errorf("failed to reserve inventory: %w", err)
		}

		// Update product in repository
		if err := s.productRepo.Update(ctx, product); err != nil {
			return fmt.Errorf("failed to update product inventory: %w", err)
		}

		// Update order item with current product details
		order.Items[i].SKU = product.SKU
		order.Items[i].Name = product.Name
		order.Items[i].UnitPrice = product.Price
		order.Items[i].Total = float64(item.Quantity) * product.Price
	}

	// Calculate order totals
	order.CalculateTotals()

	// Set initial status
	order.Status = models.OrderStatusPending

	// Create order
	if err := s.orderRepo.Create(ctx, order); err != nil {
		// Release reserved inventory on failure
		s.releaseReservedInventory(ctx, order)
		return fmt.Errorf("failed to create order: %w", err)
	}

	return nil
}

// ProcessOrderPayment processes payment for an order
func (s *OrderService) ProcessOrderPayment(ctx context.Context, orderID string) error {
	order, err := s.orderRepo.GetByID(ctx, orderID)
	if err != nil {
		return fmt.Errorf("order not found: %w", err)
	}

	if order.Status != models.OrderStatusPending {
		return fmt.Errorf("order cannot be processed in current status: %s", order.Status)
	}

	// Process payment
	if err := s.paymentService.ProcessPayment(ctx, order); err != nil {
		order.Status = models.OrderStatusCancelled
		if err := s.orderRepo.Update(ctx, order); err != nil {
			fmt.Printf("Failed to update order status: %v\n", err)
		}
		s.releaseReservedInventory(ctx, order)
		return fmt.Errorf("payment processing failed: %w", err)
	}

	// Update order status
	order.Status = models.OrderStatusProcessing
	order.UpdatedAt = time.Now()

	if err := s.orderRepo.Update(ctx, order); err != nil {
		return fmt.Errorf("failed to update order status: %w", err)
	}

	return nil
}

// ShipOrder marks an order as shipped
func (s *OrderService) ShipOrder(ctx context.Context, orderID string, trackingInfo models.TrackingInfo) error {
	order, err := s.orderRepo.GetByID(ctx, orderID)
	if err != nil {
		return fmt.Errorf("order not found: %w", err)
	}

	if order.Status != models.OrderStatusProcessing {
		return fmt.Errorf("order must be in processing status to ship")
	}

	order.Status = models.OrderStatusShipped
	order.TrackingInfo = &trackingInfo
	order.UpdatedAt = time.Now()

	if err := s.orderRepo.Update(ctx, order); err != nil {
		return fmt.Errorf("failed to update order: %w", err)
	}

	return nil
}

// CancelOrder cancels an order and releases inventory
func (s *OrderService) CancelOrder(ctx context.Context, orderID string, reason string) error {
	order, err := s.orderRepo.GetByID(ctx, orderID)
	if err != nil {
		return fmt.Errorf("order not found: %w", err)
	}

	// Check if order can be cancelled
	if order.Status == models.OrderStatusShipped || order.Status == models.OrderStatusDelivered {
		return fmt.Errorf("order cannot be cancelled after shipping")
	}

	// Release reserved inventory
	s.releaseReservedInventory(ctx, order)

	// Process refund if payment was made
	if order.Status == models.OrderStatusProcessing {
		if err := s.paymentService.RefundPayment(ctx, orderID, order.Total); err != nil {
			fmt.Printf("Failed to process refund: %v\n", err)
		}
	}

	// Update order status
	order.Status = models.OrderStatusCancelled
	order.Notes = fmt.Sprintf("Cancelled: %s", reason)
	order.UpdatedAt = time.Now()

	if err := s.orderRepo.Update(ctx, order); err != nil {
		return fmt.Errorf("failed to update order: %w", err)
	}

	return nil
}

// GetOrderHistory returns order history for a user
func (s *OrderService) GetOrderHistory(ctx context.Context, userID string, limit, offset int) ([]*models.Order, error) {
	// In real implementation, you'd have a repository method for this
	orders, err := s.orderRepo.List(ctx, limit, offset)
	if err != nil {
		return nil, fmt.Errorf("failed to get orders: %w", err)
	}

	var userOrders []*models.Order
	for _, order := range orders {
		if order.UserID == userID {
			userOrders = append(userOrders, order)
		}
	}

	return userOrders, nil
}

// GetOrderStats returns order statistics
func (s *OrderService) GetOrderStats(ctx context.Context) (*OrderStats, error) {
	orders, err := s.orderRepo.List(ctx, 10000, 0)
	if err != nil {
		return nil, fmt.Errorf("failed to get orders: %w", err)
	}

	stats := &OrderStats{
		TotalOrders:     int64(len(orders)),
		StatusBreakdown: make(map[models.OrderStatus]int64),
		RevenueByStatus: make(map[models.OrderStatus]float64),
	}

	for _, order := range orders {
		stats.StatusBreakdown[order.Status]++
		stats.RevenueByStatus[order.Status] += order.Total

		if order.Status == models.OrderStatusDelivered {
			stats.TotalRevenue += order.Total
			stats.CompletedOrders++
		}
	}

	return stats, nil
}

type OrderStats struct {
	TotalOrders     int64
	CompletedOrders int64
	TotalRevenue    float64
	StatusBreakdown map[models.OrderStatus]int64
	RevenueByStatus map[models.OrderStatus]float64
}

// releaseReservedInventory releases reserved inventory for cancelled orders
func (s *OrderService) releaseReservedInventory(ctx context.Context, order *models.Order) {
	s.inventoryMu.Lock()
	defer s.inventoryMu.Unlock()

	for _, item := range order.Items {
		product, err := s.productRepo.GetByID(ctx, item.ProductID)
		if err != nil {
			fmt.Printf("Failed to get product for inventory release: %v\n", err)
			continue
		}

		if err := product.UpdateInventory(item.Quantity, "release"); err != nil {
			fmt.Printf("Failed to release inventory: %v\n", err)
			continue
		}

		if err := s.productRepo.Update(ctx, product); err != nil {
			fmt.Printf("Failed to update product after inventory release: %v\n", err)
		}
	}
}

// ProcessBatchOrders processes multiple orders in batch
func (s *OrderService) ProcessBatchOrders(ctx context.Context, orderIDs []string) *BatchProcessingResult {
	result := &BatchProcessingResult{
		SuccessCount: 0,
		FailureCount: 0,
		Errors:       make(map[string]error),
	}

	var wg sync.WaitGroup
	sem := make(chan struct{}, 5) // Limit concurrent processing

	for _, orderID := range orderIDs {
		wg.Add(1)
		go func(id string) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			if err := s.ProcessOrderPayment(ctx, id); err != nil {
				result.mu.Lock()
				result.FailureCount++
				result.Errors[id] = err
				result.mu.Unlock()
			} else {
				result.mu.Lock()
				result.SuccessCount++
				result.mu.Unlock()
			}
		}(orderID)
	}

	wg.Wait()
	return result
}

type BatchProcessingResult struct {
	SuccessCount int
	FailureCount int
	Errors       map[string]error
	mu           sync.Mutex
}
