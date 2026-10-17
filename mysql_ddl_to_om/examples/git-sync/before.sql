CREATE TABLE users (
  id INT NOT NULL,
  email VARCHAR(128) COMMENT 'User email address
@om.security=L2
@om.tag=PII.Email',
  obsolete INT,
  PRIMARY KEY (id)
) COMMENT='Users';
CREATE TABLE legacy_archive (id INT);
