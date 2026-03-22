-- schema.sql
-- Multi-hotel schema for Hotel Review Dashboard
-- Compatible with MariaDB / MySQL 8+

CREATE DATABASE IF NOT EXISTS monitoring_review
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE monitoring_review;

-- 1) Hotels
CREATE TABLE IF NOT EXISTS hotels (
  hotel_id INT AUTO_INCREMENT PRIMARY KEY,
  manajemen_hotel_id INT NOT NULL,
  hotel_name VARCHAR(255) NOT NULL,
  address VARCHAR(500) NULL,
  place_id VARCHAR(255) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  scrape_interval_minutes INT NOT NULL DEFAULT 30,
  last_scrape_at DATETIME NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,

  CONSTRAINT uq_hotels_manajemen_hotel_id UNIQUE (manajemen_hotel_id),
  CONSTRAINT uq_hotels_place_id UNIQUE (place_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_hotels_is_active ON hotels (is_active);
CREATE INDEX idx_hotels_name ON hotels (hotel_name);

-- 2) Users (1 user -> 1 hotel)

CREATE TABLE IF NOT EXISTS users (
  user_id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(100) NOT NULL,
  password VARCHAR(255) NOT NULL,
  role ENUM('admin', 'user') DEFAULT 'user',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  hotel_id INT NOT NULL,

  CONSTRAINT uq_users_username UNIQUE (username),
  CONSTRAINT fk_users_hotel
    FOREIGN KEY (hotel_id)
    REFERENCES hotels (hotel_id)
    ON UPDATE CASCADE
    ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_users_hotel_id ON users (hotel_id);

-- 3) Raw reviews

CREATE TABLE IF NOT EXISTS hotel_reviews (
  review_id INT AUTO_INCREMENT PRIMARY KEY,
  hotel_id INT NOT NULL,
  user_name VARCHAR(255) NULL,
  review_text TEXT NULL,
  rating INT NULL,
  review_date DATETIME NOT NULL,
  source VARCHAR(50) DEFAULT 'Google Maps',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT fk_hotel_reviews_hotel
    FOREIGN KEY (hotel_id)
    REFERENCES hotels (hotel_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_hotel_reviews_hotel_date ON hotel_reviews (hotel_id, review_date);
CREATE INDEX idx_hotel_reviews_hotel_user_rating_source ON hotel_reviews (hotel_id, user_name, rating, source);

-- 4) Sentiment reviews (ML output)

CREATE TABLE IF NOT EXISTS sentiment_reviews (
  sentiment_id INT AUTO_INCREMENT PRIMARY KEY,
  review_id INT NOT NULL,
  hotel_id INT NOT NULL,
  user_name VARCHAR(255) NULL,
  review_text TEXT NULL,
  rating TINYINT UNSIGNED NULL,
  review_date DATETIME NOT NULL,
  sentiment_nb VARCHAR(50) NULL,
  sentiment_svm VARCHAR(50) NULL,
  source VARCHAR(50) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT fk_sentiment_reviews_review
    FOREIGN KEY (review_id)
    REFERENCES hotel_reviews (review_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE,
  CONSTRAINT fk_sentiment_reviews_hotel
    FOREIGN KEY (hotel_id)
    REFERENCES hotels (hotel_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_sentiment_reviews_hotel_date ON sentiment_reviews (hotel_id, review_date);
CREATE INDEX idx_sentiment_reviews_hotel_nb ON sentiment_reviews (hotel_id, sentiment_nb);
CREATE INDEX idx_sentiment_reviews_hotel_svm ON sentiment_reviews (hotel_id, sentiment_svm);
CREATE INDEX idx_sentiment_reviews_review_id ON sentiment_reviews (review_id);

-- 5) Telegram subscribers (scoped per hotel)

CREATE TABLE IF NOT EXISTS telegram_users (
  chat_id BIGINT NOT NULL,
  hotel_id INT NOT NULL,
  subscribed TINYINT(1) DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (chat_id, hotel_id),
  CONSTRAINT fk_telegram_users_hotel
    FOREIGN KEY (hotel_id)
    REFERENCES hotels (hotel_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_telegram_users_hotel_subscribed ON telegram_users (hotel_id, subscribed);


-- 6) Notifications 
CREATE TABLE IF NOT EXISTS notifications (
  notif_id INT AUTO_INCREMENT PRIMARY KEY,
  review_id INT NULL,
  chat_id BIGINT NOT NULL,
  hotel_id INT NOT NULL,
  status VARCHAR(50) DEFAULT 'sent',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT fk_notifications_review
    FOREIGN KEY (review_id)
    REFERENCES hotel_reviews (review_id)
    ON UPDATE CASCADE
    ON DELETE SET NULL,
  CONSTRAINT fk_notifications_telegram_user
    FOREIGN KEY (chat_id, hotel_id)
    REFERENCES telegram_users (chat_id, hotel_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE,
  CONSTRAINT fk_notifications_hotel
    FOREIGN KEY (hotel_id)
    REFERENCES hotels (hotel_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_notifications_hotel_created_at ON notifications (hotel_id, created_at);
CREATE INDEX idx_notifications_chat_hotel ON notifications (chat_id, hotel_id);
CREATE INDEX idx_notifications_review_id ON notifications (review_id);

MariaDB [monitoring_review]> DESCRIBE users;
+------------+----------------------+------+-----+---------------------+----------------+
| Field      | Type                 | Null | Key | Default             | Extra          |
+------------+----------------------+------+-----+---------------------+----------------+
| user_id    | int(11)              | NO   | PRI | NULL                | auto_increment |
| username   | varchar(100)         | NO   | UNI | NULL                |                |
| password   | varchar(255)         | NO   |     | NULL                |                |
| role       | enum('admin','user') | YES  |     | user                |                |
| created_at | timestamp            | NO   |     | current_timestamp() |                |
| hotel_id   | int(11)              | NO   | MUL | NULL                |                |
+------------+----------------------+------+-----+---------------------+----------------+
6 rows in set (0.076 sec)

MariaDB [monitoring_review]> DESCRIBE hotels;
+-------------------------+--------------+------+-----+---------------------+----------------+
| Field                   | Type         | Null | Key | Default             | Extra          |
+-------------------------+--------------+------+-----+---------------------+----------------+
| hotel_id                | int(11)      | NO   | PRI | NULL                | auto_increment |
| manajemen_hotel_id      | int(11)      | NO   | UNI | NULL                |                |
| hotel_name              | varchar(255) | NO   |     | NULL                |                |
| address                 | varchar(500) | YES  |     | NULL                |                |
| place_id                | varchar(255) | NO   |     | NULL                |                |
| created_at              | timestamp    | NO   |     | current_timestamp() |                |
| last_scrape_at          | datetime     | YES  |     | NULL                |                |
| is_active               | tinyint(1)   | NO   |     | 1                   |                |
| scrape_interval_minutes | int(11)      | YES  |     | 30                  |                |
+-------------------------+--------------+------+-----+---------------------+----------------+
9 rows in set (0.037 sec)

MariaDB [monitoring_review]> DESCRIBE hotel_reviews;
+-------------+--------------+------+-----+---------------------+----------------+
| Field       | Type         | Null | Key | Default             | Extra          |
+-------------+--------------+------+-----+---------------------+----------------+
| review_id   | int(11)      | NO   | PRI | NULL                | auto_increment |
| hotel_id    | int(11)      | NO   | MUL | NULL                |                |
| user_name   | varchar(255) | YES  |     | NULL                |                |
| review_text | text         | YES  |     | NULL                |                |
| rating      | int(11)      | YES  |     | NULL                |                |
| review_date | datetime     | NO   |     | NULL                |                |
| source      | varchar(50)  | YES  |     | Google Maps         |                |
| created_at  | timestamp    | NO   |     | current_timestamp() |                |
+-------------+--------------+------+-----+---------------------+----------------+
8 rows in set (0.017 sec)

MariaDB [monitoring_review]> DESCRIBE sentiment_reviews;
+---------------+---------------------+------+-----+---------------------+----------------+
| Field         | Type                | Null | Key | Default             | Extra          |
+---------------+---------------------+------+-----+---------------------+----------------+
| sentiment_id  | int(11)             | NO   | PRI | NULL                | auto_increment |
| review_id     | int(11)             | NO   | MUL | NULL                |                |
| hotel_id      | int(11)             | NO   | MUL | NULL                |                |
| user_name     | varchar(255)        | YES  |     | NULL                |                |
| review_text   | text                | YES  |     | NULL                |                |
| rating        | tinyint(3) unsigned | YES  |     | NULL                |                |
| review_date   | datetime            | NO   |     | NULL                |                |
| sentiment_nb  | varchar(50)         | YES  |     | NULL                |                |
| sentiment_svm | varchar(50)         | YES  |     | NULL                |                |
| source        | varchar(50)         | YES  |     | NULL                |                |
| created_at    | timestamp           | NO   |     | current_timestamp() |                |
+---------------+---------------------+------+-----+---------------------+----------------+
11 rows in set (0.016 sec)

MariaDB [monitoring_review]> DESCRIBE telegram_users;
+------------+------------+------+-----+---------------------+-------+
| Field      | Type       | Null | Key | Default             | Extra |
+------------+------------+------+-----+---------------------+-------+
| chat_id    | bigint(20) | NO   | PRI | NULL                |       |
| hotel_id   | int(11)    | NO   | PRI | NULL                |       |
| subscribed | tinyint(1) | YES  |     | 1                   |       |
| created_at | timestamp  | NO   |     | current_timestamp() |       |
+------------+------------+------+-----+---------------------+-------+
4 rows in set (0.015 sec)

MariaDB [monitoring_review]> DESCRIBE notifications;
+------------+-------------+------+-----+---------------------+----------------+
| Field      | Type        | Null | Key | Default             | Extra          |
+------------+-------------+------+-----+---------------------+----------------+
| notif_id   | int(11)     | NO   | PRI | NULL                | auto_increment |
| review_id  | int(11)     | YES  | MUL | NULL                |                |
| chat_id    | bigint(20)  | NO   | MUL | NULL                |                |
| hotel_id   | int(11)     | NO   | MUL | NULL                |                |
| status     | varchar(50) | YES  |     | sent                |                |
| created_at | timestamp   | NO   |     | current_timestamp() |                |
+------------+-------------+------+-----+---------------------+----------------+
6 rows in set (0.035 sec)



ERD Summary:
6 Tables included (color-coded):

hotels — Blue, central parent table (9 columns)
users — Green, 1 user ? 1 hotel (6 columns)
hotel_reviews — Yellow, raw reviews (8 columns)
sentiment_reviews — Purple, ML sentiment output (11 columns)
telegram_users — Orange, composite PK (chat_id, hotel_id) (4 columns)
notifications — Red, notification log (6 columns)
8 FK relationships with crow's foot notation:

hotels 1?N users
hotels 1?N hotel_reviews
hotels 1?N sentiment_reviews
hotels 1?N telegram_users
hotels 1?N notifications
hotel_reviews 1?N sentiment_reviews
hotel_reviews 1?0..N notifications (dashed line — optional FK, ON DELETE SET NULL)
telegram_users 1?N notifications (composite FK chat_id + hotel_id)
