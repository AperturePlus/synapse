package models

import "fmt"

type UserService struct{}

func NewUserService() *UserService {
	return &UserService{}
}

func (s *UserService) PrintUser(name string) {
	fmt.Println(name)
}
