package main

import (
	"github.com/example/web/handlers"
	"github.com/gofiber/fiber/v2"
)

func SetupFiber() *fiber.App {
	app := fiber.New()
	v1 := app.Group("/v1")
	v1.Get("/users", handlers.ListUsers)
	app.Delete("/users/:id", DeleteUser)
	app.Add("PATCH", "/users/:id", handlers.ListUsers)
	return app
}

func DeleteUser(c *fiber.Ctx) error { return nil }

