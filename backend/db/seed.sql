-- KarigarSetu SAMPLE suppliers: makers, their designs, stock, and their supplier accounts.
-- Loaded when the tables are created (python -m app.seed --reset, or first server start) if SAMPLE_MAKERS=true.
-- They show as approved suppliers on /admin but can't log in to the website (no password).
-- Your own maker is NOT here: sign up on the website, approve it at /admin, then log in.
-- Retailers (shops) are in retailers.sql.
--
-- Edit freely. Rules:
--   * Phones are digits only, with country code (91...).
--   * Rows are linked by phone and product code, not by id, so editing ids is never needed.
--   * Works on both SQLite and PostgreSQL. Times are UTC.
--   * Don't put semicolons inside text values, and end each statement with ; at the end of a line
--     (the loader splits statements there).

-- ---------- Makers ----------
-- language: the language of the fixed WhatsApp messages this maker gets (Marathi, Hindi or English)
INSERT INTO maker (name, phone, place, buffer_days, min_order, language) VALUES
  ('Kolhapur Chappal Kendra',      '919800000001', 'Kolhapur, Maharashtra',      3, 20, 'Marathi'),
  ('Patil Chappal Udyog',  '919800000002', 'Kapshi, Kolhapur district',  4, 30, 'Marathi');

-- ---------- Products (designs each maker sells) ----------
-- pairs_per_day = how many pairs of this design the workshop can make in a day
WITH v(n, maker_phone, code, name, price_per_pair, pairs_per_day, sizes) AS (VALUES
  (1, '919800000001', 'classic',  'Kolhapuri Classic', 550, 6, '6,7,8,9,10'),
  (2, '919800000001', 'kapshi',   'Kapshi',            620, 4, '6,7,8,9,10'),
  (3, '919800000001', 'paytan',   'Paytan',            480, 8, '6,7,8,9,10'),
  (4, '919800000002', 'kapshi',   'Kapshi',            640, 5, '6,7,8,9,10'),
  (5, '919800000002', 'kachkadi', 'Kachkadi',          700, 3, '6,7,8,9,10'),
  (6, '919800000002', 'pukari',   'Pukari',            420, 7, '6,7,8,9,10')
)
INSERT INTO product (maker_id, code, name, price_per_pair, pairs_per_day, sizes)
SELECT m.id, v.code, v.name, v.price_per_pair, v.pairs_per_day, v.sizes
FROM v JOIN maker m ON m.phone = v.maker_phone
-- ORDER BY keeps the file's order, so designs are listed in this order everywhere
ORDER BY v.n;

-- ---------- Stock (pairs ready to ship, by size) ----------
WITH v(maker_phone, code, size, ready) AS (VALUES
  ('919800000001', 'classic', 6, 4), ('919800000001', 'classic', 7, 6), ('919800000001', 'classic', 8, 8),
  ('919800000001', 'classic', 9, 6), ('919800000001', 'classic', 10, 3),
  ('919800000001', 'kapshi', 6, 2),  ('919800000001', 'kapshi', 7, 5),  ('919800000001', 'kapshi', 8, 6),
  ('919800000001', 'kapshi', 9, 4),  ('919800000001', 'kapshi', 10, 1),
  ('919800000001', 'paytan', 6, 6),  ('919800000001', 'paytan', 7, 8),  ('919800000001', 'paytan', 8, 9),
  ('919800000001', 'paytan', 9, 7),  ('919800000001', 'paytan', 10, 4),
  ('919800000002', 'kapshi', 6, 3),  ('919800000002', 'kapshi', 7, 4),  ('919800000002', 'kapshi', 8, 6),
  ('919800000002', 'kapshi', 9, 5),  ('919800000002', 'kapshi', 10, 2),
  ('919800000002', 'kachkadi', 6, 2), ('919800000002', 'kachkadi', 7, 3), ('919800000002', 'kachkadi', 8, 4),
  ('919800000002', 'kachkadi', 9, 3), ('919800000002', 'kachkadi', 10, 1),
  ('919800000002', 'pukari', 6, 8),  ('919800000002', 'pukari', 7, 10), ('919800000002', 'pukari', 8, 12),
  ('919800000002', 'pukari', 9, 9),  ('919800000002', 'pukari', 10, 5)
)
INSERT INTO stock (product_id, size, ready)
SELECT p.id, v.size, v.ready
FROM v JOIN maker m ON m.phone = v.maker_phone JOIN product p ON p.maker_id = m.id AND p.code = v.code;

-- ---------- Supplier accounts for the sample makers ----------
-- Approved, linked to the maker by WhatsApp number. password_hash 'sample-no-login' = no website login.
WITH v(phone, owner, craft, email) AS (VALUES
  ('919800000001', 'Ganesh Jadhav', 'Kolhapuri chappals', 'kendra@sample.karigarsetu.in'),
  ('919800000002', 'Sunil Patil',   'Kolhapuri chappals', 'patil@sample.karigarsetu.in')
)
INSERT INTO supplier_account (maker_id, name, business_name, craft, town, phone, email, password_hash,
                              status, failed_logins, created_at, reviewed_at)
SELECT m.id, v.owner, m.name, v.craft, m.place, m.phone, v.email, 'sample-no-login',
       'approved', 0, '2026-10-01 09:00:00', '2026-10-01 10:00:00'
FROM v JOIN maker m ON m.phone = v.phone
ORDER BY m.id;
