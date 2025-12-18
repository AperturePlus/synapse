package repository

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/google/uuid"
)

// Generic repository interface
type Repository[T any, ID comparable] interface {
	Create(ctx context.Context, entity *T) error
	GetByID(ctx context.Context, id ID) (*T, error)
	Update(ctx context.Context, entity *T) error
	Delete(ctx context.Context, id ID) error
	List(ctx context.Context, limit, offset int) ([]*T, error)
	Count(ctx context.Context) (int64, error)
}

// Generic cache interface
type Cache[K comparable, V any] interface {
	Get(key K) (V, bool)
	Set(key K, value V, ttl time.Duration)
	Delete(key K)
	Clear()
}

// MemoryRepository implements Repository with in-memory storage
type MemoryRepository[T any, ID comparable] struct {
	mu        sync.RWMutex
	items     map[ID]*T
	idFunc    func(*T) ID
	setIDFunc func(*T, ID)
}

func NewMemoryRepository[T any, ID comparable](
	idFunc func(*T) ID,
	setIDFunc func(*T, ID),
) *MemoryRepository[T, ID] {
	return &MemoryRepository[T, ID]{
		items:     make(map[ID]*T),
		idFunc:    idFunc,
		setIDFunc: setIDFunc,
	}
}

func (r *MemoryRepository[T, ID]) Create(ctx context.Context, entity *T) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	id := r.idFunc(entity)
	if _, exists := r.items[id]; exists {
		return fmt.Errorf("entity with id %v already exists", id)
	}

	if id == *new(ID) {
		newID := generateID[ID]()
		r.setIDFunc(entity, newID)
		id = newID
	}

	r.items[id] = entity
	return nil
}

func (r *MemoryRepository[T, ID]) GetByID(ctx context.Context, id ID) (*T, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	entity, exists := r.items[id]
	if !exists {
		return nil, fmt.Errorf("entity with id %v not found", id)
	}
	return entity, nil
}

func (r *MemoryRepository[T, ID]) Update(ctx context.Context, entity *T) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	id := r.idFunc(entity)
	if _, exists := r.items[id]; !exists {
		return fmt.Errorf("entity with id %v not found", id)
	}

	r.items[id] = entity
	return nil
}

func (r *MemoryRepository[T, ID]) Delete(ctx context.Context, id ID) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	if _, exists := r.items[id]; !exists {
		return fmt.Errorf("entity with id %v not found", id)
	}

	delete(r.items, id)
	return nil
}

func (r *MemoryRepository[T, ID]) List(ctx context.Context, limit, offset int) ([]*T, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	if limit <= 0 {
		limit = 10
	}

	var results []*T
	count := 0
	skipped := 0

	for _, entity := range r.items {
		if skipped < offset {
			skipped++
			continue
		}
		if count >= limit {
			break
		}
		results = append(results, entity)
		count++
	}

	return results, nil
}

func (r *MemoryRepository[T, ID]) Count(ctx context.Context) (int64, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return int64(len(r.items)), nil
}

// CachedRepository adds caching layer to any repository
type CachedRepository[T any, ID comparable] struct {
	repo   Repository[T, ID]
	cache  Cache[ID, *T]
	prefix string
}

func NewCachedRepository[T any, ID comparable](
	repo Repository[T, ID],
	cache Cache[ID, *T],
	prefix string,
) *CachedRepository[T, ID] {
	return &CachedRepository[T, ID]{
		repo:   repo,
		cache:  cache,
		prefix: prefix,
	}
}

func (c *CachedRepository[T, ID]) Create(ctx context.Context, entity *T) error {
	if err := c.repo.Create(ctx, entity); err != nil {
		return err
	}
	return nil
}

func (c *CachedRepository[T, ID]) GetByID(ctx context.Context, id ID) (*T, error) {
	cacheKey := c.prefix + fmt.Sprintf("%v", id)

	if entity, found := c.cache.Get(id); found {
		return entity, nil
	}

	entity, err := c.repo.GetByID(ctx, id)
	if err != nil {
		return nil, err
	}

	c.cache.Set(id, entity, 5*time.Minute)
	return entity, nil
}

func (c *CachedRepository[T, ID]) Update(ctx context.Context, entity *T) error {
	if err := c.repo.Update(ctx, entity); err != nil {
		return err
	}

	id := getIDFromEntity(entity)
	c.cache.Delete(id)
	return nil
}

func (c *CachedRepository[T, ID]) Delete(ctx context.Context, id ID) error {
	if err := c.repo.Delete(ctx, id); err != nil {
		return err
	}

	c.cache.Delete(id)
	return nil
}

func (c *CachedRepository[T, ID]) List(ctx context.Context, limit, offset int) ([]*T, error) {
	return c.repo.List(ctx, limit, offset)
}

func (c *CachedRepository[T, ID]) Count(ctx context.Context) (int64, error) {
	return c.repo.Count(ctx)
}

// Helper functions
func generateID[T any]() T {
	var zero T
	switch any(zero).(type) {
	case string:
		return any(uuid.New().String()).(T)
	case int:
		return any(int(time.Now().UnixNano())).(T)
	case int64:
		return any(time.Now().UnixNano()).(T)
	default:
		panic("unsupported ID type")
	}
}

func getIDFromEntity[T any, ID comparable](entity *T) ID {
	var zero ID
	return zero
}
