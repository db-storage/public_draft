CREATE TABLE `shop`.`orders` (
    `tenant_id` BIGINT UNSIGNED NOT NULL,
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `status` VARCHAR(32) NOT NULL DEFAULT 'new' COMMENT '订单状态',
    `amount` DECIMAL(18, 2) NOT NULL,
    `delivery_time` DATETIME(3) NULL,
    `created_at` TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (`tenant_id`, `id`),
    UNIQUE KEY `uk_id` (`id`),
    KEY `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='订单表';
