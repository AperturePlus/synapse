package com.example.services;

import com.example.models.User;

public class UserService {
    public User createUser(String name, int age) {
        return new User(name, age);
    }

    public void printUser(User user) {
        System.out.println(user.getName());
    }
}
