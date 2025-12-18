package main

import (
	"github.com/example/web/handlers"
	"github.com/gin-gonic/gin"
)

func SetupGin() *gin.Engine {
	r := gin.Default()
	api := r.Group("/api")
	api.GET("/ping", handlers.Ping)
	r.POST("/submit", Submit)
	r.Handle("PUT", "/direct", handlers.Ping)
	return r
}

func Submit(c *gin.Context) {}

