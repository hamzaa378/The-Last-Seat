-- SQL invariant report: the two zero counts MUST be zero.
SELECT 'double_booked_seats' AS invariant, count(*) AS violations
FROM (
  SELECT seat_id FROM bookings
  WHERE status IN ('HELD','CONFIRMED') GROUP BY seat_id HAVING count(*) > 1
) duplicates
UNION ALL
SELECT 'duplicate_active_users', count(*) FROM (
  SELECT event_id, user_id FROM bookings
  WHERE status IN ('HELD','CONFIRMED') GROUP BY event_id,user_id HAVING count(*) > 1
) duplicates;

-- Inventory coverage (sample concert): confirmed + held + physically free = 500.
SELECT e.slug, count(s.id) AS capacity,
       count(*) FILTER (WHERE b.status='CONFIRMED') AS confirmed,
       count(*) FILTER (WHERE b.status='HELD') AS held,
       count(*) FILTER (WHERE b.id IS NULL) AS physically_free
FROM events e JOIN seats s ON s.event_id=e.id
LEFT JOIN bookings b ON b.seat_id=s.id AND b.status IN ('HELD','CONFIRMED')
WHERE e.slug='campus-concert'
GROUP BY e.slug;

-- Event audit records cannot be updated/deleted (enforced by database trigger).
