CREATE OR REPLACE VIEW "Update_Customer_Info"."CustomerSpendingF1_2026H1" AS
WITH latest_customer AS (
   SELECT DISTINCT ON ((cd.id)::text)
      (cd.id)::text AS id_khach_hang,
      cd.nguoi_gioi_thieu_id,
      cd.nguoi_gioi_thieu_khach_hang,
      cd.nguoi_gioi_thieu_khach_hang_pid
   FROM public.customer_data cd
   WHERE cd.id IS NOT NULL
   ORDER BY (cd.id)::text, cd.ngay_cuoi_cap_nhat DESC
),
period_sales AS (
   SELECT
      (sr.id_khach_hang)::text AS id_khach_hang,
      (sr.ma_hoa_don)::text AS ma_hoa_don,
      (sr.loai_doanh_thu)::text AS loai_doanh_thu,
      (sr.ten_doi_tuong_thanh_toan)::text AS ten_doi_tuong_thanh_toan,
      sr.so_tien_thuc_te_thu,
      sr.ngay_cap_nhat_hoa_don_cuoi
   FROM public.sales_revenue sr
   WHERE (sr.ngay_ghi)::date > DATE '2025-12-31'
     AND (sr.ngay_ghi)::date < DATE '2026-07-16'
),
latest_period_bill AS (
   SELECT
      ps.*,
      ROW_NUMBER() OVER (
         PARTITION BY ps.ma_hoa_don
         ORDER BY ps.ngay_cap_nhat_hoa_don_cuoi DESC
      ) AS rn
   FROM period_sales ps
),
valid_bill AS (
   SELECT
      lpb.id_khach_hang,
      ROUND(
         CASE
            WHEN lpb.ten_doi_tuong_thanh_toan = ANY (ARRAY['SPĐ', 'SPD - Prepaid', 'Ưu đãi nội bộ'])
                AND lpb.loai_doanh_thu = 'Khác'
               THEN NULLIF(lpb.so_tien_thuc_te_thu::text, '')::numeric * -0.85
            WHEN lpb.ten_doi_tuong_thanh_toan = ANY (
               ARRAY['SPĐ', 'SPD - Prepaid', 'Ưu đãi nội bộ', 'KHKD SPĐ', 'Giảm VinClub', 'Tích điểm VinClub', 'VinID', 'Prepaid']
            )
               THEN 0
            WHEN lpb.loai_doanh_thu = 'Khác'
               THEN 0.15 * NULLIF(lpb.so_tien_thuc_te_thu::text, '')::numeric
            ELSE NULLIF(lpb.so_tien_thuc_te_thu::text, '')::numeric
         END
      ) AS revenue
   FROM latest_period_bill lpb
   LEFT JOIN public.cancellation_bills cb
      ON lpb.ma_hoa_don = (cb.ma_hoa_don)::text
   WHERE lpb.rn = 1
     AND cb.ma_hoa_don IS NULL
),
bill_by_customer AS (
   SELECT
      vb.id_khach_hang,
      SUM(vb.revenue) AS dtf1
   FROM valid_bill vb
   GROUP BY vb.id_khach_hang
)
SELECT
   lc.nguoi_gioi_thieu_id,
   lc.nguoi_gioi_thieu_khach_hang,
   lc.nguoi_gioi_thieu_khach_hang_pid,
   COUNT(*) AS slf1,
   SUM(bc.dtf1) AS dtf1
FROM latest_customer lc
JOIN bill_by_customer bc
   ON lc.id_khach_hang = bc.id_khach_hang
GROUP BY
   lc.nguoi_gioi_thieu_id,
   lc.nguoi_gioi_thieu_khach_hang,
   lc.nguoi_gioi_thieu_khach_hang_pid;