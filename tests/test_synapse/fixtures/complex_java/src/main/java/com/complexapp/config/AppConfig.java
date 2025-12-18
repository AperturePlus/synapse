package com.complexapp.config;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.Map;

public class AppConfig {
    private static final Logger logger = LoggerFactory.getLogger(AppConfig.class);
    
    @JsonProperty("server")
    private ServerConfig server;
    
    @JsonProperty("database")
    private DatabaseConfig database;
    
    @JsonProperty("redis")
    private RedisConfig redis;
    
    @JsonProperty("security")
    private SecurityConfig security;
    
    @JsonProperty("features")
    private FeatureFlags features;
    
    @JsonProperty("external_services")
    private Map<String, ExternalServiceConfig> externalServices;

    public static AppConfig load(String configPath) throws IOException {
        logger.info("Loading configuration from: {}", configPath);
        
        ObjectMapper mapper = new ObjectMapper();
        mapper.registerModule(new JavaTimeModule());
        
        String content = Files.readString(Path.of(configPath));
        AppConfig config = mapper.readValue(content, AppConfig.class);
        
        config.validate();
        logger.info("Configuration loaded successfully");
        
        return config;
    }

    private void validate() {
        if (server == null) {
            throw new IllegalArgumentException("Server configuration is required");
        }
        server.validate();

        if (database == null) {
            throw new IllegalArgumentException("Database configuration is required");
        }
        database.validate();

        if (redis != null) {
            redis.validate();
        }

        if (security != null) {
            security.validate();
        }
    }

    // Getters
    public ServerConfig getServer() { return server; }
    public DatabaseConfig getDatabase() { return database; }
    public RedisConfig getRedis() { return redis; }
    public SecurityConfig getSecurity() { return security; }
    public FeatureFlags getFeatures() { return features; }
    public Map<String, ExternalServiceConfig> getExternalServices() { return externalServices; }

    public static class ServerConfig {
        @JsonProperty("port")
        private int port;
        
        @JsonProperty("host")
        private String host;
        
        @JsonProperty("thread_pool")
        private ThreadPoolConfig threadPool;
        
        @JsonProperty("ssl")
        private SSLConfig ssl;

        public void validate() {
            if (port <= 0 || port > 65535) {
                throw new IllegalArgumentException("Invalid port: " + port);
            }
            if (host == null || host.trim().isEmpty()) {
                throw new IllegalArgumentException("Host is required");
            }
            if (threadPool != null) {
                threadPool.validate();
            }
        }

        public int getPort() { return port; }
        public String getHost() { return host; }
        public ThreadPoolConfig getThreadPool() { return threadPool; }
        public SSLConfig getSsl() { return ssl; }
    }

    public static class ThreadPoolConfig {
        @JsonProperty("core_size")
        private int coreSize;
        
        @JsonProperty("max_size")
        private int maxSize;
        
        @JsonProperty("queue_capacity")
        private int queueCapacity;
        
        @JsonProperty("keep_alive_time")
        private Duration keepAliveTime;

        public void validate() {
            if (coreSize <= 0) {
                throw new IllegalArgumentException("Core pool size must be positive");
            }
            if (maxSize < coreSize) {
                throw new IllegalArgumentException("Max pool size must be >= core size");
            }
        }

        public int getCoreSize() { return coreSize; }
        public int getMaxSize() { return maxSize; }
        public int getQueueCapacity() { return queueCapacity; }
        public Duration getKeepAliveTime() { return keepAliveTime; }
    }

    public static class SSLConfig {
        @JsonProperty("enabled")
        private boolean enabled;
        
        @JsonProperty("key_store")
        private String keyStore;
        
        @JsonProperty("key_store_password")
        private String keyStorePassword;
        
        @JsonProperty("trust_store")
        private String trustStore;

        public boolean isEnabled() { return enabled; }
        public String getKeyStore() { return keyStore; }
        public String getKeyStorePassword() { return keyStorePassword; }
        public String getTrustStore() { return trustStore; }
    }

    public static class DatabaseConfig {
        @JsonProperty("url")
        private String url;
        
        @JsonProperty("username")
        private String username;
        
        @JsonProperty("password")
        private String password;
        
        @JsonProperty("pool")
        private ConnectionPoolConfig pool;
        
        @JsonProperty("migrations")
        private MigrationConfig migrations;

        public void validate() {
            if (url == null || url.trim().isEmpty()) {
                throw new IllegalArgumentException("Database URL is required");
            }
            if (pool != null) {
                pool.validate();
            }
        }

        public String getUrl() { return url; }
        public String getUsername() { return username; }
        public String getPassword() { return password; }
        public ConnectionPoolConfig getPool() { return pool; }
        public MigrationConfig getMigrations() { return migrations; }
    }

    public static class ConnectionPoolConfig {
        @JsonProperty("min_size")
        private int minSize;
        
        @JsonProperty("max_size")
        private int maxSize;
        
        @JsonProperty("connection_timeout")
        private Duration connectionTimeout;
        
        @JsonProperty("idle_timeout")
        private Duration idleTimeout;
        
        @JsonProperty("max_lifetime")
        private Duration maxLifetime;

        public void validate() {
            if (minSize < 0) {
                throw new IllegalArgumentException("Min pool size cannot be negative");
            }
            if (maxSize <= 0) {
                throw new IllegalArgumentException("Max pool size must be positive");
            }
        }

        public int getMinSize() { return minSize; }
        public int getMaxSize() { return maxSize; }
        public Duration getConnectionTimeout() { return connectionTimeout; }
        public Duration getIdleTimeout() { return idleTimeout; }
        public Duration getMaxLifetime() { return maxLifetime; }
    }

    public static class MigrationConfig {
        @JsonProperty("enabled")
        private boolean enabled;
        
        @JsonProperty("locations")
        private List<String> locations;

        public boolean isEnabled() { return enabled; }
        public List<String> getLocations() { return locations; }
    }

    public static class RedisConfig {
        @JsonProperty("host")
        private String host;
        
        @JsonProperty("port")
        private int port;
        
        @JsonProperty("password")
        private String password;
        
        @JsonProperty("database")
        private int database;
        
        @JsonProperty("ssl")
        private boolean ssl;

        public void validate() {
            if (host == null || host.trim().isEmpty()) {
                throw new IllegalArgumentException("Redis host is required");
            }
            if (port <= 0 || port > 65535) {
                throw new IllegalArgumentException("Invalid Redis port: " + port);
            }
        }

        public String getHost() { return host; }
        public int getPort() { return port; }
        public String getPassword() { return password; }
        public int getDatabase() { return database; }
        public boolean isSsl() { return ssl; }
    }

    public static class SecurityConfig {
        @JsonProperty("jwt")
        private JWTConfig jwt;
        
        @JsonProperty("oauth2")
        private OAuth2Config oauth2;
        
        @JsonProperty("cors")
        private CorsConfig cors;
        
        @JsonProperty("rate_limiting")
        private RateLimitingConfig rateLimiting;

        public void validate() {
            if (jwt != null) {
                jwt.validate();
            }
            if (oauth2 != null) {
                oauth2.validate();
            }
        }

        public JWTConfig getJwt() { return jwt; }
        public OAuth2Config getOauth2() { return oauth2; }
        public CorsConfig getCors() { return cors; }
        public RateLimitingConfig getRateLimiting() { return rateLimiting; }
    }

    public static class JWTConfig {
        @JsonProperty("secret")
        private String secret;
        
        @JsonProperty("expiration")
        private Duration expiration;
        
        @JsonProperty("refresh_expiration")
        private Duration refreshExpiration;

        public void validate() {
            if (secret == null || secret.length() < 32) {
                throw new IllegalArgumentException("JWT secret must be at least 32 characters");
            }
        }

        public String getSecret() { return secret; }
        public Duration getExpiration() { return expiration; }
        public Duration getRefreshExpiration() { return refreshExpiration; }
    }

    public static class OAuth2Config {
        @JsonProperty("providers")
        private Map<String, OAuth2ProviderConfig> providers;

        public void validate() {
            if (providers != null) {
                providers.values().forEach(OAuth2ProviderConfig::validate);
            }
        }

        public Map<String, OAuth2ProviderConfig> getProviders() { return providers; }
    }

    public static class OAuth2ProviderConfig {
        @JsonProperty("client_id")
        private String clientId;
        
        @JsonProperty("client_secret")
        private String clientSecret;
        
        @JsonProperty("redirect_uri")
        private String redirectUri;

        public void validate() {
            if (clientId == null || clientId.trim().isEmpty()) {
                throw new IllegalArgumentException("OAuth2 client ID is required");
            }
        }

        public String getClientId() { return clientId; }
        public String getClientSecret() { return clientSecret; }
        public String getRedirectUri() { return redirectUri; }
    }

    public static class CorsConfig {
        @JsonProperty("allowed_origins")
        private List<String> allowedOrigins;
        
        @JsonProperty("allowed_methods")
        private List<String> allowedMethods;
        
        @JsonProperty("allowed_headers")
        private List<String> allowedHeaders;
        
        @JsonProperty("max_age")
        private Duration maxAge;

        public List<String> getAllowedOrigins() { return allowedOrigins; }
        public List<String> getAllowedMethods() { return allowedMethods; }
        public List<String> getAllowedHeaders() { return allowedHeaders; }
        public Duration getMaxAge() { return maxAge; }
    }

    public static class RateLimitingConfig {
        @JsonProperty("enabled")
        private boolean enabled;
        
        @JsonProperty("requests_per_minute")
        private int requestsPerMinute;
        
        @JsonProperty("burst_size")
        private int burstSize;

        public boolean isEnabled() { return enabled; }
        public int getRequestsPerMinute() { return requestsPerMinute; }
        public int getBurstSize() { return burstSize; }
    }

    public static class FeatureFlags {
        @JsonProperty("enable_cache")
        private boolean enableCache;
        
        @JsonProperty("enable_metrics")
        private boolean enableMetrics;
        
        @JsonProperty("enable_tracing")
        private boolean enableTracing;
        
        @JsonProperty("enable_rate_limiting")
        private boolean enableRateLimiting;
        
        @JsonProperty("experimental_features")
        private List<String> experimentalFeatures;

        public boolean isEnableCache() { return enableCache; }
        public boolean isEnableMetrics() { return enableMetrics; }
        public boolean isEnableTracing() { return enableTracing; }
        public boolean isEnableRateLimiting() { return enableRateLimiting; }
        public List<String> getExperimentalFeatures() { return experimentalFeatures; }
    }

    public static class ExternalServiceConfig {
        @JsonProperty("url")
        private String url;
        
        @JsonProperty("api_key")
        private String apiKey;
        
        @JsonProperty("timeout")
        private Duration timeout;
        
        @JsonProperty("retry_policy")
        private RetryPolicy retryPolicy;

        public String getUrl() { return url; }
        public String getApiKey() { return apiKey; }
        public Duration getTimeout() { return timeout; }
        public RetryPolicy getRetryPolicy() { return retryPolicy; }
    }

    public static class RetryPolicy {
        @JsonProperty("max_attempts")
        private int maxAttempts;
        
        @JsonProperty("backoff_multiplier")
        private double backoffMultiplier;
        
        @JsonProperty("max_backoff")
        private Duration maxBackoff;

        public int getMaxAttempts() { return maxAttempts; }
        public double getBackoffMultiplier() { return backoffMultiplier; }
        public Duration getMaxBackoff() { return maxBackoff; }
    }
}