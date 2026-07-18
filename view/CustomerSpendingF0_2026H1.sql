CREATE OR REPLACE VIEW "Update_Customer_Info"."CustomerSpendingF0_2026H1" AS
 WITH latest_customer AS (
         SELECT DISTINCT ON (cd.id) cd.id AS id_khach_hang,
            cd.id,
            cd.ten_khach_hang,
            cd.pid,
            cd.ngay_sinh,
            cd.chuyen_vien_tu_van,
            cd.nguon_1,
            cd.nguoi_gioi_thieu_id,
            cd.nguoi_gioi_thieu_khach_hang,
            cd.nguoi_gioi_thieu_khach_hang_pid,
            cd.co_phuc_loi_tap_doan,
            cd.quan_he_voi_cap_quyen_loi_ap_dung,
            cd.cap_quyen_loi_ap_dung,
            cd.cong_ty_1,
            cd.ten_bao_hiem_thanh_toan
           FROM customer_data cd
          WHERE (cd.id IS NOT NULL)
          ORDER BY cd.id, cd.ngay_cuoi_cap_nhat DESC
        ), period_sales AS (
         SELECT sr.id_khach_hang,
            sr.ma_hoa_don,
            sr.loai_du_lieu,
            sr.loai_doanh_thu,
            sr.san_pham,
            sr.ten_doi_tuong_thanh_toan,
            sr.so_tien_thuc_te_thu,
            sr.ngay_cap_nhat_hoa_don_cuoi
           FROM sales_revenue sr
          WHERE (((sr.ngay_ghi)::date > '2025-12-31'::date) AND ((sr.ngay_ghi)::date < '2026-07-16'::date))
        ), latest_period_bill AS (
         SELECT ps.id_khach_hang,
            ps.ma_hoa_don,
            ps.loai_du_lieu,
            ps.loai_doanh_thu,
            ps.san_pham,
            ps.ten_doi_tuong_thanh_toan,
            ps.so_tien_thuc_te_thu,
            ps.ngay_cap_nhat_hoa_don_cuoi,
            row_number() OVER (PARTITION BY ps.ma_hoa_don ORDER BY ps.ngay_cap_nhat_hoa_don_cuoi DESC) AS rn
           FROM period_sales ps
        ), valid_bill AS (
         SELECT lpb.id_khach_hang,
            lpb.ma_hoa_don,
            lpb.loai_du_lieu,
            lpb.loai_doanh_thu,
            lpb.san_pham,
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
        ), bill_window AS (
         SELECT vb.id_khach_hang,
            count(DISTINCT
                CASE
                    WHEN (vb.loai_doanh_thu = 'Thuốc đông y'::text) THEN vb.ma_hoa_don
                    ELSE NULL::text
                END) AS so_don_thuoc,
            sum(
                CASE
                    WHEN (vb.loai_doanh_thu = 'Thuốc đông y'::text) THEN vb.revenue
                    ELSE (0)::numeric
                END) AS dt_thuoc,
            sum(
                CASE
                    WHEN (vb.loai_doanh_thu = ANY (ARRAY['Biệt dược'::text, 'Sản phẩm'::text])) THEN vb.revenue
                    ELSE (0)::numeric
                END) AS dt_bdvasp,
            sum(
                CASE
                    WHEN (vb.loai_doanh_thu = 'FnB'::text) THEN vb.revenue
                    ELSE (0)::numeric
                END) AS dt_fnb,
            sum(
                CASE
                    WHEN (vb.loai_doanh_thu <> ALL (ARRAY['Thuốc đông y'::text, 'Biệt dược'::text, 'Sản phẩm'::text])) THEN vb.revenue
                    ELSE (0)::numeric
                END) AS dt_khongdungthuoc,
            sum(vb.revenue) AS tongdt
           FROM valid_bill vb
          GROUP BY vb.id_khach_hang
        ), combo_totals AS (
         SELECT vb.id_khach_hang,
            (count(DISTINCT vb.ma_hoa_don))::numeric AS so_lan_len_goi
           FROM valid_bill vb
          WHERE ((vb.loai_du_lieu = 'Thông tin thanh toán'::text) AND (vb.loai_doanh_thu = 'Gói trị liệu'::text) AND ((vb.san_pham ~~ '%Xoa bóp%'::text) OR (vb.san_pham ~~ '%Hào châm%'::text)))
          GROUP BY vb.id_khach_hang
        ), first_last_day AS (
         SELECT sr.id_khach_hang,
            min((sr.ngay_ghi)::date) AS "Ngay_dau_tien",
            max((sr.ngay_ghi)::date) AS "Ngay_cuoi_cung"
           FROM (sales_revenue sr
             LEFT JOIN cancellation_bills cb ON ((sr.ma_hoa_don = cb.ma_hoa_don)))
          WHERE (cb.ma_hoa_don IS NULL)
          GROUP BY sr.id_khach_hang
        )
 SELECT lc.id,
    lc.ten_khach_hang,
    lc.pid,
    ('1899-12-30'::date + (floor((NULLIF((lc.ngay_sinh)::text, ''::text))::numeric))::integer) AS ngay_sinh_chuan,
    lc.chuyen_vien_tu_van,
    lc.nguon_1,
    lc.nguoi_gioi_thieu_id,
    lc.nguoi_gioi_thieu_khach_hang,
    lc.nguoi_gioi_thieu_khach_hang_pid,
    lc.co_phuc_loi_tap_doan,
    lc.quan_he_voi_cap_quyen_loi_ap_dung,
    lc.cap_quyen_loi_ap_dung,
    lc.cong_ty_1,
    lc.ten_bao_hiem_thanh_toan,
    fld."Ngay_dau_tien",
    fld."Ngay_cuoi_cung",
    COALESCE(bw.so_don_thuoc, (0)::bigint) AS so_don_thuoc,
    COALESCE(bw.dt_thuoc, (0)::numeric) AS dt_thuoc,
    COALESCE(bw.dt_bdvasp, (0)::numeric) AS dt_bdvasp,
    COALESCE(bw.dt_fnb, (0)::numeric) AS dt_fnb,
    COALESCE(ct.so_lan_len_goi, (0)::numeric) AS so_lan_len_goi,
    COALESCE(bw.dt_khongdungthuoc, (0)::numeric) AS dt_khongdungthuoc,
    COALESCE(bw.tongdt, (0)::numeric) AS tongdt
   FROM (((latest_customer lc
     JOIN bill_window bw ON ((lc.id_khach_hang = bw.id_khach_hang)))
     LEFT JOIN combo_totals ct ON ((lc.id_khach_hang = ct.id_khach_hang)))
     LEFT JOIN first_last_day fld ON ((lc.id_khach_hang = fld.id_khach_hang)));