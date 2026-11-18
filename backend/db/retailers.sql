-- KarigarSetu retailers (shops that order on WhatsApp). Loaded into an empty database by
--   python -m app.seed  /  python -m app.seed --reset
-- Phones: digits only, with country code. End each statement with ; at the end of a line.

-- ---------- Retailers (customers) ----------
-- Pune Footwear House is the shop used in the live demo (first simulated order).
INSERT INTO retailer (name, phone, city, language, created_at) VALUES
  ('Pune Footwear House',     '919811112222', 'Pune',      'Marathi', '2026-10-02 10:15:00'),
  ('Nashik Heritage Store',   '919811110005', 'Nashik',    'Hindi',   '2026-10-09 12:30:00'),
  ('Mumbai Craft Co.',        '919811110002', 'Mumbai',    'English', '2026-10-14 09:45:00'),
  ('Kolhapur Footwear Mart',  '919811110001', 'Kolhapur',  'Marathi', '2026-10-20 16:00:00'),
  ('Indore Juti Ghar',        '919811110003', 'Indore',    'Hindi',   '2026-10-27 11:10:00'),
  ('Satara Chappal Bazaar',   '919811110004', 'Satara',    'Marathi', '2026-11-01 14:05:00'),
  ('Bengaluru Desi Soles',    '919811110006', 'Bengaluru', 'English', '2026-11-03 18:20:00');
