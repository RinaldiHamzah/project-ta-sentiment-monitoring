relasi antar tabel berdasarkan database:

hotels (1) → users (N)
Satu hotel dapat memiliki banyak user.
users.hotel_id → hotels.hotel_id
Aksi: ON UPDATE CASCADE, ON DELETE RESTRICT.

hotels (1) → hotel_reviews (N)
Satu hotel memiliki banyak review mentah.
hotel_reviews.hotel_id → hotels.hotel_id
Aksi: ON UPDATE CASCADE, ON DELETE CASCADE.

hotels (1) → sentiment_reviews (N)
Satu hotel memiliki banyak hasil analisis sentimen.
sentiment_reviews.hotel_id → hotels.hotel_id
Aksi: ON UPDATE CASCADE, ON DELETE CASCADE.

hotel_reviews (1) → sentiment_reviews (N)
Satu review mentah dapat memiliki banyak hasil analisis sentimen.
sentiment_reviews.review_id → hotel_reviews.review_id
Aksi: ON UPDATE CASCADE, ON DELETE CASCADE.

hotels (1) → telegram_users (N)
Satu hotel memiliki banyak subscriber Telegram.
telegram_users.hotel_id → hotels.hotel_id
Aksi: ON UPDATE CASCADE, ON DELETE CASCADE.

telegram_users (1) → notifications (N)
Satu subscriber dapat menerima banyak notifikasi.
notifications.(chat_id, hotel_id) → telegram_users.(chat_id, hotel_id)
Aksi: ON UPDATE CASCADE, ON DELETE CASCADE.

hotel_reviews (1) → notifications (0..N)
Satu review bisa memicu banyak notifikasi, namun opsional karena review_id bisa NULL.
notifications.review_id → hotel_reviews.review_id
Aksi: ON UPDATE CASCADE, ON DELETE SET NULL.

hotels (1) → notifications (N)
Semua notifikasi tetap terikat ke hotel.
notifications.hotel_id → hotels.hotel_id
Aksi: ON UPDATE CASCADE, ON DELETE CASCADE.