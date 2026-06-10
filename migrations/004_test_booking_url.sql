-- 004_test_booking_url.sql
-- Temporary: point all dummy mentors at the same Cal.com booking link for testing.
-- Stored value is the path AFTER cal.com/ (the backend prepends CAL_BASE_URL).
UPDATE mentors
SET booking_url = 'yokesh-dhanabal-4hwiui/30min';
