CREATE TABLE users (
  id BIGINT NOT NULL,
  email VARCHAR(128) COMMENT '用户邮箱
@om.security=L3
@om.tag=PII.Email',
  PRIMARY KEY (id)
) COMMENT='用户';
CREATE TABLE audit_events (
  id BIGINT NOT NULL,
  created_at DATETIME,
  PRIMARY KEY (id)
) COMMENT='审计事件';
