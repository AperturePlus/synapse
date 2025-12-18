package com.example.models;

import com.example.interfaces.Speakable;

public class Cat extends Animal implements Speakable {
    public Cat(String name) {
        super(name);
    }

    @Override
    public void speak() {
        meow();
    }

    private void meow() {
        System.out.println("Meow!");
    }
}
