-- KarigarSetu: designs (products) and ready stock for each maker, by WhatsApp number.
--
-- Runs automatically:
--   * when the admin approves a maker at /admin
--   * after  python -m app.seed --reset
-- Run it by hand any time (after editing this file):
--   python -m app.seed --designs
--
-- Only adds what's missing: a design the maker already has is not changed, and stock the maker has
-- edited is not overwritten. To change a price or stock later, use the dashboard or WhatsApp.
--
-- Rules:
--   * maker_phone = the WhatsApp number used at sign-up, digits only with country code (91...).
--     A maker that doesn't exist yet (not approved) is simply skipped.
--   * code = short id the AI uses (lowercase, no spaces). sizes = comma-separated.
--   * pairs_per_day = how many pairs of this design the workshop can make in a day.
--   * Don't put semicolons inside text values. End each statement with ; at the end of a line.

-- ---------- Designs ----------
WITH v(n, maker_phone, code, name, price_per_pair, pairs_per_day, sizes) AS (VALUES
  (1, '917030317109', 'classic', 'Kolhapuri Classic', 550, 6, '6,7,8,9,10'),
  (2, '917030317109', 'kapshi',  'Kapshi',            620, 4, '6,7,8,9,10'),
  (3, '917030317109', 'paytan',  'Paytan',            480, 8, '6,7,8,9,10')
)
INSERT INTO product (maker_id, code, name, price_per_pair, pairs_per_day, sizes)
SELECT m.id, v.code, v.name, v.price_per_pair, v.pairs_per_day, v.sizes
FROM v JOIN maker m ON m.phone = v.maker_phone
WHERE NOT EXISTS (SELECT 1 FROM product p WHERE p.maker_id = m.id AND p.code = v.code)
ORDER BY v.n;

-- ---------- Ready stock (pairs ready to ship, by size) ----------
WITH v(maker_phone, code, size, ready) AS (VALUES
  ('917030317109', 'classic', 6, 4), ('917030317109', 'classic', 7, 6), ('917030317109', 'classic', 8, 8),
  ('917030317109', 'classic', 9, 6), ('917030317109', 'classic', 10, 3),
  ('917030317109', 'kapshi', 6, 2),  ('917030317109', 'kapshi', 7, 5),  ('917030317109', 'kapshi', 8, 6),
  ('917030317109', 'kapshi', 9, 4),  ('917030317109', 'kapshi', 10, 1),
  ('917030317109', 'paytan', 6, 6),  ('917030317109', 'paytan', 7, 8),  ('917030317109', 'paytan', 8, 9),
  ('917030317109', 'paytan', 9, 7),  ('917030317109', 'paytan', 10, 4)
)
INSERT INTO stock (product_id, size, ready)
SELECT p.id, v.size, v.ready
FROM v JOIN maker m ON m.phone = v.maker_phone
       JOIN product p ON p.maker_id = m.id AND p.code = v.code
WHERE NOT EXISTS (SELECT 1 FROM stock s WHERE s.product_id = p.id AND s.size = v.size);
