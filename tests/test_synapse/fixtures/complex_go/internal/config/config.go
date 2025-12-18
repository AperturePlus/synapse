package config

import (
	"fmt"
	"os"
	"time"

	"gopkg.in/yaml.v3"
)

type Config struct {
	Port           int            `yaml:"port"`
	LogLevel       string         `yaml:"log_level"`
	RedisAddr      string         `yaml:"redis_addr"`
	RedisPassword  string         `yaml:"redis_password"`
	WorkerPoolSize int            `yaml:"worker_pool_size"`
	SMTPConfig     SMTPConfig     `yaml:"smtp"`
	Database       DatabaseConfig `yaml:"database"`
	Features       FeatureFlags   `yaml:"features"`
}

type SMTPConfig struct {
	Host     string        `yaml:"host"`
	Port     int           `yaml:"port"`
	Username string        `yaml:"username"`
	Password string        `yaml:"password"`
	Timeout  time.Duration `yaml:"timeout"`
}

type DatabaseConfig struct {
	Host            string        `yaml:"host"`
	Port            int           `yaml:"port"`
	Username        string        `yaml:"username"`
	Password        string        `yaml:"password"`
	Database        string        `yaml:"database"`
	MaxConnections  int           `yaml:"max_connections"`
	ConnMaxLifetime time.Duration `yaml:"conn_max_lifetime"`
	SSLMode         string        `yaml:"ssl_mode"`
}

type FeatureFlags struct {
	EnableCache          bool     `yaml:"enable_cache"`
	EnableMetrics        bool     `yaml:"enable_metrics"`
	EnableTracing        bool     `yaml:"enable_tracing"`
	EnableRateLimit      bool     `yaml:"enable_rate_limit"`
	ExperimentalFeatures []string `yaml:"experimental_features"`
}

func Load(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("failed to read config file: %w", err)
	}

	var cfg Config
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("failed to parse config: %w", err)
	}

	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("invalid config: %w", err)
	}

	return &cfg, nil
}

func (c *Config) Validate() error {
	if c.Port <= 0 || c.Port > 65535 {
		return fmt.Errorf("invalid port: %d", c.Port)
	}

	if c.WorkerPoolSize <= 0 {
		return fmt.Errorf("worker pool size must be positive")
	}

	if c.Database.MaxConnections <= 0 {
		return fmt.Errorf("max connections must be positive")
	}

	return nil
}

// DefaultConfig returns a configuration with sensible defaults
func DefaultConfig() *Config {
	return &Config{
		Port:           8080,
		LogLevel:       "info",
		RedisAddr:      "localhost:6379",
		WorkerPoolSize: 10,
		SMTPConfig: SMTPConfig{
			Host:    "smtp.gmail.com",
			Port:    587,
			Timeout: 30 * time.Second,
		},
		Database: DatabaseConfig{
			Host:            "localhost",
			Port:            5432,
			MaxConnections:  100,
			ConnMaxLifetime: time.Hour,
			SSLMode:         "disable",
		},
		Features: FeatureFlags{
			EnableCache:     true,
			EnableMetrics:   true,
			EnableTracing:   false,
			EnableRateLimit: true,
		},
	}
}
