CREATE TABLE users (
  id INT NOT NULL,
  email VARCHAR(128) COMMENT '用户邮箱
@om.security=L2
@om.tag=PII.Email',
  obsolete INT,
  PRIMARY KEY (id)
) COMMENT='用户';
CREATE TABLE legacy_archive (id INT);
