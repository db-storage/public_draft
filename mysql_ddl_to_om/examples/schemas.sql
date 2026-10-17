CREATE TABLE shop.customers (
  id BIGINT NOT NULL,
  name VARCHAR(128) COMMENT '客户名称',
  PRIMARY KEY (id)
) COMMENT='客户表';

CREATE TABLE shop.customer_orders (
  id BIGINT NOT NULL,
  customer_id BIGINT NOT NULL,
  order_status VARCHAR(32) COMMENT '订单状态',
  PRIMARY KEY (id),
  CONSTRAINT fk_customer FOREIGN KEY (customer_id) REFERENCES shop.customers(id)
) COMMENT='客户订单';
