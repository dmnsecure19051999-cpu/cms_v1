CREATE OR REPLACE VIEW "Update_Customer_Info"."CustomerSpendingF1_2026H1" AS
 WITH latest_customer AS (
         SELECT DISTINCT ON (cd.id) cd.id AS id_khach_hang,
            cd.nguoi_gioi_thieu_id,
            cd.nguoi_gioi_thieu_khach_hang,
            cd.nguoi_gioi_thieu_khach_hang_pid
           FROM customer_data cd
          WHERE (cd.id IS NOT NULL)
          ORDER BY cd.id, cd.ngay_cuoi_cap_nhat DESC
        ), period_sales AS (
         SELECT sr.id_khach_hang,
            sr.ma_hoa_don,
            sr.loai_doanh_thu,
            sr.ten_doi_tuong_thanh_toan,
            sr.so_tien_thuc_te_thu,
            sr.ngay_cap_nhat_hoa_don_cuoi
           FROM sales_revenue sr
          WHERE (((sr.ngay_ghi)::date > '2025-12-31'::date) AND ((sr.ngay_ghi)::date < '2026-07-16'::date))
        ), latest_period_bill AS (
         SELECT ps.id_khach_hang,
            ps.ma_hoa_don,
            ps.loai_doanh_thu,
            ps.ten_doi_tuong_thanh_toan,
            ps.so_tien_thuc_te_thu,
            ps.ngay_cap_nhat_hoa_don_cuoi,
            row_number() OVER (PARTITION BY ps.ma_hoa_don ORDER BY ps.ngay_cap_nhat_hoa_don_cuoi DESC) AS rn
           FROM period_sales ps
        ), valid_bill AS (
         SELECT lpb.id_khach_hang,
            round(
                CASE
                    WHEN ((lpb.ten_doi_tuong_thanh_toan = ANY (ARRAY['SPĐ'::text, 'SPD - Prepaid'::text, 'Ưu đãi nội bộ'::text])) AND (lpb.loai_doanh_thu = 'Khác'::text)) THEN ((NULLIF((lpb.so_tien_thuc_te_thu)::text, ''::text))::numeric * '-0.85'::numeric)
                    WHEN (lpb.ten_doi_tuong_thanh_toan = ANY (ARRAY['SPĐ'::text, 'SPD - Prepaid'::text, 'Ưu đãi nội bộ'::text, 'KHKD SPĐ'::text, 'Giảm VinClub'::text, 'Tích điểm VinClub'::text, 'VinID'::text, 'Prepaid'::text])) THEN (0)::numeric
                    WHEN (lpb.loai_doanh_thu = 'Khác'::text) THEN (0.15 * (NULLIF((lpb.so_tien_thuc_te_thu)::text, ''::text))::numeric)
                    ELSE (NULLIF((lpb.so_tien_thuc_te_thu)::text, ''::text))::numeric
                END) AS revenue
           FROM (latest_period_bill lpb
             LEFT JOIN cancellation_bills cb ON ((lpb.ma_hoa_don = cb.ma_hoa_don)))
          WHERE ((lpb.rn = 1) AND (cb.ma_hoa_don IS NULL))
        ), bill_by_customer AS (
         SELECT vb.id_khach_hang,
            sum(vb.revenue) AS dtf1
           FROM valid_bill vb
          GROUP BY vb.id_khach_hang
        )
 SELECT lc.nguoi_gioi_thieu_id,
    lc.nguoi_gioi_thieu_khach_hang,
    lc.nguoi_gioi_thieu_khach_hang_pid,
    count(*) AS slf1,
    sum(bc.dtf1) AS dtf1
   FROM (latest_customer lc
     JOIN bill_by_customer bc ON ((lc.id_khach_hang = bc.id_khach_hang)))
  GROUP BY lc.nguoi_gioi_thieu_id, lc.nguoi_gioi_thieu_khach_hang, lc.nguoi_gioi_thieu_khach_hang_pid;