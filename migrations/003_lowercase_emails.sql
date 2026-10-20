UPDATE users SET email = lower(email) WHERE email <> lower(email);

CREATE UNIQUE INDEX users_email_lower_key ON users (lower(email));