package com.example.models;

public abstract class Animal {
    protected String name;

    public Animal(String name) {
        this.name = name;
    }

    public abstract void speak();

    public String getName() {
        return name;
    }
}
