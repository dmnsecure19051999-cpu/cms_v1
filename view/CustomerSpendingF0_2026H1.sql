CREATE OR REPLACE VIEW "Update_Customer_Info"."CustomerSpendingF0_2026H1" AS
WITH latest_customer AS (
    SELECT DISTINCT ON ((cd.id)::text)
        (cd.id)::text AS id_khach_hang,
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
    FROM public.customer_data cd
    WHERE cd.id IS NOT NULL
    ORDER BY (cd.id)::text, cd.ngay_cuoi_cap_nhat DESC
),
period_sales AS (
    SELECT
        (sr.id_khach_hang)::text AS id_khach_hang,
        (sr.ma_hoa_don)::text AS ma_hoa_don,
        (sr.loai_du_lieu)::text AS loai_du_lieu,
        (sr.loai_doanh_thu)::text AS loai_doanh_thu,
        (sr.san_pham)::text AS san_pham,
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
        lpb.ma_hoa_don,
        lpb.loai_du_lieu,
        lpb.loai_doanh_thu,
        lpb.san_pham,
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
bill_window AS (
    SELECT
        vb.id_khach_hang,
        COUNT(DISTINCT CASE WHEN vb.loai_doanh_thu = 'Thuốc đông y' THEN vb.ma_hoa_don END) AS so_don_thuoc,
        SUM(CASE WHEN vb.loai_doanh_thu = 'Thuốc đông y' THEN vb.revenue ELSE 0 END) AS dt_thuoc,
        SUM(CASE WHEN vb.loai_doanh_thu IN ('Biệt dược', 'Sản phẩm') THEN vb.revenue ELSE 0 END) AS dt_bdvasp,
        SUM(CASE WHEN vb.loai_doanh_thu = 'FnB' THEN vb.revenue ELSE 0 END) AS dt_fnb,
        SUM(CASE WHEN vb.loai_doanh_thu NOT IN ('Thuốc đông y', 'Biệt dược', 'Sản phẩm') THEN vb.revenue ELSE 0 END) AS dt_khongdungthuoc,
        SUM(vb.revenue) AS tongdt
    FROM valid_bill vb
    GROUP BY vb.id_khach_hang
),
combo_totals AS (
    SELECT
        vb.id_khach_hang,
        COUNT(DISTINCT vb.ma_hoa_don)::numeric AS so_lan_len_goi
    FROM valid_bill vb
    WHERE vb.loai_du_lieu = 'Thông tin thanh toán'
      AND vb.loai_doanh_thu = 'Gói trị liệu'
      AND (vb.san_pham LIKE '%Xoa bóp%' OR vb.san_pham LIKE '%Hào châm%')
    GROUP BY vb.id_khach_hang
),
first_last_day AS (
    SELECT
        (sr.id_khach_hang)::text AS id_khach_hang,
        MIN((sr.ngay_ghi)::date) AS "Ngay_dau_tien",
        MAX((sr.ngay_ghi)::date) AS "Ngay_cuoi_cung"
    FROM public.sales_revenue sr
    LEFT JOIN public.cancellation_bills cb
        ON (sr.ma_hoa_don)::text = (cb.ma_hoa_don)::text
    WHERE cb.ma_hoa_don IS NULL
    GROUP BY (sr.id_khach_hang)::text
)
SELECT
    lc.id,
    lc.ten_khach_hang,
    lc.pid,
    (DATE '1899-12-30' + FLOOR(NULLIF((lc.ngay_sinh)::text, '')::numeric)::integer) AS ngay_sinh_chuan,
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
    COALESCE(bw.so_don_thuoc, 0) AS so_don_thuoc,
    COALESCE(bw.dt_thuoc, 0) AS dt_thuoc,
    COALESCE(bw.dt_bdvasp, 0) AS dt_bdvasp,
    COALESCE(bw.dt_fnb, 0) AS dt_fnb,
    COALESCE(ct.so_lan_len_goi, 0::numeric) AS so_lan_len_goi,
    COALESCE(bw.dt_khongdungthuoc, 0) AS dt_khongdungthuoc,
    COALESCE(bw.tongdt, 0) AS tongdt
FROM latest_customer lc
JOIN bill_window bw
    ON lc.id_khach_hang = bw.id_khach_hang
LEFT JOIN combo_totals ct
    ON lc.id_khach_hang = ct.id_khach_hang
LEFT JOIN first_last_day fld
    ON lc.id_khach_hang = fld.id_khach_hang;