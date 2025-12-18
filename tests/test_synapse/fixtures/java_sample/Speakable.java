package com.example.interfaces;

public interface Speakable {
    void speak();
    default void greet() {
        System.out.println("Hello!");
    }
}
