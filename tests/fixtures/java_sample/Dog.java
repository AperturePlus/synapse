package com.example.models;

public class Dog extends Animal {
    public Dog(String name) {
        super(name);
    }

    @Override
    public void speak() {
        bark();
    }

    private void bark() {
        System.out.println("Woof!");
    }
}
