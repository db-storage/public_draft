CREATE TABLE shop.customers (
  id BIGINT NOT NULL,
  name VARCHAR(128) COMMENT 'Customer name',
  PRIMARY KEY (id)
) COMMENT='Customers table';

CREATE TABLE shop.customer_orders (
  id BIGINT NOT NULL,
  customer_id BIGINT NOT NULL,
  order_status VARCHAR(32) COMMENT 'Order status',
  PRIMARY KEY (id),
  CONSTRAINT fk_customer FOREIGN KEY (customer_id) REFERENCES shop.customers(id)
) COMMENT='Customer orders';
