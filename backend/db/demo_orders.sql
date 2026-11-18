-- Past orders so the dashboard has history in a demo. Loaded after seed.sql
-- unless SEED_DEMO_ORDERS=false. Times are UTC (India is UTC+5:30).
--
-- These use Kapshi, Paytan and Pukari, never Classic, so the live demo order
-- (Pune, Classic, 50 pairs) still comes out as 20 ready, 30 to make, 24 Nov.
-- New orders continue numbering from the highest code here (KS-1041 next).
--
-- reserved_ready / to_make: pairs taken from stock / booked into production when the order
-- was approved. Stock in seed.sql is what's left AFTER these reservations.

-- ---------- Orders ----------
-- Plain VALUES rows (not a WITH list) so PostgreSQL converts the text into the
-- status, date and timestamp column types. Ids are looked up by phone and design code.
INSERT INTO "order" (code, maker_id, product_id, retailer_id, retailer_name, retailer_phone, city, language,
                     price_per_pair, status, proposed_date, due_date, reserved_ready, to_make, created_at) VALUES
  ('KS-1036',
   (SELECT id FROM maker WHERE phone = '919800000001'),
   (SELECT p.id FROM product p JOIN maker m ON m.id = p.maker_id WHERE m.phone = '919800000001' AND p.code = 'paytan'),
   (SELECT id FROM retailer WHERE phone = '919811110002'),
   'Mumbai Craft Co.', '919811110002', 'Mumbai', 'English',
   480, 'delivered', '2026-11-05', '2026-11-11', 24, 0, '2026-11-04 10:50:00'),
  ('KS-1038',
   (SELECT id FROM maker WHERE phone = '919800000002'),
   (SELECT p.id FROM product p JOIN maker m ON m.id = p.maker_id WHERE m.phone = '919800000002' AND p.code = 'pukari'),
   (SELECT id FROM retailer WHERE phone = '919811110006'),
   'Bengaluru Desi Soles', '919811110006', 'Bengaluru', 'English',
   420, 'ready', '2026-11-14', '2026-11-14', 30, 6, '2026-11-07 07:30:00'),
  ('KS-1039',
   (SELECT id FROM maker WHERE phone = '919800000001'),
   (SELECT p.id FROM product p JOIN maker m ON m.id = p.maker_id WHERE m.phone = '919800000001' AND p.code = 'kapshi'),
   (SELECT id FROM retailer WHERE phone = '919811110005'),
   'Nashik Heritage Store', '919811110005', 'Nashik', 'Hindi',
   620, 'in_production', '2026-11-22', '2026-11-24', 16, 24, '2026-11-12 05:35:00'),
  ('KS-1040',
   (SELECT id FROM maker WHERE phone = '919800000002'),
   (SELECT p.id FROM product p JOIN maker m ON m.id = p.maker_id WHERE m.phone = '919800000002' AND p.code = 'kapshi'),
   (SELECT id FROM retailer WHERE phone = '919811110003'),
   'Indore Juti Ghar', '919811110003', 'Indore', 'Hindi',
   640, 'rejected', '2026-11-25', NULL, 0, 0, '2026-11-13 13:00:00');

-- ---------- Order lines (pairs per size) ----------
WITH v(code, size, qty) AS (VALUES
  ('KS-1036', 8, 12), ('KS-1036', 9, 12),
  ('KS-1038', 7, 10), ('KS-1038', 8, 14), ('KS-1038', 9, 12),
  ('KS-1039', 7, 10), ('KS-1039', 8, 16), ('KS-1039', 9, 14),
  ('KS-1040', 8, 20), ('KS-1040', 9, 15)
)
INSERT INTO orderline (order_id, size, qty)
SELECT o.id, v.size, v.qty FROM v JOIN "order" o ON o.code = v.code;

-- ---------- Audit history ----------
INSERT INTO auditlog (ts, maker_id, order_code, actor, action, detail) VALUES
  ('2026-11-04 10:50:00', (SELECT id FROM maker WHERE phone = '919800000001'), 'KS-1036', 'AI agent', 'order.drafted', 'Paytan, 24 pairs (size 8: 12, size 9: 12) for Mumbai Craft Co.'),
  ('2026-11-04 11:20:00', (SELECT id FROM maker WHERE phone = '919800000001'), 'KS-1036', 'Maker', 'order.approved', '24 pairs at ₹480/pair, delivery 11 Nov 2026'),
  ('2026-11-11 09:30:00', (SELECT id FROM maker WHERE phone = '919800000001'), 'KS-1036', 'Maker', 'order.delivered', ''),
  ('2026-11-07 07:30:00', (SELECT id FROM maker WHERE phone = '919800000002'), 'KS-1038', 'AI agent', 'order.drafted', 'Pukari, 36 pairs for Bengaluru Desi Soles'),
  ('2026-11-07 08:05:00', (SELECT id FROM maker WHERE phone = '919800000002'), 'KS-1038', 'Maker', 'order.approved', '36 pairs at ₹420/pair, delivery 14 Nov 2026'),
  ('2026-11-14 17:40:00', (SELECT id FROM maker WHERE phone = '919800000002'), 'KS-1038', 'Maker', 'order.ready', ''),
  ('2026-11-12 05:35:00', (SELECT id FROM maker WHERE phone = '919800000001'), 'KS-1039', 'AI agent', 'order.drafted', 'Kapshi, 40 pairs (size 7: 10, size 8: 16, size 9: 14) for Nashik Heritage Store from Hindi message'),
  ('2026-11-12 05:35:00', (SELECT id FROM maker WHERE phone = '919800000001'), 'KS-1039', 'System', 'order.feasibility', '16 ready, 24 to make, earliest 22 Nov 2026'),
  ('2026-11-12 05:50:00', (SELECT id FROM maker WHERE phone = '919800000001'), 'KS-1039', 'Maker', 'order.counter', '₹620/pair, delivery 24 Nov 2026'),
  ('2026-11-12 06:10:00', (SELECT id FROM maker WHERE phone = '919800000001'), 'KS-1039', 'Retailer', 'counter.accepted', ''),
  ('2026-11-15 12:40:00', (SELECT id FROM maker WHERE phone = '919800000001'), 'KS-1039', 'Maker', 'order.in_production', ''),
  ('2026-11-13 13:00:00', (SELECT id FROM maker WHERE phone = '919800000002'), 'KS-1040', 'AI agent', 'order.drafted', 'Kapshi, 35 pairs for Indore Juti Ghar'),
  ('2026-11-13 15:30:00', (SELECT id FROM maker WHERE phone = '919800000002'), 'KS-1040', 'Maker', 'order.rejected', 'Leather shortage this week');
