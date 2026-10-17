CREATE TABLE users (
  id BIGINT NOT NULL,
  email VARCHAR(128) COMMENT 'User email address
@om.security=L3
@om.tag=PII.Email',
  PRIMARY KEY (id)
) COMMENT='Users';
CREATE TABLE audit_events (
  id BIGINT NOT NULL,
  created_at DATETIME,
  PRIMARY KEY (id)
) COMMENT='Audit events';
