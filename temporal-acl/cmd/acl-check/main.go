package main

import (
	"context"
	"example.com/temporal-acl/acl"
	"fmt"
	"log"
	"os"
	"time"
)

func main() {
	if len(os.Args) != 4 {
		log.Fatal("usage: acl-check CONFIG USER_ID USER_TYPE")
	}
	cfg, err := acl.ReadConfig(os.Args[1])
	if err != nil {
		log.Fatal(err)
	}
	model, err := acl.NewFromConfig(cfg)
	if err != nil {
		log.Fatal(err)
	}
	defer model.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	p, err := model.GetPermissions(ctx, acl.Identity{UserID: os.Args[2], UserType: os.Args[3]})
	if err != nil {
		log.Fatal(err)
	}
	for ns, role := range p {
		fmt.Printf("%s: role_bits=%d\n", ns, role)
	}
}
