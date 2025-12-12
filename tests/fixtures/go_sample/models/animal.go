package models

type Animal struct {
	Name string
}

func (a *Animal) GetName() string {
	return a.Name
}

type Dog struct {
	Animal
	Breed string
}

func (d *Dog) Bark() string {
	return "Woof!"
}

type Cat struct {
	Animal
}

func (c *Cat) Meow() string {
	return "Meow!"
}
