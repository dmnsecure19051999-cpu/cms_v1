CREATE OR REPLACE VIEW "Update_Bills"."UpdateBill" AS
 WITH clean_table AS (
         SELECT DISTINCT (sr.loai_du_lieu)::text AS loai_du_lieu,
            (sr.id_khach_hang)::text AS id_khach_hang,
            (sr.khach_hang)::text AS khach_hang,
            (sr.pid)::text AS pid,
            (sr.loai_doanh_thu)::text AS loai_doanh_thu,
            (sr.loai_hoa_don)::text AS loai_hoa_don,
            (sr.ma_hoa_don)::text AS ma_hoa_don,
            (sr.san_pham)::text AS san_pham,
            sr.so_luong,
            sr.ngay_ghi,
            sr.ngay_cap_nhat_hoa_don_cuoi,
            sr.so_tien_thuc_te_thu,
            (sr.ten_doi_tuong_thanh_toan)::text AS ten_doi_tuong_thanh_toan
           FROM sales_revenue sr
        ), ranked_table AS (
         SELECT c.loai_du_lieu,
            c.id_khach_hang,
            c.khach_hang,
            c.pid,
            c.loai_doanh_thu,
            c.loai_hoa_don,
            c.ma_hoa_don,
            c.san_pham,
            c.so_luong,
            c.ngay_ghi,
            c.ngay_cap_nhat_hoa_don_cuoi,
            c.so_tien_thuc_te_thu,
            c.ten_doi_tuong_thanh_toan,
            dense_rank() OVER (PARTITION BY c.ma_hoa_don ORDER BY c.ngay_cap_nhat_hoa_don_cuoi DESC) AS "Rank_HD"
           FROM clean_table c
        )
 SELECT rt.loai_du_lieu,
    rt.id_khach_hang,
    rt.khach_hang,
    rt.pid,
    rt.loai_doanh_thu,
    rt.loai_hoa_don,
    rt.ma_hoa_don,
    rt.san_pham,
    rt.so_luong,
    rt.ngay_ghi,
    rt.ngay_cap_nhat_hoa_don_cuoi,
    rt.so_tien_thuc_te_thu,
    rt.ten_doi_tuong_thanh_toan,
    rt."Rank_HD",
    round(
        CASE
         WHEN ((rt.ten_doi_tuong_thanh_toan::text = ANY (ARRAY['SPĐ'::text, 'SPD - Prepaid'::text, 'Ưu đãi nội bộ'::text])) AND (rt.loai_doanh_thu::text = 'Khác'::text)) THEN ((NULLIF(rt.so_tien_thuc_te_thu::text, ''::text))::numeric * '-0.85'::numeric)
         WHEN (rt.ten_doi_tuong_thanh_toan::text = ANY (ARRAY['SPĐ'::text, 'SPD - Prepaid'::text, 'Ưu đãi nội bộ'::text, 'KHKD SPĐ'::text, 'Giảm VinClub'::text, 'Tích điểm VinClub'::text, 'VinID'::text, 'Prepaid'::text])) THEN (0)::numeric
         WHEN (rt.loai_doanh_thu::text = 'Khác'::text) THEN (0.15 * (NULLIF(rt.so_tien_thuc_te_thu::text, ''::text))::numeric)
         ELSE (NULLIF(rt.so_tien_thuc_te_thu::text, ''::text))::numeric
        END) AS revenue
   FROM (ranked_table rt
     LEFT JOIN cancellation_bills cb ON ((rt.ma_hoa_don = cb.ma_hoa_don)))
  WHERE ((rt."Rank_HD" = 1) AND (cb.ma_hoa_don IS NULL));