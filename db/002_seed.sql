-- Idempotent seed, executed after schema initialization.
INSERT INTO events(slug, title, starts_at)
VALUES ('campus-concert','The Last Seat: Campus Concert','2027-03-20 18:00:00+05:30')
ON CONFLICT (slug) DO NOTHING;

INSERT INTO seats(event_id, number)
SELECT e.id, n FROM events e CROSS JOIN generate_series(1,500) AS n
WHERE e.slug='campus-concert'
ON CONFLICT (event_id,number) DO NOTHING;
