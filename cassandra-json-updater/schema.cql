-- Provision keyspace `tata` separately with replication configured for YOUR datacenter(s).
CREATE TABLE IF NOT EXISTS tata.users (user_id text, user_type text, cmdb text, created_at timestamp, PRIMARY KEY (user_id, user_type));
CREATE TABLE IF NOT EXISTS tata.groups (group_id text PRIMARY KEY, description text, create_at timestamp);
CREATE TABLE IF NOT EXISTS tata.group_members (group_id text, user_type text, user_id text, added_at text, PRIMARY KEY (group_id, user_type, user_id));
CREATE TABLE IF NOT EXISTS tata.user_permissions (user_id text, user_type text, namespace text, role_name text, granted_at timestamp, PRIMARY KEY (user_id, user_type, namespace));
CREATE TABLE IF NOT EXISTS tata.group_permissions (group_id text, namespace text, role_name text, granted_at timestamp, PRIMARY KEY (group_id, namespace));
CREATE TABLE IF NOT EXISTS tata.user_groups (user_id text, user_type text, group_id text, PRIMARY KEY (user_id, user_type, group_id));
