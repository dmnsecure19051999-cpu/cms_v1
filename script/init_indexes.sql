-- Init index policy: only create missing indexes.
-- Do not drop any existing indexes during init.

-- Keep anti-join support for cancellation bills.
CREATE INDEX IF NOT EXISTS idx_cancellation_bills_ma_hoa_don
ON public.cancellation_bills (ma_hoa_don);

ANALYZE public.cancellation_bills;
